#!/usr/bin/env python3
"""
Pickwatch → Betfair Adapter

Reads Pickwatch picks from the local SQLite DB and converts them into
Betfair-compatible market/runner structures for the SignalEngine.

Key conversions:
- American odds → Decimal odds (Betfair format)
- ML (Moneyline) picks → BACK signals on match odds markets
- Edge % → SignalEngine confidence + edge_pct
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional


PICKWATCH_DB = Path("/app/pickwatch_history.db")

# Betfair sport IDs for sports that Pickwatch covers
BETFAIR_SPORT_MAP = {
    "NBA": 7522,
    "NHL": 7524,
    "MLB": 7523,   # Baseball (US)
    "NFL": 6423,
    "NCAAB": 7379,
    "NCAAF": 7380,
}


def american_to_decimal(odds: int) -> float:
    """
    Convert American odds to Decimal (European) odds.
    
    Positive American: decimal = (odds / 100) + 1
    Negative American: decimal = (100 / abs(odds)) + 1
    Zero or None: return 2.0 (even money)
    """
    if odds is None or odds == 0:
        return 2.0
    if odds > 0:
        return round((odds / 100) + 1, 2)
    else:
        return round((100 / abs(odds)) + 1, 2)


def decimal_to_american(decimal_odds: float) -> int:
    """Convert Decimal odds back to American odds."""
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1) * 100))
    else:
        return int(round(-100 / (decimal_odds - 1)))


def get_todays_picks(db_path: Optional[str] = None) -> list[dict]:
    """
    Fetch today's picks from Pickwatch DB.
    
    Returns list of pick dicts with:
    - sport, matchup, pick_team, pick_type, odds_american,
      edge, confidence_score, value_rating, recommendation
    Plus computed: odds_decimal
    """
    path = db_path or str(PICKWATCH_DB)
    
    if not Path(path).exists():
        print(f"⚠️  Pickwatch DB not found at {path}")
        return []
    
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    
    today = date.today().isoformat()
    c = conn.cursor()
    c.execute("""
        SELECT id, sport, matchup, pick_team, pick_type, 
               odds_american, edge, confidence_score, 
               value_rating, recommendation, outcome
        FROM picks 
        WHERE date = ? 
        ORDER BY edge DESC
    """, (today,))
    
    picks = []
    for row in c.fetchall():
        pick = dict(row)
        pick["odds_decimal"] = american_to_decimal(pick["odds_american"] or 0)
        picks.append(pick)
    
    conn.close()
    return picks


def get_unresolved_picks(db_path: Optional[str] = None) -> list[dict]:
    """
    Fetch picks where outcome is still None (pending resolution).
    These are active picks that haven't been settled yet.
    """
    path = db_path or str(PICKWATCH_DB)
    
    if not Path(path).exists():
        return []
    
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    
    c = conn.cursor()
    c.execute("""
        SELECT id, sport, matchup, pick_team, pick_type, 
               odds_american, edge, confidence_score, 
               value_rating, recommendation, outcome, date
        FROM picks 
        WHERE outcome IS NULL OR outcome = ''
        ORDER BY date DESC, edge DESC
    """)
    
    picks = []
    for row in c.fetchall():
        pick = dict(row)
        pick["odds_decimal"] = american_to_decimal(pick["odds_american"] or 0)
        picks.append(pick)
    
    conn.close()
    return picks


def get_historical_picks(
    sport: Optional[str] = None,
    limit: int = 100,
    min_edge: float = 0,
    db_path: Optional[str] = None
) -> list[dict]:
    """Fetch resolved picks with outcomes for analysis."""
    path = db_path or str(PICKWATCH_DB)
    
    if not Path(path).exists():
        return []
    
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    
    query = """
        SELECT * FROM picks 
        WHERE outcome IS NOT NULL AND outcome != ''
    """
    params = []
    
    if sport:
        query += " AND sport = ?"
        params.append(sport)
    
    if min_edge > 0:
        query += " AND edge >= ?"
        params.append(min_edge)
    
    query += " ORDER BY date DESC LIMIT ?"
    params.append(limit)
    
    c = conn.cursor()
    c.execute(query, params)
    
    picks = []
    for row in c.fetchall():
        pick = dict(row)
        pick["odds_decimal"] = american_to_decimal(pick.get("odds_american") or 0)
        picks.append(pick)
    
    conn.close()
    return picks


def pickwatch_picks_to_market_data(picks: list[dict]) -> list[dict]:
    """
    Convert Pickwatch picks into Betfair market/runner format
    that SignalEngine can process via _pickwatch_edge strategy.
    
    Each pick becomes a "market" with:
    - marketId: synthetic (PW-{id})
    - eventName: the matchup
    - runners: the picked team with odds
    - pickwatch_data: edge info for signal generation
    """
    markets = []
    
    for pick in picks:
        sport = pick.get("sport", "unknown")
        matchup = pick.get("matchup", "Unknown")
        pick_team = pick.get("pick_team", "Unknown")
        odds_dec = pick.get("odds_decimal", 2.0)
        edge = (pick.get("edge") or 0) / 100.0  # Convert % to fraction
        confidence = (pick.get("confidence_score") or 50) / 100.0  # Convert to 0-1
        recommendation = pick.get("recommendation", "LEAN")
        betfair_sport_id = BETFAIR_SPORT_MAP.get(sport)
        
        # Only include if recommendation is BET or STRONG BET
        if recommendation not in ("BET", "STRONG BET"):
            continue
        
        # Minimum confidence filter
        if confidence < 0.6:
            continue
        
        selection_id = hash(pick_team) % 100000  # Stable synthetic ID
        
        market = {
            "marketId": f"PW-{pick.get('id', hash(matchup))}",
            "eventName": f"{sport}: {matchup}",
            "sport": sport,
            "betfair_sport_id": betfair_sport_id,
            "runners": [
                {
                    "selectionId": selection_id,
                    "runnerName": pick_team,
                    "ex": {
                        "availableToBack": [{"price": odds_dec, "size": 100}],
                        "availableToLay": [{"price": round(odds_dec + 0.02, 2), "size": 100}],
                    }
                }
            ],
            "pickwatch_data": {
                pick_team: {
                    "edge": edge,
                    "expert_pct": confidence,
                    "recommendation": recommendation,
                    "pick_type": pick.get("pick_type", "ML"),
                    "odds_american": pick.get("odds_american", 0),
                    "value_rating": pick.get("value_rating", 3),
                },
                selection_id: {
                    "edge": edge,
                    "expert_pct": confidence,
                    "recommendation": recommendation,
                }
            }
        }
        markets.append(market)
    
    return markets


def compute_pickwatch_stats(db_path: Optional[str] = None) -> dict:
    """Compute win rate and ROI statistics from Pickwatch historical data."""
    path = db_path or str(PICKWATCH_DB)
    
    if not Path(path).exists():
        return {}
    
    conn = sqlite3.connect(path)
    c = conn.cursor()
    
    # Overall stats
    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN outcome = 'PUSH' THEN 1 ELSE 0 END) as pushes
        FROM picks 
        WHERE outcome IS NOT NULL AND outcome != ''
    """)
    total, wins, losses, pushes = c.fetchone()
    
    # Per-sport stats
    c.execute("""
        SELECT 
            sport,
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses
        FROM picks 
        WHERE outcome IS NOT NULL AND outcome != ''
        GROUP BY sport
    """)
    sport_stats = {}
    for row in c.fetchall():
        sport, s_total, s_wins, s_losses = row
        wr = (s_wins / s_total * 100) if s_total > 0 else 0
        sport_stats[sport] = {
            "total": s_total,
            "wins": s_wins,
            "losses": s_losses,
            "win_rate": round(wr, 1),
        }
    
    # By edge bracket
    c.execute("""
        SELECT 
            CASE 
                WHEN edge >= 35 THEN '35+'
                WHEN edge >= 30 THEN '30-35'
                WHEN edge >= 25 THEN '25-30'
                WHEN edge >= 20 THEN '20-25'
                ELSE '<20'
            END as edge_bracket,
            COUNT(*) as total,
            SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) as losses
        FROM picks 
        WHERE outcome IS NOT NULL AND outcome != ''
        GROUP BY edge_bracket
        ORDER BY edge_bracket DESC
    """)
    edge_stats = {}
    for row in c.fetchall():
        bracket, e_total, e_wins, e_losses = row
        wr = (e_wins / e_total * 100) if e_total > 0 else 0
        edge_stats[bracket] = {
            "total": e_total,
            "wins": e_wins,
            "losses": e_losses,
            "win_rate": round(wr, 1),
        }
    
    conn.close()
    
    wr = (wins / total * 100) if total > 0 else 0
    
    return {
        "total": total,
        "wins": wins or 0,
        "losses": losses or 0,
        "pushes": pushes or 0,
        "win_rate": round(wr, 1),
        "by_sport": sport_stats,
        "by_edge": edge_stats,
    }


if __name__ == "__main__":
    print("🎯 **PICKWATCH ADAPTER**")
    print("━" * 28)
    
    # Today's picks
    picks = get_todays_picks()
    print(f"\n📋 Today's Picks: {len(picks)}")
    for p in picks:
        odds_str = f"{p['odds_american']:+d}" if p['odds_american'] else "PK"
        rec_emoji = "🔥" if p["recommendation"] == "STRONG BET" else "✅" if p["recommendation"] == "BET" else "📊"
        print(f"  {rec_emoji} {p['sport']:4} {p['matchup']:25} {p['pick_team']:15} {odds_str:>6}  Edge: {p['edge']:.1f}%  Conf: {p['confidence_score']:.0f}%")
    
    # Unresolved picks
    unresolved = get_unresolved_picks()
    print(f"\n⏳ Unresolved Picks: {len(unresolved)}")
    
    # Stats
    stats = compute_pickwatch_stats()
    if stats:
        print(f"\n📊 Historical Stats:")
        print(f"  Overall: {stats['wins']}W-{stats['losses']}L-{stats['pushes']}P ({stats['win_rate']}%)")
        for sport, s in stats["by_sport"].items():
            print(f"  {sport}: {s['wins']}W-{s['losses']}L ({s['win_rate']}%)")
        
        print(f"\n📈 By Edge Bracket:")
        for bracket, e in stats["by_edge"].items():
            print(f"  Edge {bracket:>5}: {e['wins']}W-{e['losses']}L ({e['win_rate']}%)")
    
    # Market data conversion demo
    if picks:
        markets = pickwatch_picks_to_market_data(picks)
        print(f"\n🔄 Convertible Markets: {len(markets)}")
        for m in markets[:3]:
            print(f"  {m['eventName']} → {m['marketId']}")