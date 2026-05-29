import unittest
from datetime import datetime, timedelta
from signal_engine import SignalEngine, SignalStrength, BetType

class TestSignalEngine(unittest.TestCase):
    def setUp(self):
        self.engine = SignalEngine()

    def test_value_betting(self):
        """Test that value betting identifies a bet when odds > fair odds."""
        market = {
            "marketId": "M1",
            "eventName": "Test Value Event",
            "runners": [
                {
                    "selectionId": 101,
                    "runnerName": "Team A",
                    "ex": {"availableToBack": [{"price": 2.20, "size": 100}]}
                }
            ],
            "fair_odds": {101: 2.00} # 10% edge
        }
        
        signals = self.engine.generate_signals([market])
        self.assertTrue(len(signals) > 0)
        self.assertEqual(signals[0].strategy, "value")
        self.assertEqual(signals[0].edge_pct, 0.10)
        self.assertEqual(signals[0].strength, SignalStrength.STRONG)

    def test_steam_move(self):
        """Test that steam move detects significant price drops."""
        now = datetime.utcnow()
        market = {
            "marketId": "M2",
            "eventName": "Test Steam Event",
            "runners": [
                {
                    "selectionId": 201,
                    "runnerName": "Team B",
                    "ex": {"availableToBack": [{"price": 1.80, "size": 100}]}
                }
            ],
            "odds_history": {
                201: [
                    {"price": 2.10, "timestamp": (now - timedelta(minutes=30)).isoformat()},
                    {"price": 1.80, "timestamp": now.isoformat()}
                ]
            }
        }
        
        signals = self.engine.generate_signals([market])
        self.assertTrue(len(signals) > 0)
        self.assertEqual(signals[0].strategy, "steam")
        # (2.10 - 1.80) / 2.10 = ~14% move
        self.assertGreater(signals[0].edge_pct, 0)

    def test_pickwatch_integration(self):
        """Test that Pickwatch data generates signals."""
        market = {
            "marketId": "M3",
            "eventName": "Test Pickwatch Event",
            "runners": [
                {
                    "selectionId": 301,
                    "runnerName": "Team C",
                    "ex": {"availableToBack": [{"price": 2.00, "size": 100}]}
                }
            ],
            "pickwatch_data": {
                "Team C": {"edge": 0.08, "expert_pct": 0.75}
            }
        }
        
        signals = self.engine.generate_signals([market])
        self.assertTrue(len(signals) > 0)
        self.assertEqual(signals[0].strategy, "pickwatch")
        self.assertEqual(signals[0].edge_pct, 0.08)
        self.assertEqual(signals[0].strength, SignalStrength.STRONG)

    def test_confidence_filtering(self):
        """Test that signals below MIN_CONFIDENCE are filtered out."""
        market = {
            "marketId": "M4",
            "eventName": "Low Confidence Event",
            "runners": [
                {
                    "selectionId": 401,
                    "runnerName": "Team D",
                    "ex": {"availableToBack": [{"price": 2.00, "size": 100}]}
                }
            ],
            "pickwatch_data": {
                "Team D": {"edge": 0.01, "expert_pct": 0.40} # Below MIN_CONFIDENCE (0.6)
            }
        }
        
        signals = self.engine.generate_signals([market])
        self.assertEqual(len(signals), 0)

    def test_signal_sorting(self):
        """Test that signals are sorted by edge percentage (highest first)."""
        market_low = {
            "marketId": "ML",
            "runners": [{"selectionId": 1, "runnerName": "A", "ex": {"availableToBack": [{"price": 2.0, "size": 1}]}}],
            "fair_odds": {1: 1.95} # ~2.5% edge
        }
        market_high = {
            "marketId": "MH",
            "runners": [{"selectionId": 2, "runnerName": "B", "ex": {"availableToBack": [{"price": 3.0, "size": 1}]}}],
            "fair_odds": {2: 2.00} # 50% edge
        }
        
        signals = self.engine.generate_signals([market_low, market_high])
        self.assertEqual(signals[0].market_id, "MH")
        self.assertEqual(signals[1].market_id, "ML")

if __name__ == "__main__":
    unittest.main()
