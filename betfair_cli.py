#!/usr/bin/env python3
"""
Betfair Unified CLI

All-in-one command line interface for Betfair paper trading.

Usage:
    ./betfair_cli.py status          # Portfolio status
    ./betfair_cli.py run             # Execute trading cycle
    ./betfair_cli.py history         # Trade history
    ./betfair_cli.py signals         # Current signals
    ./betfair_cli.py markets         # Available markets
    ./betfair_cli.py health          # System health check
    ./betfair_cli.py reset           # Reset portfolio
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Import local modules
from paper_trader import (
    init_db, get_balance, get_open_positions,
    DB_PATH, INITIAL_BALANCE
)
from signal_engine import SignalEngine, BetType
from config import Config, format_config_display


def cmd_status(args):
    """Show portfolio status."""
    conn = init_db()
    balance = get_balance(conn)
    positions = get_open_positions(conn)
    position_count = len(positions)
    
    # Calculate unrealized P&L (simplified - would need live odds)
    unrealized = 0
    for pos in positions:
        # Estimate based on potential profit (simplified)
        unrealized += pos["potential_profit"] * 0.5  # rough estimate
    
    print("💰 **BETFAIR PORTFOLIO**")
    print("━" * 24)
    print(f"Balance:     £{balance:,.2f}")
    print(f"Positions:   {position_count}/5")
    print(f"Initial:     £{INITIAL_BALANCE:,.2f}")
    print(f"P&L:         £{balance - INITIAL_BALANCE:+,.2f}")
    
    if positions:
        print("\n**Open Positions:**")
        for pos in positions:
            emoji = "📈" if pos["bet_type"] == "BACK" else "📉"
            print(f"  {emoji} {pos['selection_name']}")
            print(f"     {pos['bet_type']} @ {pos['odds']:.2f}, £{pos['stake']:.2f}")
    
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    conn.close()


def cmd_run(args):
    """Execute trading cycle — Pickwatch-driven paper trades."""
    from pickwatch_adapter import (
        get_todays_picks, get_unresolved_picks,
        pickwatch_picks_to_market_data, compute_pickwatch_stats
    )
    from paper_trader import place_bet, MAX_POSITIONS
    from config import Config

    conn = init_db()
    balance = get_balance(conn)
    positions = get_open_positions(conn)
    position_count = len(positions)
    
    print("🤖 **TRADING CYCLE**")
    print("━" * 28)
    print(f"💰 Balance:     £{balance:,.2f}")
    print(f"📊 Positions:   {position_count}/{MAX_POSITIONS}")
    
    cfg = Config()
    
    # ── Source 1: Pickwatch data (local DB, always available) ──
    picks = get_todays_picks()
    print(f"\n📋 Pickwatch Picks Today: {len(picks)}")
    
    placed = 0
    skipped = 0
    
    if picks:
        markets = pickwatch_picks_to_market_data(picks)
        engine = SignalEngine()
        signals = engine.generate_signals(markets)
        
        print(f"📡 Signals Generated: {len(signals)}")
        
        for sig in signals[:5]:  # Max 5 signals per cycle
            print(f"\n  {sig.strength.name} {sig.event_name}")
            print(f"    {sig.bet_type.value} {sig.selection_name} @ {sig.odds:.2f}")
            print(f"    Edge: {sig.edge_pct*100:.1f}% | Conf: {sig.confidence*100:.0f}%")
            print(f"    {sig.reason}")
            
            # Check position limit
            if position_count >= MAX_POSITIONS:
                print(f"    ⛔ Max positions reached ({MAX_POSITIONS})")
                skipped += 1
                continue
            
            # Check duplicate market
            existing_markets = {p["market_id"] for p in positions}
            if sig.market_id in existing_markets:
                print(f"    ⏭️  Already have position in this market")
                skipped += 1
                continue
            
            # Kelly Criterion stake sizing
            b = sig.odds - 1  # net odds
            p = sig.confidence
            q = 1 - p
            kelly_frac = (b * p - q) / b if b > 0 else 0
            kelly_frac = max(0, min(kelly_frac, cfg.max_stake_pct))
            stake = round(balance * kelly_frac, 2)
            
            # Minimum stake
            if stake < 1.0:
                stake = min(cfg.default_stake, balance * cfg.max_stake_pct)
            stake = round(max(stake, 1.0), 2)
            
            pid = place_bet(
                conn,
                market_id=sig.market_id,
                selection_id=sig.selection_id,
                event_name=sig.event_name,
                selection_name=sig.selection_name,
                bet_type=sig.bet_type.value,
                odds=sig.odds,
                stake=stake,
            )
            if pid:
                placed += 1
                position_count += 1
                balance -= stake  # Track locally for next stake calc
    
    # ── Source 2: Betfair live (if credentials available) ──
    try:
        from betfair_client import BetfairClient
        app_key = os.environ.get("BETFAIR_APP_KEY")
        if app_key:
            client = BetfairClient.from_config(cfg.to_dict())
            all_signals = []
            for sport_id in [7524, 7522, 6423]:
                markets = client.list_markets(sport_id=sport_id, max_results=10)
                for m in markets:
                    m["fair_odds"] = {r["selection_id"]: r["odds"] * 0.95 for r in m["runners"]}
                signals = engine.generate_signals(markets)
                all_signals.extend(signals)
            if all_signals:
                print(f"\n📡 Betfair Live: {len(all_signals)} additional signals")
            client.logout()
    except Exception:
        pass  # No Betfair creds — Pickwatch-only mode
    
    # ── Summary ──
    if not picks:
        print("\n📭 No Pickwatch picks today — no trades placed")
        print("   Picks sync from Pickwatch dashboard daily")
    
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"✅ Placed: {placed}  ⏭️  Skipped: {skipped}")
    
    # Show open positions
    positions = get_open_positions(conn)
    if positions:
        print(f"\n📊 Open Positions ({len(positions)}):")
        for pos in positions:
            emoji = "📈" if pos["bet_type"] == "BACK" else "📉"
            print(f"  {emoji} {pos['selection_name']} {pos['bet_type']} @ {pos['odds']:.2f} £{pos['stake']:.2f}")
    
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    conn.close()


def cmd_history(args):
    """Show trade history."""
    conn = init_db()
    c = conn.cursor()
    
    limit = args.limit if hasattr(args, 'limit') else 10
    c.execute("""
        SELECT * FROM trades 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (limit,))
    trades = c.fetchall()
    
    print("📜 **TRADE HISTORY**")
    print("━" * 24)
    
    if not trades:
        print("No trades yet")
    else:
        for t in trades:
            emoji = "🟢" if (t["profit_loss"] or 0) >= 0 else "🔴"
            pl = t["profit_loss"] or 0
            print(f"{emoji} {t['action']} {t['bet_type']} @ {t['odds']:.2f}")
            print(f"   £{t['stake']:.2f} → £{pl:+.2f} | Bal: £{t['balance_after']:.2f}")
    
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    conn.close()


def cmd_signals(args):
    """Show current signals (simulated)."""
    engine = SignalEngine()
    
    print("📡 **SIGNAL SCAN**")
    print("━" * 24)
    print("⚠️  No live market data (credentials required)")
    print("\n**Signal Engine Ready:**")
    print("  ✅ Value Betting strategy")
    print("  ✅ Steam Moves strategy")
    print("  ✅ Pickwatch Integration")
    print("\nConnect Betfair API to generate signals")
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")


def cmd_markets(args):
    """Show available markets - with demo mode when no credentials."""
    from betfair_client import SPORT_IDS, MARKET_TYPES
    from pathlib import Path

    print("🏟️ **BETFAIR MARKETS**")
    print("━" * 28)

    # Check credentials
    cert_path = Path(__file__).parent / "config" / "betfair.crt"
    key_path = Path(__file__).parent / "config" / "betfair.key"
    has_creds = cert_path.exists() and key_path.exists()

    # Show sport catalog (always available)
    print("\n📋 **SPORT CATALOG**")
    print("━" * 28)

    sport_emojis = {
        "american_football": "🏈",
        "basketball": "🏀",
        "ice_hockey": "🏒",
        "soccer": "⚽",
        "tennis": "🎾",
        "horse_racing": "🏇",
        "golf": "⛳",
        "cricket": "🏏",
        "boxing": "🥊",
        "motor_sport": "🏎️",
    }

    for name, sport_id in sorted(SPORT_IDS.items()):
        emoji = sport_emojis.get(name, "🏆")
        print(f"  {emoji} {name.replace('_', ' ').title():20} ID: {sport_id}")

    # Show market types
    print("\n📊 **MARKET TYPES**")
    print("━" * 28)
    for name, code in MARKET_TYPES.items():
        print(f"  • {name.replace('_', ' ').title():15} ({code})")

    # Demo mode - sample markets for NHL/NBA/NFL
    if not has_creds or args.demo:
        print("\n🎮 **DEMO MODE** — Sample Markets")
        print("━" * 28)
        print("   (Connect Betfair API for live data)\n")

        demo_markets = [
            {
                "sport": "NHL",
                "event": "Toronto Maple Leafs vs Boston Bruins",
                "time": "2025-03-13 19:00",
                "markets": [
                    {"name": "Match Odds", "back": "2.10", "lay": "2.15"},
                    {"name": "Total Goals O/U 5.5", "back": "1.90", "lay": "1.95"},
                ]
            },
            {
                "sport": "NBA",
                "event": "Lakers vs Warriors",
                "time": "2025-03-13 22:30",
                "markets": [
                    {"name": "Match Odds", "back": "1.75", "lay": "1.80"},
                    {"name": "Spread +4.5", "back": "1.95", "lay": "2.00"},
                ]
            },
            {
                "sport": "NFL",
                "event": "Super Bowl LIX",
                "time": "2025-02-09 18:30",
                "markets": [
                    {"name": "Match Odds", "back": "1.85", "lay": "1.90"},
                    {"name": "Total Points O/U 47.5", "back": "1.91", "lay": "1.96"},
                ]
            },
        ]

        for m in demo_markets:
            print(f"  🏆 {m['sport']} — {m['event']}")
            print(f"     📅 {m['time']}")
            for market in m['markets']:
                print(f"     • {market['name']:<25} Back: {market['back']:<6} Lay: {market['lay']}")
            print()

        print("💡 **Usage with credentials:**")
        print("   ./betfair_cli.py markets --sport 7524    # NHL")
        print("   ./betfair_cli.py markets --sport 7522    # NBA")
        print("   ./betfair_cli.py markets --sport 6423    # NFL")

    else:
        # Live mode - try to fetch real markets
        try:
            from betfair_client import BetfairClient
            from config import Config

            cfg = Config()
            client = BetfairClient.from_config(cfg.to_dict())

            sport_id = args.sport if hasattr(args, 'sport') and args.sport else None

            if sport_id:
                sport_name = next((k for k, v in SPORT_IDS.items() if v == sport_id), "Unknown")
                print(f"\n📡 **LIVE MARKETS: {sport_name.upper()}**")
                print("━" * 28)

                markets = client.list_markets(sport_id=sport_id, max_results=args.limit)

                if not markets:
                    print("  No markets found for this sport")
                else:
                    for m in markets[:args.limit]:
                        event_name = m['event']['name'] if m['event'] else "Unknown"
                        market_name = m['market_name']
                        matched = m.get('total_matched', 0)
                        print(f"  • {event_name}")
                        print(f"    {market_name} (£{matched:,.0f} matched)")
            else:
                # Show all sports with market counts
                print("\n📡 **LIVE SPORTS**")
                print("━" * 28)
                sports = client.list_sports()
                for s in sorted(sports, key=lambda x: x['market_count'], reverse=True)[:10]:
                    print(f"  • {s['name']:<20} {s['market_count']:>6} markets")

            client.logout()

        except Exception as e:
            print(f"\n❌ Error fetching live markets: {e}")
            print("   Run with --demo to see sample markets")

    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")


def cmd_health(args):
    """System health check."""
    print("🏥 **BETFAIR HEALTH**")
    print("━" * 24)
    
    checks = []
    
    # Check database
    try:
        conn = init_db()
        balance = get_balance(conn)
        checks.append(("Database", True, f"£{balance:,.2f}"))
        conn.close()
    except Exception as e:
        checks.append(("Database", False, str(e)))
    
    # Check signal engine
    try:
        engine = SignalEngine()
        checks.append(("Signal Engine", True, "3 strategies"))
    except Exception as e:
        checks.append(("Signal Engine", False, str(e)))
    
    # Check paper trader
    try:
        from paper_trader import place_bet, settle_position
        checks.append(("Paper Trader", True, "OK"))
    except Exception as e:
        checks.append(("Paper Trader", False, str(e)))
    
    # Check Pickwatch data
    try:
        from pickwatch_adapter import get_todays_picks, PICKWATCH_DB
        if PICKWATCH_DB.exists():
            picks = get_todays_picks()
            checks.append(("Pickwatch Data", True, f"{len(picks)} picks today"))
        else:
            checks.append(("Pickwatch Data", False, "DB not found"))
    except Exception as e:
        checks.append(("Pickwatch Data", False, str(e)))
    cert_path = Path(__file__).parent / "config" / "betfair.crt"
    key_path = Path(__file__).parent / "config" / "betfair.key"
    if cert_path.exists() and key_path.exists():
        checks.append(("API Credentials", True, "configured"))
    else:
        checks.append(("API Credentials", False, "missing"))
    
    # Print results
    for name, ok, detail in checks:
        emoji = "🟢" if ok else "🔴"
        print(f"  {emoji} {name}: {detail}")
    
    healthy = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n✅ {healthy}/{total} systems healthy")
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")


def cmd_picks(args):
    """Show Pickwatch picks for today with signal analysis."""
    from pickwatch_adapter import (
        get_todays_picks, get_unresolved_picks,
        pickwatch_picks_to_market_data, compute_pickwatch_stats,
        american_to_decimal
    )
    
    print("🎯 **PICKWATCH PICKS**")
    print("━" * 28)
    
    picks = get_todays_picks()
    if not picks:
        print("\n📭 No picks for today")
        print("   Picks sync from Pickwatch dashboard")
    else:
        print(f"\n📋 Today: {len(picks)} picks\n")
        for p in picks:
            odds_str = f"{p['odds_american']:+d}" if p['odds_american'] else "PK"
            rec_emoji = "🔥" if p["recommendation"] == "STRONG BET" else "✅" if p["recommendation"] == "BET" else "📊"
            dec = p.get("odds_decimal", 2.0)
            print(f"  {rec_emoji} {p['sport']:4} {p['matchup']:25}")
            print(f"      {p['pick_team']:15} {odds_str:>6} ({dec:.2f})")
            print(f"      Edge: {p['edge']:.1f}%  Conf: {p['confidence_score']:.0f}%  Rating: {p.get('value_rating', '-')}")
        
        # Signal analysis
        markets = pickwatch_picks_to_market_data(picks)
        if markets:
            from signal_engine import SignalEngine
            engine = SignalEngine()
            signals = engine.generate_signals(markets)
            print(f"\n📡 Signal Analysis: {len(signals)} tradeable signals")
            for sig in signals:
                strength_emoji = {"WEAK": "⚪", "MODERATE": "🟡", "STRONG": "🟠", "ELITE": "🔴"}.get(sig.strength.name, "?")
                print(f"  {strength_emoji} {sig.selection_name} @ {sig.odds:.2f}")
                print(f"     Edge: {sig.edge_pct*100:.1f}% Conf: {sig.confidence*100:.0f}% {sig.reason}")
    
    # Stats
    stats = compute_pickwatch_stats()
    if stats:
        print(f"\n📊 Historical: {stats['wins']}W-{stats['losses']}L-{stats['pushes']}P ({stats['win_rate']}%)")
        for sport, s in stats["by_sport"].items():
            print(f"   {sport}: {s['wins']}W-{s['losses']}L ({s['win_rate']}%)")
    
    # Unresolved
    unresolved = get_unresolved_picks()
    if unresolved:
        print(f"\n⏳ Unresolved: {len(unresolved)} picks pending")
    
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")


def cmd_reset(args):
    """Reset portfolio."""
    if not args.confirm:
        print("⚠️  This will reset your portfolio to £1,000")
        print("   Run with --confirm to proceed")
        return
    
    conn = init_db()
    c = conn.cursor()
    
    # Reset balance
    c.execute("UPDATE portfolio SET balance = ?, updated_at = ?", 
              (INITIAL_BALANCE, datetime.utcnow().isoformat()))
    
    # Close all positions
    c.execute("UPDATE positions SET status = 'VOID', closed_at = ? WHERE status = 'OPEN'",
              (datetime.utcnow().isoformat(),))
    
    conn.commit()
    print("✅ Portfolio reset to £1,000")
    print(f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    conn.close()


def cmd_config(args):
    """Show or modify configuration."""
    cfg = Config()
    
    if args.set and len(args.set) >= 2:
        key = args.set[0]
        value = args.set[1]
        
        # Type conversion
        if value.replace(".", "").replace("-", "").isdigit():
            value = float(value) if "." in value else int(value)
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        
        cfg.set(key, value)
        print(f"✅ Set {key} = {value}")
        print(f"   Config saved to config.json")
    elif args.reset_config:
        cfg.reset()
        print("✅ Config reset to defaults")
    elif args.json:
        import json
        print(json.dumps(cfg.to_dict(), indent=2))
    else:
        print(format_config_display(cfg))
    
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")


def cmd_stats(args):
    """Show trading statistics."""
    conn = init_db()
    c = conn.cursor()
    
    # Get trade stats
    c.execute("""
        SELECT 
            COUNT(*) as total_trades,
            SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN profit_loss < 0 THEN 1 ELSE 0 END) as losses,
            SUM(profit_loss) as total_pnl,
            AVG(profit_loss) as avg_pnl,
            MAX(profit_loss) as best_trade,
            MIN(profit_loss) as worst_trade
        FROM trades
        WHERE action IN ('WIN', 'LOSE')
    """)
    stats = c.fetchone()
    
    print("📊 **TRADING STATISTICS**")
    print("━" * 28)
    
    total = stats[0] or 0
    wins = stats[1] or 0
    losses = stats[2] or 0
    total_pnl = stats[3] or 0
    avg_pnl = stats[4] or 0
    best = stats[5] or 0
    worst = stats[6] or 0
    
    win_rate = (wins / total * 100) if total > 0 else 0
    
    print(f"Total Trades:  {total}")
    print(f"Win Rate:      {win_rate:.1f}% ({wins}W/{losses}L)")
    print(f"Total P&L:     £{total_pnl:+,.2f}")
    print(f"Avg P&L:       £{avg_pnl:+,.2f}")
    print(f"Best Trade:    £{best:+,.2f}")
    print(f"Worst Trade:   £{worst:+,.2f}")
    
    print(f"\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Betfair Unified CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  status    Portfolio status
  run       Execute trading cycle (Pickwatch-driven)
  history   Trade history
  signals   Current signals
  markets   Available markets
  picks     Show Pickwatch picks for today
  stats     Trading statistics
  config    View/modify configuration
  health    System health check
  reset     Reset portfolio
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Status
    status_parser = subparsers.add_parser("status", help="Portfolio status")
    status_parser.set_defaults(func=cmd_status)
    
    # Run
    run_parser = subparsers.add_parser("run", help="Execute trading cycle")
    run_parser.set_defaults(func=cmd_run)
    
    # History
    history_parser = subparsers.add_parser("history", help="Trade history")
    history_parser.add_argument("--limit", type=int, default=10, help="Max trades to show")
    history_parser.set_defaults(func=cmd_history)
    
    # Signals
    signals_parser = subparsers.add_parser("signals", help="Current signals")
    signals_parser.set_defaults(func=cmd_signals)
    
    # Markets
    markets_parser = subparsers.add_parser("markets", help="Available markets")
    markets_parser.add_argument("--sport", type=int, help="Sport ID (e.g., 7524 for NHL, 7522 for NBA, 6423 for NFL)")
    markets_parser.add_argument("--demo", action="store_true", help="Force demo mode (show sample markets)")
    markets_parser.add_argument("--limit", type=int, default=10, help="Max markets to show (default: 10)")
    markets_parser.set_defaults(func=cmd_markets)
    
    # Config
    config_parser = subparsers.add_parser("config", help="View/modify configuration")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set config value")
    config_parser.add_argument("--reset", dest="reset_config", action="store_true", help="Reset to defaults")
    config_parser.add_argument("--json", action="store_true", help="Output as JSON")
    config_parser.set_defaults(func=cmd_config)
    
    # Stats
    stats_parser = subparsers.add_parser("stats", help="Trading statistics")
    stats_parser.set_defaults(func=cmd_stats)
    
    # Health
    health_parser = subparsers.add_parser("health", help="System health check")
    health_parser.set_defaults(func=cmd_health)
    
    # Picks
    picks_parser = subparsers.add_parser("picks", help="Show Pickwatch picks for today")
    picks_parser.set_defaults(func=cmd_picks)

    # Reset
    reset_parser = subparsers.add_parser("reset", help="Reset portfolio")
    reset_parser.add_argument("--confirm", action="store_true", help="Confirm reset")
    reset_parser.set_defaults(func=cmd_reset)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
