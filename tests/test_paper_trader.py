#!/usr/bin/env python3
"""
Unit tests for Betfair Paper Trader

Tests bet placement, P&L calculation, and position management.
Run with: python3 -m unittest tests.test_paper_trader
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import tempfile
import unittest
from pathlib import Path
import paper_trader as pt


class TestPaperTrader(unittest.TestCase):
    """Test cases for paper trading functionality."""

    def setUp(self):
        """Create a fresh test database for each test."""
        self.test_db = tempfile.mktemp(suffix='.db')
        pt.DB_PATH = Path(self.test_db)
        pt.init_db()
        self.conn = sqlite3.connect(self.test_db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        """Clean up test database."""
        self.conn.close()
        if os.path.exists(self.test_db):
            os.unlink(self.test_db)

    def test_database_initializes(self):
        """Database initializes correctly."""
        self.assertTrue(Path(self.test_db).exists())

    def test_initial_balance(self):
        """Initial balance is £1,000."""
        balance = pt.get_balance(self.conn)
        self.assertEqual(balance, 1000.0)

    def test_back_bet_deducts_stake(self):
        """BACK bet deducts stake from balance."""
        initial = pt.get_balance(self.conn)
        pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='Team A',
            bet_type='BACK',
            odds=2.5,
            stake=10.0
        )
        final = pt.get_balance(self.conn)
        self.assertEqual(final, initial - 10.0)

    def test_lay_bet_deducts_liability(self):
        """LAY bet deducts liability from balance."""
        initial = pt.get_balance(self.conn)
        pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='Team B',
            bet_type='LAY',
            odds=2.5,
            stake=10.0
        )
        final = pt.get_balance(self.conn)
        liability = 10.0 * (2.5 - 1)  # £15
        expected = initial - liability
        self.assertEqual(final, expected)

    def test_position_count_increases(self):
        """Position count increases after placing bet."""
        positions = pt.get_open_positions(self.conn)
        self.assertEqual(len(positions), 0)
        
        pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='Team A',
            bet_type='BACK',
            odds=2.0,
            stake=10.0
        )
        
        positions = pt.get_open_positions(self.conn)
        self.assertEqual(len(positions), 1)

    def test_reset_restores_initial_state(self):
        """Reset restores initial balance and clears positions."""
        pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='A',
            bet_type='BACK',
            odds=2.0,
            stake=100.0
        )
        
        pt.reset_portfolio(self.conn)
        balance = pt.get_balance(self.conn)
        positions = pt.get_open_positions(self.conn)
        
        self.assertEqual(balance, 1000.0)
        self.assertEqual(len(positions), 0)

    def test_constants_defined(self):
        """Constants are correctly defined."""
        self.assertEqual(pt.INITIAL_BALANCE, 1000.0)
        self.assertEqual(pt.MAX_POSITIONS, 5)
        self.assertEqual(pt.DEFAULT_STAKE, 10.0)


if __name__ == "__main__":
    unittest.main()
