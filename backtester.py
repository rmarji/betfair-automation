#!/usr/bin/env python3
"""
Betfair Backtester

Runs historical Pickwatch picks through the signal engine and paper trader
to determine whether the strategy has positive expected value (EV).

Supports:
- Full historical replay with configurable bankroll
- Kelly Criterion vs flat staking comparison
- Sport-by-sport breakdown
- Edge bracket analysis
- Rolling ROI chart data

Usage:
    python backtester.py                # Full backtest
    python backtester.py --sport NBA    # Sport-specific
    python backtester.py --flat        # Flat staking (no Kelly)
    python backtester.py --bankroll 500 # Custom starting bankroll
"""

import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from pickwatch_adapter import (
    american_to_decimal,
    compute_pickwatch_stats,
    get_historical_picks,
    PICKWATCH_DB,
)
from signal_engine import SignalEngine, SignalStrength, BetType


PICKWATCH_DB_PATH = str(PICKWATCH_DB)
BETFAIR_DB = Path(__file__).parent / "backtest_results.db"

DEFAULT_BANKROLL = 1000.0
DEFAULT_MIN_EDGE = 5.0  # Minimum edge % to include
BETFAIR_COMMISSION = 0.05  # 5% commission on net winnings (standard)


@dataclass
class BacktestResult:
    """Results of a single backtest run."""
    bankroll_start: float
    bankroll_end: float
    total_bets: int
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    total_staked: float = 0.0
    total_returned: float = 0.0
    total_commission: float = 0.0
    roi_pct: float = 0.0
    win_rate: float = 0.0
    avg_edge: float = 0.0
    profit_loss: float = 0.0
    max_drawdown: float = 0.0
    kelly_staking: bool = True
    by_sport: dict = field(default_factory=dict)
    by_edge_bracket: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)

    def summary(self) -> str:
        """Formatted summary for terminal output."""
        emoji = "🟢" if self.roi_pct > 0 else "🔴" if self.roi_pct < 0 else "⚪"
        lines = [
            f"{emoji} **BACKTEST RESULTS**",
            f"━" * 28,
            f"💰 Bankroll: £{self.bankroll_start:,.0f} → £{self.bankroll_end:,.2f}",
            f"📊 P&L: £{self.profit_loss:+,.2f} ({self.roi_pct:+.1f}% ROI)",
            f"🎲 Bets: {self.total_bets} ({self.wins}W-{self.losses}L-{self.pushes}P)",
            f"📈 Win Rate: {self.win_rate:.1f}%",
            f"⚡ Avg Edge: {self.avg_edge:.1f}%",
            f"📉 Max Drawdown: £{self.max_drawdown:,.2f}",
            f"💶 Commission paid: £{self.total_commission:,.2f}",
            f"🎯 Staking: {'Kelly' if self.kelly_staking else 'Flat'}",
        ]
        return "\n".join(lines)


def kelly_stake(edge_pct: float, odds: float, bankroll: float, fraction: float = 0.25) -> float:
    """
    Kelly Criterion stake sizing.
    
    Uses fractional Kelly (default 1/4 Kelly) for safety.
    
    Args:
        edge_pct: Edge as fraction (e.g. 0.15 for 15%)
        odds: Decimal odds
        bankroll: Current bankroll
        fraction: Kelly fraction (0.25 = quarter Kelly)
    
    Returns:
        Stake amount in currency units
    """
    if odds <= 1.0 or edge_pct <= 0:
        return 0.0
    
    # p = implied probability from edge
    # If edge = (odds * p - 1), then p = (1 + edge) / odds
    # But we get edge as a fraction, so:
    # Kelly % = edge / (odds - 1) simplified for back bets
    # Full Kelly: f* = (bp - q) / b where b = odds-1, p = win probability, q = 1-p
    
    win_prob = (1 + edge_pct) / odds  # Backed out from edge
    lose_prob = 1 - win_prob
    
    if win_prob <= 0 or win_prob >= 1:
        return 0.0
    
    b = odds - 1  # Net odds
    kelly_pct = (b * win_prob - lose_prob) / b
    
    if kelly_pct <= 0:
        return 0.0
    
    # Apply fractional Kelly
    stake = bankroll * kelly_pct * fraction
    
    # Cap at 5% of bankroll
    max_stake = bankroll * 0.05
    stake = min(stake, max_stake)
    
    # Minimum stake
    stake = max(stake, 1.0)
    
    return round(stake, 2)


def flat_stake(bankroll: float, pct: float = 0.02) -> float:
    """Flat staking: fixed % of starting bankroll."""
    return round(bankroll * pct, 2)


def run_backtest(
    db_path: Optional[str] = None,
    sport: Optional[str] = None,
    bankroll: float = DEFAULT_BANKROLL,
    min_edge: float = DEFAULT_MIN_EDGE,
    use_kelly: bool = True,
    min_confidence: float = 60.0,
    recommendations: tuple = ("BET", "STRONG BET"),
) -> BacktestResult:
    """
    Run a backtest using historical Pickwatch data.
    
    Simulates placing bets on historical picks and tracking
    cumulative P&L with Betfair commission deducted.
    
    Args:
        db_path: Path to Pickwatch DB
        sport: Filter to specific sport
        bankroll: Starting bankroll
        min_edge: Minimum edge % to include
        use_kelly: Use Kelly Criterion for stake sizing
        min_confidence: Minimum Pickwatch confidence score
        recommendations: Which recommendation levels to include
    
    Returns:
        BacktestResult with full statistics
    """
    path = db_path or PICKWATCH_DB_PATH
    
    if not Path(path).exists():
        print(f"❌ Pickwatch DB not found at {path}")
        return BacktestResult(bankroll_start=bankroll, bankroll_end=bankroll,
                              total_bets=0)
    
    # Fetch historical picks with outcomes
    picks = get_historical_picks(sport=sport, limit=5000, db_path=path)
    
    # Filter by criteria
    filtered = []
    for pick in picks:
        edge = pick.get("edge", 0) or 0
        confidence = pick.get("confidence_score", 0) or 0
        rec = pick.get("recommendation", "")
        
        if edge < min_edge:
            continue
        if confidence < min_confidence:
            continue
        if rec not in recommendations:
            continue
        
        filtered.append(pick)
    
    if not filtered:
        print("⚠️  No picks match the criteria")
        return BacktestResult(bankroll_start=bankroll, bankroll_end=bankroll,
                              total_bets=0)
    
    # Sort by date for chronological replay
    filtered.sort(key=lambda p: p.get("date", ""))
    
    # Initialize tracking
    result = BacktestResult(
        bankroll_start=bankroll,
        bankroll_end=bankroll,
        total_bets=len(filtered),
        kelly_staking=use_kelly,
    )
    
    current_bankroll = bankroll
    peak_bankroll = bankroll
    max_drawdown = 0.0
    equity_curve = [bankroll]
    
    total_staked = 0.0
    total_returned = 0.0
    total_commission = 0.0
    total_edge = 0.0
    
    wins = 0
    losses = 0
    pushes = 0
    
    by_sport = {}
    by_edge = {}
    
    for pick in filtered:
        sport_name = pick.get("sport", "unknown")
        edge = (pick.get("edge", 0) or 0)
        edge_frac = edge / 100.0
        odds_american = pick.get("odds_american", 0) or 0
        odds_decimal = american_to_decimal(odds_american)
        outcome = (pick.get("outcome") or "").upper()
        
        if odds_decimal <= 1.0:
            continue
        
        # Calculate stake
        if use_kelly:
            stake = kelly_stake(edge_frac, odds_decimal, current_bankroll)
        else:
            stake = flat_stake(bankroll)  # Flat based on initial bankroll
        
        if stake <= 0 or stake > current_bankroll:
            continue
        
        # Track
        total_staked += stake
        total_edge += edge
        
        # Simulate outcome
        if outcome == "WIN":
            gross_return = stake * odds_decimal  # Total return including stake
            net_winnings = stake * (odds_decimal - 1)
            commission = net_winnings * BETFAIR_COMMISSION
            net_return = stake + net_winnings - commission
            
            current_bankroll = current_bankroll - stake + net_return
            total_returned += net_return
            total_commission += commission
            wins += 1
            profit = net_return - stake
            
        elif outcome == "LOSS":
            current_bankroll -= stake
            total_returned += 0
            losses += 1
            profit = -stake
            
        elif outcome == "PUSH":
            current_bankroll -= stake
            current_bankroll += stake  # Return stake
            total_returned += stake
            pushes += 1
            profit = 0
            
        else:
            # Unknown outcome, skip
            continue
        
        # Track by sport
        if sport_name not in by_sport:
            by_sport[sport_name] = {
                "bets": 0, "wins": 0, "losses": 0, "pushes": 0,
                "staked": 0.0, "returned": 0.0, "commission": 0.0
            }
        s = by_sport[sport_name]
        s["bets"] += 1
        s["staked"] += stake
        s["returned"] += total_returned if profit != -stake else 0  # fix: only add for this pick
        if outcome == "WIN":
            s["wins"] += 1
            s["commission"] += commission
        elif outcome == "LOSS":
            s["losses"] += 1
        elif outcome == "PUSH":
            s["pushes"] += 1
        
        # Track by edge bracket
        if edge >= 35:
            bracket = "35+"
        elif edge >= 25:
            bracket = "25-35"
        elif edge >= 15:
            bracket = "15-25"
        else:
            bracket = "<15"
        
        if bracket not in by_edge:
            by_edge[bracket] = {
                "bets": 0, "wins": 0, "losses": 0, "staked": 0.0, "returned": 0.0
            }
        e = by_edge[bracket]
        e["bets"] += 1
        e["staked"] += stake
        if outcome == "WIN":
            e["wins"] += 1
            e["returned"] += stake + stake * (odds_decimal - 1) * (1 - BETFAIR_COMMISSION)
        elif outcome == "LOSS":
            e["losses"] += 1
        
        # Drawdown tracking
        if current_bankroll > peak_bankroll:
            peak_bankroll = current_bankroll
        
        drawdown = peak_bankroll - current_bankroll
        if drawdown > max_drawdown:
            max_drawdown = drawdown
        
        equity_curve.append(round(current_bankroll, 2))
    
    # Populate result
    result.bankroll_end = round(current_bankroll, 2)
    result.wins = wins
    result.losses = losses
    result.pushes = pushes
    result.total_staked = round(total_staked, 2)
    result.total_returned = round(total_returned, 2)
    result.total_commission = round(total_commission, 2)
    result.profit_loss = round(current_bankroll - bankroll, 2)
    result.roi_pct = round((current_bankroll - bankroll) / bankroll * 100, 1) if bankroll > 0 else 0
    result.win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0
    result.avg_edge = round(total_edge / len(filtered), 1) if filtered else 0
    result.max_drawdown = round(max_drawdown, 2)
    result.by_sport = by_sport
    result.by_edge_bracket = by_edge
    result.equity_curve = equity_curve
    
    return result


def print_sport_breakdown(result: BacktestResult):
    """Print per-sport stats."""
    print("\n📋 **BY SPORT**")
    print("━" * 28)
    
    for sport, s in sorted(result.by_sport.items()):
        wr = (s["wins"] / (s["wins"] + s["losses"]) * 100) if (s["wins"] + s["losses"]) > 0 else 0
        pnl = s["returned"] - s["staked"]
        roi = (pnl / s["staked"] * 100) if s["staked"] > 0 else 0
        emoji = "🟢" if roi > 0 else "🔴"
        print(f"  {emoji} {sport}: {s['wins']}W-{s['losses']}L ({wr:.0f}%) | ROI: {roi:+.1f}%")


def print_edge_breakdown(result: BacktestResult):
    """Print per-edge bracket stats."""
    print("\n📊 **BY EDGE BRACKET**")
    print("━" * 28)
    
    bracket_order = ["<15", "15-25", "25-35", "35+"]
    for bracket in bracket_order:
        if bracket not in result.by_edge_bracket:
            continue
        e = result.by_edge_bracket[bracket]
        wr = (e["wins"] / (e["wins"] + e["losses"]) * 100) if (e["wins"] + e["losses"]) > 0 else 0
        pnl = e["returned"] - e["staked"]
        roi = (pnl / e["staked"] * 100) if e["staked"] > 0 else 0
        emoji = "🟢" if roi > 0 else "🔴"
        print(f"  {emoji} {bracket:>5}% edge: {e['wins']}W-{e['losses']}L ({wr:.0f}%) | ROI: {roi:+.1f}%")


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Betfair Strategy Backtester")
    parser.add_argument("--sport", type=str, help="Filter to specific sport (NBA, NHL, MLB, NFL)")
    parser.add_argument("--bankroll", type=float, default=DEFAULT_BANKROLL, help="Starting bankroll")
    parser.add_argument("--min-edge", type=float, default=DEFAULT_MIN_EDGE, help="Minimum edge %%")
    parser.add_argument("--flat", action="store_true", help="Use flat staking instead of Kelly")
    parser.add_argument("--min-confidence", type=float, default=60.0, help="Minimum confidence score")
    parser.add_argument("--db", type=str, help="Path to Pickwatch DB")
    
    args = parser.parse_args()
    
    print("🎰 **BETFAIR BACKTESTER**")
    print("━" * 28)
    
    if args.sport:
        print(f"🎯 Sport: {args.sport}")
    print(f"💰 Bankroll: £{args.bankroll:,.0f}")
    print(f"⚡ Min Edge: {args.min_edge}%")
    print(f"🎯 Staking: {'Flat' if args.flat else 'Kelly (1/4)'}")
    print(f"📊 Min Confidence: {args.min_confidence}%")
    print()
    
    result = run_backtest(
        db_path=args.db,
        sport=args.sport,
        bankroll=args.bankroll,
        min_edge=args.min_edge,
        use_kelly=not args.flat,
        min_confidence=args.min_confidence,
    )
    
    print(result.summary())
    print_sport_breakdown(result)
    print_edge_breakdown(result)
    
    # Save results to DB for later analysis
    save_results(result, sport=args.sport)
    
    print(f"\n💾 Results saved to {BETFAIR_DB}")


def save_results(result: BacktestResult, sport: Optional[str] = None):
    """Save backtest results to SQLite for historical comparison."""
    conn = sqlite3.connect(BETFAIR_DB)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY,
            run_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sport TEXT,
            bankroll_start REAL,
            bankroll_end REAL,
            total_bets INTEGER,
            wins INTEGER,
            losses INTEGER,
            pushes INTEGER,
            roi_pct REAL,
            win_rate REAL,
            avg_edge REAL,
            max_drawdown REAL,
            total_staked REAL,
            total_commission REAL,
            kelly_staking INTEGER,
            equity_curve TEXT
        )
    """)
    
    import json
    c.execute("""
        INSERT INTO backtest_runs 
        (sport, bankroll_start, bankroll_end, total_bets, wins, losses, pushes,
         roi_pct, win_rate, avg_edge, max_drawdown, total_staked, total_commission,
         kelly_staking, equity_curve)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sport,
        result.bankroll_start,
        result.bankroll_end,
        result.total_bets,
        result.wins,
        result.losses,
        result.pushes,
        result.roi_pct,
        result.win_rate,
        result.avg_edge,
        result.max_drawdown,
        result.total_staked,
        result.total_commission,
        1 if result.kelly_staking else 0,
        json.dumps(result.equity_curve),
    ))
    
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()