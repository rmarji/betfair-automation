"""Tests for pickwatch_adapter module."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta

from pickwatch_adapter import (
    american_to_decimal,
    decimal_to_american,
    get_todays_picks,
    get_unresolved_picks,
    get_historical_picks,
    pickwatch_picks_to_market_data,
    compute_pickwatch_stats,
)


def _create_test_db(path: str, picks: list[dict]):
    """Create a test DB with the given pick rows."""
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            sport TEXT,
            matchup TEXT,
            pick_team TEXT,
            pick_type TEXT,
            odds_american INTEGER,
            edge REAL,
            confidence_score REAL,
            value_rating REAL,
            recommendation TEXT,
            outcome TEXT
        )
    """)
    for p in picks:
        c.execute(
            "INSERT INTO picks (date, sport, matchup, pick_team, pick_type, odds_american, edge, confidence_score, value_rating, recommendation, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.get("date", date.today().isoformat()),
                p.get("sport", "MLB"),
                p.get("matchup", "Team A vs Team B"),
                p.get("pick_team", "Team A"),
                p.get("pick_type", "ML"),
                p.get("odds_american", -110),
                p.get("edge", 25.0),
                p.get("confidence_score", 70.0),
                p.get("value_rating", 3.0),
                p.get("recommendation", "BET"),
                p.get("outcome"),
            ),
        )
    conn.commit()
    conn.close()


class TestAmericanToDecimal(unittest.TestCase):
    """Test American-to-Decimal odds conversion."""

    def test_positive_odds(self):
        # +150 → (150/100) + 1 = 2.50
        self.assertAlmostEqual(american_to_decimal(150), 2.50)

    def test_negative_odds(self):
        # -110 → (100/110) + 1 = 1.91
        self.assertAlmostEqual(american_to_decimal(-110), 1.91)

    def test_even_money(self):
        # +100 → 2.0
        self.assertAlmostEqual(american_to_decimal(100), 2.0)

    def test_none_returns_even(self):
        self.assertEqual(american_to_decimal(None), 2.0)

    def test_zero_returns_even(self):
        self.assertEqual(american_to_decimal(0), 2.0)

    def test_large_positive(self):
        # +500 → 6.0
        self.assertAlmostEqual(american_to_decimal(500), 6.0)

    def test_large_negative(self):
        # -300 → (100/300)+1 ≈ 1.33
        self.assertAlmostEqual(american_to_decimal(-300), 1.33)


class TestDecimalToAmerican(unittest.TestCase):
    """Test Decimal-to-American odds conversion."""

    def test_decimal_above_2(self):
        # 2.50 → +150
        self.assertEqual(decimal_to_american(2.50), 150)

    def test_decimal_below_2(self):
        # 1.91 → -110
        self.assertEqual(decimal_to_american(1.91), -110)

    def test_exact_2(self):
        # 2.0 → +100
        self.assertEqual(decimal_to_american(2.0), 100)


class TestGetTodaysPicks(unittest.TestCase):
    """Test fetching today's picks from DB."""

    def test_todays_picks_returns_today_only(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            today = date.today().isoformat()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            picks = [
                {"date": today, "sport": "MLB", "matchup": "Yankees vs Red Sox", "pick_team": "Yankees", "edge": 28.0, "confidence_score": 75.0, "recommendation": "BET"},
                {"date": yesterday, "sport": "NBA", "matchup": "Lakers vs Warriors", "pick_team": "Lakers", "edge": 22.0, "confidence_score": 65.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            result = get_todays_picks(db_path=db_path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["sport"], "MLB")
        finally:
            os.unlink(db_path)

    def test_empty_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("CREATE TABLE picks (id INTEGER PRIMARY KEY, date TEXT, sport TEXT, matchup TEXT, pick_team TEXT, pick_type TEXT, odds_american INTEGER, edge REAL, confidence_score REAL, value_rating REAL, recommendation TEXT, outcome TEXT)")
            conn.commit()
            conn.close()

            result = get_todays_picks(db_path=db_path)
            self.assertEqual(len(result), 0)
        finally:
            os.unlink(db_path)

    def test_nonexistent_db(self):
        result = get_todays_picks(db_path="/tmp/nonexistent_12345.db")
        self.assertEqual(result, [])

    def test_odds_decimal_conversion_in_picks(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"odds_american": -110, "edge": 25.0, "confidence_score": 70.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            result = get_todays_picks(db_path=db_path)
            self.assertEqual(len(result), 1)
            self.assertAlmostEqual(result[0]["odds_decimal"], 1.91)
        finally:
            os.unlink(db_path)


class TestGetUnresolvedPicks(unittest.TestCase):
    """Test fetching unresolved (pending) picks."""

    def test_unresolved_returns_null_outcome(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": None, "edge": 30.0, "confidence_score": 80.0, "recommendation": "STRONG BET"},
                {"sport": "NBA", "outcome": "WIN", "edge": 25.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "NHL", "outcome": "", "edge": 22.0, "confidence_score": 65.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            result = get_unresolved_picks(db_path=db_path)
            # Should return picks with None or empty outcome
            self.assertGreaterEqual(len(result), 2)
            for p in result:
                self.assertTrue(p["outcome"] is None or p["outcome"] == "")
        finally:
            os.unlink(db_path)


class TestGetHistoricalPicks(unittest.TestCase):
    """Test fetching resolved picks with outcomes."""

    def test_historical_returns_resolved_only(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": "WIN", "edge": 25.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "LOSS", "edge": 20.0, "confidence_score": 65.0, "recommendation": "BET"},
                {"sport": "MLB", "outcome": None, "edge": 30.0, "confidence_score": 80.0, "recommendation": "STRONG BET"},
            ]
            _create_test_db(db_path, picks)

            result = get_historical_picks(db_path=db_path)
            self.assertEqual(len(result), 2)
            for p in result:
                self.assertIn(p["outcome"], ("WIN", "LOSS"))
        finally:
            os.unlink(db_path)

    def test_filter_by_sport(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": "WIN", "edge": 25.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "LOSS", "edge": 20.0, "confidence_score": 65.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            mlb = get_historical_picks(sport="MLB", db_path=db_path)
            self.assertEqual(len(mlb), 1)
            self.assertEqual(mlb[0]["sport"], "MLB")
        finally:
            os.unlink(db_path)

    def test_filter_by_min_edge(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": "WIN", "edge": 15.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "LOSS", "edge": 35.0, "confidence_score": 65.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            high_edge = get_historical_picks(min_edge=25.0, db_path=db_path)
            self.assertEqual(len(high_edge), 1)
            self.assertGreaterEqual(high_edge[0]["edge"], 25.0)
        finally:
            os.unlink(db_path)


class TestPickwatchPicksToMarketData(unittest.TestCase):
    """Test converting Pickwatch picks to Betfair market format."""

    def test_bet_picks_included(self):
        picks = [
            {
                "id": 1, "sport": "MLB", "matchup": "Yankees vs Red Sox",
                "pick_team": "Yankees", "pick_type": "ML",
                "odds_american": -110, "edge": 30.0,
                "confidence_score": 75.0, "value_rating": 4.0,
                "recommendation": "BET", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        self.assertEqual(len(markets), 1)
        self.assertIn("PW-", markets[0]["marketId"])

    def test_strong_bet_included(self):
        picks = [
            {
                "id": 2, "sport": "MLB", "matchup": "Dodgers vs Giants",
                "pick_team": "Dodgers", "pick_type": "ML",
                "odds_american": 150, "edge": 35.0,
                "confidence_score": 85.0, "value_rating": 5.0,
                "recommendation": "STRONG BET", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        self.assertEqual(len(markets), 1)

    def test_lean_picks_filtered_out(self):
        picks = [
            {
                "id": 3, "sport": "NBA", "matchup": "Lakers vs Warriors",
                "pick_team": "Lakers", "pick_type": "ML",
                "odds_american": -110, "edge": 15.0,
                "confidence_score": 55.0, "value_rating": 2.0,
                "recommendation": "LEAN", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        self.assertEqual(len(markets), 0)

    def test_low_confidence_filtered_out(self):
        picks = [
            {
                "id": 4, "sport": "MLB", "matchup": "Leafs vs Bruins",
                "pick_team": "Leafs", "pick_type": "ML",
                "odds_american": -110, "edge": 35.0,
                "confidence_score": 50.0, "value_rating": 2.0,
                "recommendation": "BET", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        self.assertEqual(len(markets), 0)  # Below 60% confidence threshold

    def test_low_edge_filtered_out(self):
        """Picks below min_edge threshold are filtered out."""
        picks = [
            {
                "id": 7, "sport": "MLB", "matchup": "Angels vs A's",
                "pick_team": "Angels", "pick_type": "ML",
                "odds_american": -110, "edge": 15.0,
                "confidence_score": 70.0, "value_rating": 2.0,
                "recommendation": "BET", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        self.assertEqual(len(markets), 0)  # Below 30% edge threshold

    def test_sport_config_disabled_sport(self):
        """Picks from disabled sports are filtered out."""
        picks = [
            {
                "id": 8, "sport": "NBA", "matchup": "Lakers vs Warriors",
                "pick_team": "Lakers", "pick_type": "ML",
                "odds_american": -110, "edge": 35.0,
                "confidence_score": 70.0, "value_rating": 3.0,
                "recommendation": "BET", "outcome": None,
            }
        ]
        # NBA is disabled in default sport_thresholds
        markets = pickwatch_picks_to_market_data(picks, sport_config={
            "NBA": {"min_edge": 30.0, "min_confidence": 0.65, "enabled": False}
        })
        self.assertEqual(len(markets), 0)  # NBA is disabled

    def test_market_has_correct_structure(self):
        picks = [
            {
                "id": 5, "sport": "MLB", "matchup": "Cubs vs Cards",
                "pick_team": "Cubs", "pick_type": "ML",
                "odds_american": -150, "edge": 30.0,
                "confidence_score": 70.0, "value_rating": 3.0,
                "recommendation": "BET", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        m = markets[0]
        self.assertIn("marketId", m)
        self.assertIn("eventName", m)
        self.assertIn("runners", m)
        self.assertIn("pickwatch_data", m)
        self.assertIn("sport", m)
        self.assertIn("betfair_sport_id", m)
        self.assertEqual(m["sport"], "MLB")
        self.assertEqual(m["betfair_sport_id"], 7523)  # Baseball

    def test_runner_has_back_and_lay_odds(self):
        picks = [
            {
                "id": 6, "sport": "MLB", "matchup": "Heat vs Celtics",
                "pick_team": "Heat", "pick_type": "ML",
                "odds_american": 120, "odds_decimal": 2.20,
                "edge": 30.0, "confidence_score": 72.0, "value_rating": 3.5,
                "recommendation": "BET", "outcome": None,
            }
        ]
        markets = pickwatch_picks_to_market_data(picks)
        runner = markets[0]["runners"][0]
        self.assertIn("availableToBack", runner["ex"])
        self.assertIn("availableToLay", runner["ex"])
        # Decimal odds for +120 → 2.20; odds_decimal must be in the dict
        self.assertAlmostEqual(runner["ex"]["availableToBack"][0]["price"], 2.20)

    def test_sport_id_mapping(self):
        """Verify all covered sports map to correct Betfair IDs."""
        test_cases = [
            ("NBA", 7522),
            ("NHL", 7524),
            ("MLB", 7523),
            ("NFL", 6423),
        ]
        from pickwatch_adapter import BETFAIR_SPORT_MAP
        for sport, expected_id in test_cases:
            self.assertEqual(BETFAIR_SPORT_MAP.get(sport), expected_id)


class TestComputePickwatchStats(unittest.TestCase):
    """Test historical statistics computation."""

    def test_overall_stats(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": "WIN", "edge": 25.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "MLB", "outcome": "LOSS", "edge": 20.0, "confidence_score": 65.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "WIN", "edge": 30.0, "confidence_score": 75.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "LOSS", "edge": 15.0, "confidence_score": 60.0, "recommendation": "LEAN"},
                {"sport": "NHL", "outcome": "PUSH", "edge": 22.0, "confidence_score": 68.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            stats = compute_pickwatch_stats(db_path=db_path)
            self.assertEqual(stats["total"], 5)
            self.assertEqual(stats["wins"], 2)
            self.assertEqual(stats["losses"], 2)
            self.assertEqual(stats["pushes"], 1)
            # 2 wins out of 5 total = 40% (WIN/(WIN+LOSS+PUSH))
            self.assertAlmostEqual(stats["win_rate"], 40.0)
        finally:
            os.unlink(db_path)

    def test_per_sport_stats(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": "WIN", "edge": 25.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "MLB", "outcome": "WIN", "edge": 30.0, "confidence_score": 75.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "LOSS", "edge": 20.0, "confidence_score": 65.0, "recommendation": "BET"},
            ]
            _create_test_db(db_path, picks)

            stats = compute_pickwatch_stats(db_path=db_path)
            self.assertIn("MLB", stats["by_sport"])
            self.assertIn("NBA", stats["by_sport"])
            self.assertEqual(stats["by_sport"]["MLB"]["win_rate"], 100.0)
            self.assertEqual(stats["by_sport"]["NBA"]["win_rate"], 0.0)
        finally:
            os.unlink(db_path)

    def test_edge_bracket_stats(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            picks = [
                {"sport": "MLB", "outcome": "WIN", "edge": 27.0, "confidence_score": 70.0, "recommendation": "BET"},
                {"sport": "MLB", "outcome": "LOSS", "edge": 22.0, "confidence_score": 65.0, "recommendation": "BET"},
                {"sport": "NBA", "outcome": "WIN", "edge": 38.0, "confidence_score": 80.0, "recommendation": "STRONG BET"},
            ]
            _create_test_db(db_path, picks)

            stats = compute_pickwatch_stats(db_path=db_path)
            self.assertIn("by_edge", stats)
            # Edge 25-30 should contain the 27% pick
            self.assertIn("25-30", stats["by_edge"])
        finally:
            os.unlink(db_path)

    def test_nonexistent_db_returns_empty(self):
        stats = compute_pickwatch_stats(db_path="/tmp/nonexistent_99999.db")
        self.assertEqual(stats, {})


if __name__ == "__main__":
    unittest.main()