#!/usr/bin/env python3
"""
Betfair Paper Trader

SQLite-based paper trading for Betfair markets.
Simulates order execution at current market prices.

Usage:
    python paper_trader.py status          # Show portfolio
    python paper_trader.py run             # Check signals, execute trades
    python paper_trader.py history         # Show trade history
    python paper_trader.py reset           # Reset portfolio
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Constants
DB_PATH = Path(__file__).parent / "betfair.db"
INITIAL_BALANCE = 1000.00  # £1000 paper money
MAX_POSITIONS = 5
DEFAULT_STAKE = 10.00  # £10 per bet
MAX_STAKE_PCT = 0.05  # Max 5% of balance per bet


def init_db():
    """Initialize SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 1000.0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY,
            market_id TEXT NOT NULL,
            selection_id INTEGER NOT NULL,
            event_name TEXT,
            selection_name TEXT,
            bet_type TEXT NOT NULL,  -- 'BACK' or 'LAY'
            odds REAL NOT NULL,
            stake REAL NOT NULL,
            potential_profit REAL NOT NULL,
            potential_loss REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN, WON, LOST, VOID
            opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT,
            result_profit REAL
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            position_id INTEGER,
            market_id TEXT NOT NULL,
            selection_id INTEGER NOT NULL,
            action TEXT NOT NULL,  -- 'OPEN', 'CLOSE', 'WIN', 'LOSE'
            bet_type TEXT NOT NULL,
            odds REAL NOT NULL,
            stake REAL NOT NULL,
            profit_loss REAL,
            balance_after REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (position_id) REFERENCES positions(id)
        )
    """)
    
    # Initialize portfolio if empty
    c.execute("SELECT COUNT(*) FROM portfolio")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO portfolio (balance) VALUES (?)", (INITIAL_BALANCE,))
    
    conn.commit()
    return conn


def get_balance(conn: sqlite3.Connection) -> float:
    """Get current balance."""
    c = conn.cursor()
    c.execute("SELECT balance FROM portfolio ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    return row["balance"] if row else INITIAL_BALANCE


def update_balance(conn: sqlite3.Connection, new_balance: float):
    """Update balance."""
    c = conn.cursor()
    c.execute("""
        UPDATE portfolio 
        SET balance = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = (SELECT MAX(id) FROM portfolio)
    """, (new_balance,))
    conn.commit()


def get_open_positions(conn: sqlite3.Connection) -> list:
    """Get all open positions."""
    c = conn.cursor()
    c.execute("""
        SELECT * FROM positions 
        WHERE status = 'OPEN'
        ORDER BY opened_at DESC
    """)
    return [dict(row) for row in c.fetchall()]


def get_realized_pnl(conn: sqlite3.Connection) -> float:
    """Get total realized P&L."""
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(SUM(result_profit), 0) as pnl
        FROM positions
        WHERE status IN ('WON', 'LOST')
    """)
    return c.fetchone()["pnl"]


def place_bet(
    conn: sqlite3.Connection,
    market_id: str,
    selection_id: int,
    event_name: str,
    selection_name: str,
    bet_type: str,  # 'BACK' or 'LAY'
    odds: float,
    stake: float
) -> Optional[int]:
    """
    Place a paper bet.
    
    BACK bet: Win (odds-1)*stake if selection wins, lose stake if loses
    LAY bet: Win stake if selection loses, lose (odds-1)*stake if wins
    """
    balance = get_balance(conn)
    
    # Calculate risk
    if bet_type == "BACK":
        potential_profit = (odds - 1) * stake
        potential_loss = stake
        required = stake
    else:  # LAY
        potential_profit = stake
        potential_loss = (odds - 1) * stake
        required = potential_loss  # Liability
    
    if required > balance:
        print(f"❌ Insufficient balance: need £{required:.2f}, have £{balance:.2f}")
        return None
    
    c = conn.cursor()
    
    # Create position
    c.execute("""
        INSERT INTO positions 
        (market_id, selection_id, event_name, selection_name, bet_type, odds, stake, potential_profit, potential_loss)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (market_id, selection_id, event_name, selection_name, bet_type, odds, stake, potential_profit, potential_loss))
    position_id = c.lastrowid
    
    # Deduct stake/liability
    new_balance = balance - required
    update_balance(conn, new_balance)
    
    # Record trade
    c.execute("""
        INSERT INTO trades 
        (position_id, market_id, selection_id, action, bet_type, odds, stake, balance_after)
        VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?)
    """, (position_id, market_id, selection_id, bet_type, odds, stake, new_balance))
    
    conn.commit()
    
    print(f"✅ {bet_type} £{stake:.2f} @ {odds:.2f} on {selection_name}")
    print(f"   Potential profit: £{potential_profit:.2f} | Risk: £{potential_loss:.2f}")
    
    return position_id


def settle_position(conn: sqlite3.Connection, position_id: int, won: bool, commission: float = 0.05):
    """
    Settle a position as won or lost, with Betfair commission deducted on net winnings.
    
    For BACK bets: won=True means the selection won (our back bet won).
    For LAY bets: won=True means the selection lost (our lay bet won).
    
    Args:
        conn: Database connection
        position_id: Position to settle
        won: Whether our position was correct (True = we profit)
        commission: Betfair commission rate on net winnings (default 5%)
    """
    c = conn.cursor()
    c.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
    pos = c.fetchone()
    
    if not pos:
        print(f"❌ Position {position_id} not found")
        return
    
    if pos["status"] != "OPEN":
        print(f"❌ Position {position_id} already settled")
        return
    
    balance = get_balance(conn)
    bet_type = pos["bet_type"]
    
    # Calculate P&L (with Betfair commission on net winnings)
    if bet_type == "BACK":
        if won:
            # We backed the selection, it won
            gross_profit = pos["potential_profit"]  # (odds-1)*stake
            commission_deduction = gross_profit * commission
            profit = pos["potential_profit"] + pos["stake"] - commission_deduction
            result_profit = gross_profit - commission_deduction
            status = "WON"
        else:
            # We backed the selection, it lost
            profit = 0  # Stake already deducted
            result_profit = -(pos["stake"])
            status = "LOST"
    else:  # LAY
        if won:
            # We laid the selection, it lost → our lay won
            gross_profit = pos["potential_profit"]  # stake amount we won
            commission_deduction = gross_profit * commission
            profit = pos["potential_profit"] + pos["potential_loss"] - commission_deduction
            result_profit = gross_profit - commission_deduction
            status = "WON"
        else:
            # We laid the selection, it won → our lay lost
            profit = 0  # Liability already deducted
            result_profit = -(pos["potential_loss"])
            status = "LOST"
    
    new_balance = balance + profit
    
    # Update position
    c.execute("""
        UPDATE positions 
        SET status = ?, closed_at = CURRENT_TIMESTAMP, result_profit = ?
        WHERE id = ?
    """, (status, result_profit, position_id))
    
    update_balance(conn, new_balance)
    
    # Record trade
    c.execute("""
        INSERT INTO trades 
        (position_id, market_id, selection_id, action, bet_type, odds, stake, profit_loss, balance_after)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (position_id, pos["market_id"], pos["selection_id"], status, bet_type, pos["odds"], pos["stake"], result_profit, new_balance))
    
    conn.commit()
    
    emoji = "🎉" if status == "WON" else "😢"
    comm_str = f" (commission: £{abs(result_profit) * commission:.2f})" if status == "WON" else ""
    print(f"{emoji} Position {position_id} {status}: £{result_profit:+.2f}{comm_str}")


def show_status(conn: sqlite3.Connection):
    """Show portfolio status."""
    balance = get_balance(conn)
    positions = get_open_positions(conn)
    realized_pnl = get_realized_pnl(conn)
    
    print("🎰 **BETFAIR PAPER TRADER**")
    print("━" * 26)
    print(f"💰 Balance: £{balance:,.2f}")
    print(f"📊 Positions: {len(positions)}/{MAX_POSITIONS}")
    print(f"📈 Realized P&L: £{realized_pnl:+,.2f}")
    
    if positions:
        print("\n**Open Positions:**")
        for pos in positions:
            emoji = "📈" if pos["bet_type"] == "BACK" else "📉"
            print(f"  {emoji} {pos['selection_name'] or pos['selection_id']} ({pos['bet_type']})")
            print(f"     @ {pos['odds']:.2f} | Stake: £{pos['stake']:.2f} | Risk: £{pos['potential_loss']:.2f}")


def show_history(conn: sqlite3.Connection, limit: int = 20):
    """Show trade history."""
    c = conn.cursor()
    c.execute("""
        SELECT t.*, p.event_name, p.selection_name
        FROM trades t
        LEFT JOIN positions p ON t.position_id = p.id
        ORDER BY t.created_at DESC
        LIMIT ?
    """, (limit,))
    
    trades = c.fetchall()
    
    print("📜 **TRADE HISTORY**")
    print("━" * 20)
    
    for t in trades:
        action = t["action"]
        if action == "OPEN":
            emoji = "🔓"
        elif action == "WON":
            emoji = "🎉"
        elif action == "LOST":
            emoji = "😢"
        else:
            emoji = "📝"
        
        pnl_str = f" £{t['profit_loss']:+.2f}" if t["profit_loss"] else ""
        print(f"  {emoji} {action} {t['bet_type']} @ {t['odds']:.2f}{pnl_str}")
        print(f"     {t['selection_name'] or t['selection_id']} | {t['created_at'][:16]}")


def reset_portfolio(conn: sqlite3.Connection):
    """Reset portfolio to initial state."""
    c = conn.cursor()
    c.execute("DELETE FROM trades")
    c.execute("DELETE FROM positions")
    c.execute("UPDATE portfolio SET balance = ?, updated_at = CURRENT_TIMESTAMP", (INITIAL_BALANCE,))
    conn.commit()
    print(f"🔄 Portfolio reset to £{INITIAL_BALANCE:,.2f}")


def run_signals(conn: sqlite3.Connection):
    """
    Check signals and execute trades.
    
    This is a placeholder - actual signal generation requires:
    1. BetfairClient with valid credentials
    2. signal_engine.py implementation
    """
    print("🔍 Checking signals...")
    print("⚠️  No Betfair credentials configured")
    print("   Add credentials to config/credentials.json to enable live signals")
    print()
    
    # Check for existing positions that might need settlement
    positions = get_open_positions(conn)
    if positions:
        print(f"📊 {len(positions)} open position(s) - manual settlement required")
        print("   Use: paper_trader.py settle <position_id> <won|lost>")


def settle_command(conn: sqlite3.Connection, position_id: int, result: str):
    """Settle a position from command line."""
    if result.lower() in ("won", "win", "w", "1", "true"):
        settle_position(conn, position_id, won=True)
    elif result.lower() in ("lost", "lose", "l", "0", "false"):
        settle_position(conn, position_id, won=False)
    else:
        print(f"❌ Invalid result: {result}. Use 'won' or 'lost'")


def main():
    """CLI entry point."""
    conn = init_db()
    
    if len(sys.argv) < 2:
        show_status(conn)
        return
    
    cmd = sys.argv[1].lower()
    
    if cmd == "status":
        show_status(conn)
    elif cmd == "run":
        show_status(conn)
        print()
        run_signals(conn)
    elif cmd == "history":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        show_history(conn, limit)
    elif cmd == "reset":
        confirm = input("Reset portfolio? This deletes all trades. (yes/no): ")
        if confirm.lower() == "yes":
            reset_portfolio(conn)
        else:
            print("Cancelled")
    elif cmd == "settle":
        if len(sys.argv) < 4:
            print("Usage: paper_trader.py settle <position_id> <won|lost>")
            return
        settle_command(conn, int(sys.argv[2]), sys.argv[3])
    elif cmd == "test":
        # Test placing a bet (no real Betfair connection needed)
        print("📝 Placing test bet...")
        place_bet(
            conn,
            market_id="1.234567890",
            selection_id=12345,
            event_name="Test Event - Team A vs Team B",
            selection_name="Team A",
            bet_type="BACK",
            odds=2.50,
            stake=10.00
        )
        print()
        show_status(conn)
    else:
        print(f"Unknown command: {cmd}")
        print("Commands: status, run, history, reset, settle, test")


if __name__ == "__main__":
    main()
