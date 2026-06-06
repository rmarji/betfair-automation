#!/usr/bin/env python3
"""
Pickwatch → Betfair Adapter

Fetches Pickwatch picks via HTTP API (primary) or local SQLite DB (fallback)
and converts them into Betfair-compatible market/runner structures for the SignalEngine.

Key conversions:
- American odds → Decimal odds (Betfair format)
- ML (Moneyline) picks → BACK signals on match odds markets
- Edge % → SignalEngine confidence + edge_pct

Data sources (in priority order):
1. Pickwatch API via n8n proxy (real-time, no local file needed)
2. Local SQLite DB (fallback for offline/historical use)
"""

import json
import os
import sqlite3
import ssl
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import quote


PICKWATCH_DB = Path("/app/pickwatch_history.db")

# HTTP API configuration
PICKWATCH_PROXY_URL = os.getenv(
    "PICKWATCH_PROXY_URL",
    "https://n8n.claw.jogeeks.com/webhook/pickwatch-proxy"
)
PICKWATCH_TOKEN = os.getenv("PICKWATCH_TOKEN", "")

# Sport → Pickwatch API sport name mapping
# Betfair sport IDs → Pickwatch sport keys
BETFAIR_SPORT_MAP = {
    "NBA": 7522,
    "NHL": 7524,
    "MLB": 7523,   # Baseball (US)
    "NFL": 6423,
    "NCAAB": 7379,
    "NCAAF": 7380,
}

# Pickwatch sport key → Pickwatch origin domain
PICKWATCH_SPORT_URLS = {
    "NBA": "https://nbapickwatch.com",
    "NHL": "https://nhlpickwatch.com",
    "MLB": "https://mlbpickwatch.com",
    "NFL": "https://nflpickwatch.com",
}

# Which sports to fetch via API (match tracked_sports)
API_TRACKED_SPORTS = os.getenv(
    "PICKWATCH_SPORTS",
    "NBA,NHL,MLB,NFL"
).split(",")

# ── HTTP API Functions ────────────────────────────────────────────────

def _api_get(path: str, origin: str = "https://nflpickwatch.com") -> list | dict:
    """Fetch data from Pickwatch API via n8n proxy."""
    from urllib.parse import quote as url_quote
    url = f"{PICKWATCH_PROXY_URL}?path={url_quote(path, safe='')}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (BetfairAutomation/1.0)",
    }
    req = Request(url, headers=headers)
    ssl_ctx = ssl.create_default_context()
    try:
        with urlopen(req, context=ssl_ctx, timeout=30) as resp:
            data = resp.read().decode()
            if not data:
                return []
            return json.loads(data)
    except HTTPError as e:
        if e.code in (404, 500):
            return []
        print(f"⚠️  Pickwatch API error: {e.code} {e.reason}")
        return []
    except (URLError, TimeoutError) as e:
        print(f"⚠️  Pickwatch API connection error: {e}")
        return []
    except json.JSONDecodeError:
        return []


def _score_pick_from_api(game: dict, cpu_picks: dict, sport: str) -> Optional[dict]:
    """
    Convert a raw Pickwatch API game dict into a scored pick dict.
    
    Applies the same scoring logic as the pickwatch-dashboard's ConfidenceScorer,
    producing a pick compatible with get_todays_picks() output format.
    """
    game_id = game.get("id", 0)
    home_team = game.get("home_team_id", "")
    away_team = game.get("road_team_id", "")
    home_odds = game.get("home_team_odds_ame") or 0
    away_odds = game.get("road_team_odds_ame") or 0
    game_state = game.get("game_state", "Scheduled")
    
    # Skip finished games
    if game_state in ("Final", "F/OT", "F"):
        return None
    
    # Expert consensus
    expert_home = game.get("ht_pct_su_experts") or 0
    expert_away = game.get("rt_pct_su_experts") or 0
    expert_picks_count = game.get("picks_su_experts") or 0
    
    # Fan consensus
    fan_home = game.get("ht_pct_su_fans") or 0
    fan_away = game.get("rt_pct_su_fans") or 0
    
    # CPU premium picks
    cpu_data = cpu_picks.get(game_id, {})
    cpu_pick_team = cpu_data.get("team", "")
    cpu_confidence = cpu_data.get("confidence", 0)
    
    # Determine which side to pick (the one with more expert support)
    picks = []
    for side, team, odds, expert_pct, fan_pct in [
        ("home", home_team, home_odds, expert_home, fan_home),
        ("away", away_team, away_odds, expert_away, fan_away),
    ]:
        if not team or expert_pct < 50:
            continue  # Skip side with minority expert support
        
        # Calculate edge and confidence
        cpu_conf = cpu_confidence if cpu_pick_team == team else (1 - cpu_confidence) if cpu_confidence else 0
        
        # Edge calculation: expert_pct as proxy for true probability
        # If experts say 70% and odds imply 55%, edge = 15%
        implied_prob = _american_to_implied_prob(odds)
        edge = round(expert_pct - (implied_prob * 100), 1)
        
        # Confidence score: weighted blend of expert %, fan %, CPU
        confidence = _compute_confidence(expert_pct, fan_pct, cpu_conf, expert_picks_count)
        
        # Value rating (1-5 stars)
        value_rating = min(5, max(1, int(edge / 10) + 1))
        
        # Recommendation
        if edge >= 30 and confidence >= 70:
            recommendation = "STRONG BET"
        elif edge >= 15 and confidence >= 50:
            recommendation = "BET"
        elif edge >= 5 and confidence >= 40:
            recommendation = "LEAN"
        else:
            recommendation = "PASS"
        
        pick = {
            "id": f"{sport}-{game_id}-{side}",
            "sport": sport,
            "date": str(date.today()),
            "matchup": f"{away_team} @ {home_team}",
            "pick_team": team,
            "pick_type": "ML",
            "odds_american": odds,
            "odds_decimal": american_to_decimal(odds),
            "edge": edge,
            "confidence_score": round(confidence, 1),
            "value_rating": value_rating,
            "recommendation": recommendation,
            "outcome": None,  # Unresolved
            "source": "api",
        }
        picks.append(pick)
    
    # Return only the strongest pick per game
    if len(picks) > 1:
        picks.sort(key=lambda p: (p["edge"], p["confidence_score"]), reverse=True)
    return picks[0] if picks else None


def _american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability (0-1)."""
    if odds is None or odds == 0:
        return 0.5
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def _compute_confidence(expert_pct: float, fan_pct: float, cpu_conf: float, expert_count: int) -> float:
    """Compute blended confidence score from expert, fan, and CPU data."""
    weights = []
    scores = []
    
    if expert_pct > 0:
        weights.append(0.5)
        scores.append(expert_pct)
    if fan_pct > 0:
        weights.append(0.2)
        scores.append(fan_pct)
    if cpu_conf > 0:
        weights.append(0.3)
        scores.append(cpu_conf * 100)
    
    if not weights:
        return 0.0
    
    # Weighted average
    total_weight = sum(weights)
    confidence = sum(w * s for w, s in zip(weights, scores)) / total_weight
    
    # Bonus for more expert picks (more data = more confidence)
    if expert_count >= 10:
        confidence = min(100, confidence + 5)
    
    return confidence


def fetch_picks_via_api(sport: str = None, day: str = None) -> list[dict]:
    """
    Fetch today's picks directly from Pickwatch API via n8n proxy.
    
    This is the PRIMARY data source — no local SQLite dependency needed.
    Returns picks in the same format as get_todays_picks() for seamless integration.
    """
    if day is None:
        day = date.today().isoformat()
    
    # Determine year from date string
    year = day[:4]
    
    sports = [sport] if sport else API_TRACKED_SPORTS
    all_picks = []
    
    for s in sports:
        origin = PICKWATCH_SPORT_URLS.get(s, "https://nflpickwatch.com")
        sport_lower = s.lower()
        
        # Determine season year (NBA/NHL span calendar years)
        season_year = year
        if s in ("NBA", "NHL"):
            # NBA 2025-26 season → 2025
            pass
        
        # Path format: /general/games/{year}/{day}/{sport}/REGULAR
        games_path = f"/general/games/{season_year}/{day}/{sport_lower}/REGULAR"
        games_data = _api_get(games_path, origin)
        
        if not games_data:
            print(f"📭 No {s} games data for {day}")
            continue
        
        # Fetch CPU premium picks
        cpu_path = f"/general/marketplace/premium-picks/{sport_lower}/{season_year}/{day}/su/"
        cpu_data = _api_get(cpu_path, origin)
        
        # Parse CPU picks into game_id → {team, confidence} format
        cpu_picks = {}
        if isinstance(cpu_data, dict) and cpu_data.get("experts"):
            for expert in cpu_data["experts"]:
                for game_id_str, pick in expert.get("picks", {}).items():
                    if pick.get("team_id"):
                        cpu_picks[int(game_id_str)] = {
                            "team": pick["team_id"],
                            "confidence": pick.get("confidence", 0),
                        }
        
        # Convert games to picks
        for game in games_data:
            if game.get("game_state") in ("Final", "F/OT", "F"):
                continue
            
            pick = _score_pick_from_api(game, cpu_picks, s)
            if pick:
                all_picks.append(pick)
        
        print(f"✅ Fetched {len(all_picks)} {s} picks via API")
    
    return all_picks


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


def get_todays_picks(db_path: Optional[str] = None, use_api: bool = True) -> list[dict]:
    """
    Fetch today's picks. Tries HTTP API first (real-time data),
    falls back to local SQLite DB if API is unavailable.
    
    Args:
        db_path: Path to local SQLite DB (fallback)
        use_api: If True, try Pickwatch API first. Set False for tests/offline.
    
    Returns list of pick dicts with:
    - sport, matchup, pick_team, pick_type, odds_american,
      edge, confidence_score, value_rating, recommendation
    Plus computed: odds_decimal
    """
    # Try API first (no local file dependency)
    if use_api:
        try:
            api_picks = fetch_picks_via_api()
            if api_picks:
                print(f"📡 Using Pickwatch API ({len(api_picks)} picks)")
                return api_picks
            print("📡 API returned no picks, trying local DB...")
        except Exception as e:
            print(f"📡 API fetch failed: {e}, falling back to local DB...")
    
    # Fallback to local SQLite
    path = db_path or str(PICKWATCH_DB)
    
    if not Path(path).exists():
        print(f"⚠️  Pickwatch DB not found at {path} and API unavailable")
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


def get_unresolved_picks(db_path: Optional[str] = None, use_api: bool = True) -> list[dict]:
    """
    Fetch picks where outcome is still None (pending resolution).
    Tries API first, falls back to local DB.
    
    Args:
        db_path: Path to local SQLite DB (fallback)
        use_api: If True, try Pickwatch API first. Set False for tests/offline.
    """
    # API picks are always unresolved (live data)
    if use_api:
        try:
            api_picks = fetch_picks_via_api()
            if api_picks:
                return [p for p in api_picks if p.get("outcome") is None]
        except Exception:
            pass
    
    # Fallback to local DB
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
    """
    Fetch resolved picks with outcomes for analysis.
    Historical data only available from local DB (API provides live data only).
    """
    path = db_path or str(PICKWATCH_DB)
    
    if not Path(path).exists():
        print(f"⚠️  Historical data requires local Pickwatch DB (not available)")
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


def pickwatch_picks_to_market_data(picks: list[dict], sport_config: dict = None) -> list[dict]:
    """
    Convert Pickwatch picks into Betfair market/runner format
    that SignalEngine can process via _pickwatch_edge strategy.
    
    Each pick becomes a "market" with:
    - marketId: synthetic (PW-{id})
    - eventName: the matchup
    - runners: the picked team with odds
    - pickwatch_data: edge info for signal generation
    
    Args:
        picks: List of Pickwatch pick dicts
        sport_config: Optional dict of {sport: {min_edge, min_confidence, enabled}}
                      When provided, filters picks by sport-specific thresholds.
    """
    # Build per-sport threshold lookup
    global_min_edge = 30.0  # Conservative default per backtesting
    global_min_confidence = 0.6
    
    markets = []
    
    for pick in picks:
        sport = pick.get("sport", "unknown")
        matchup = pick.get("matchup", "Unknown")
        pick_team = pick.get("pick_team", "Unknown")
        odds_dec = pick.get("odds_decimal", 2.0)
        edge = (pick.get("edge") or 0) / 100.0  # Convert % to fraction
        edge_pct = pick.get("edge") or 0  # Raw percentage for threshold check
        confidence = (pick.get("confidence_score") or 50) / 100.0  # Convert to 0-1
        recommendation = pick.get("recommendation", "LEAN")
        betfair_sport_id = BETFAIR_SPORT_MAP.get(sport)
        
        # Only include if recommendation is BET or STRONG BET
        if recommendation not in ("BET", "STRONG BET"):
            continue
        
        # Apply sport-specific thresholds if available
        if sport_config:
            sport_cfg = sport_config.get(sport, {})
            if not sport_cfg.get("enabled", True):
                continue  # Skip disabled sports
            min_edge = sport_cfg.get("min_edge", global_min_edge)
            min_conf = sport_cfg.get("min_confidence", global_min_confidence)
        else:
            min_edge = global_min_edge
            min_conf = global_min_confidence
        
        # Minimum edge and confidence filters (sport-aware)
        if edge_pct < min_edge:
            continue
        if confidence < min_conf:
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