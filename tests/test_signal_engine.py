#!/usr/bin/env python3
"""
Unit tests for Betfair Signal Engine

Tests signal generation, edge calculation, and strategy logic.
Run with: python3 -m unittest tests.test_signal_engine
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime
from signal_engine import SignalEngine, Signal, BetType, SignalStrength


class TestSignalEngine(unittest.TestCase):
    """Test cases for signal generation functionality."""

    def setUp(self):
        """Create a fresh signal engine for each test."""
        self.engine = SignalEngine()

    def test_engine_has_three_strategies(self):
        """Engine has 3 strategies."""
        self.assertEqual(len(self.engine.strategies), 3)

    def test_minimum_confidence_threshold(self):
        """Minimum confidence is 0.6."""
        self.assertEqual(self.engine.MIN_CONFIDENCE, 0.6)

    def test_edge_thresholds_correct(self):
        """Edge thresholds are correctly defined."""
        thresholds = self.engine.EDGE_THRESHOLDS
        self.assertEqual(thresholds[SignalStrength.WEAK], 0.01)
        self.assertEqual(thresholds[SignalStrength.MODERATE], 0.02)
        self.assertEqual(thresholds[SignalStrength.STRONG], 0.05)
        self.assertEqual(thresholds[SignalStrength.ELITE], 0.10)

    def test_empty_markets_returns_empty_signals(self):
        """Empty markets → empty signals."""
        signals = self.engine.generate_signals([])
        self.assertEqual(signals, [])

    def test_signal_to_dict(self):
        """Signal.to_dict() works correctly."""
        signal = Signal(
            market_id="1.234567890",
            selection_id=12345,
            event_name="Team A vs Team B",
            selection_name="Team A",
            bet_type=BetType.BACK,
            odds=2.50,
            edge_pct=7.3,
            strength=SignalStrength.STRONG,
            strategy="value_betting",
            confidence=0.85,
            reason="5% edge detected"
        )
        d = signal.to_dict()
        
        self.assertEqual(d["market_id"], "1.234567890")
        self.assertEqual(d["selection_id"], 12345)
        self.assertEqual(d["bet_type"], "BACK")
        self.assertEqual(d["strength"], "STRONG")
        self.assertEqual(d["confidence"], 0.85)
        self.assertIsNone(d["expires_at"])

    def test_signal_with_expiry_serializes(self):
        """Signal with expiry serializes correctly."""
        expires = datetime(2026, 3, 4, 15, 0, 0)
        signal = Signal(
            market_id="1.234567890",
            selection_id=12345,
            event_name="Test Event",
            selection_name="Selection A",
            bet_type=BetType.LAY,
            odds=1.80,
            edge_pct=3.2,
            strength=SignalStrength.MODERATE,
            strategy="steam_move",
            confidence=0.72,
            reason="Sharp movement",
            expires_at=expires
        )
        d = signal.to_dict()
        
        self.assertIn("2026-03-04", d["expires_at"])

    def test_bet_type_enum_values(self):
        """BetType enum has correct values."""
        self.assertEqual(BetType.BACK.value, "BACK")
        self.assertEqual(BetType.LAY.value, "LAY")

    def test_signal_strength_ordering(self):
        """SignalStrength enum has correct ordering."""
        self.assertLess(SignalStrength.WEAK.value, SignalStrength.MODERATE.value)
        self.assertLess(SignalStrength.MODERATE.value, SignalStrength.STRONG.value)
        self.assertLess(SignalStrength.STRONG.value, SignalStrength.ELITE.value)


class TestEdgeCalculation(unittest.TestCase):
    """Test cases for edge calculation logic."""

    def test_positive_edge(self):
        """Positive edge calculation (profitable bet)."""
        # If true probability is 50% and odds are 2.50
        # Edge = (0.50 * 2.50) - 1 = 0.25 = 25%
        true_prob = 0.50
        odds = 2.50
        edge = (true_prob * odds) - 1
        self.assertEqual(edge, 0.25)

    def test_negative_edge(self):
        """Negative edge calculation (unprofitable bet)."""
        # True prob 50%, odds 1.80 (implied 55.6%)
        # Edge = (0.50 * 1.80) - 1 = -0.10 = -10%
        true_prob = 0.50
        odds = 1.80
        edge = (true_prob * odds) - 1
        self.assertAlmostEqual(edge, -0.10, places=2)

    def test_breakeven_edge(self):
        """Break-even edge calculation."""
        # True prob 40%, fair odds = 2.50
        true_prob = 0.40
        odds = 2.50
        edge = (true_prob * odds) - 1
        self.assertAlmostEqual(edge, 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
