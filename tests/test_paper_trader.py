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

    def test_lay_win_with_commission(self):
        """LAY win deducts 5% commission from net winnings."""
        # LAY £10 @ 3.0: liability = 10*(3-1) = £20, locked from balance
        # Balance after placing: 1000 - 20 = 980
        pos_id = pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='Team B',
            bet_type='LAY',
            odds=3.0,
            stake=10.0
        )
        
        # won=True means our lay WON (selection lost)
        pt.settle_position(self.conn, pos_id, won=True, commission=0.05)
        
        # Net winnings: £10 (stake won) - 5% commission = £9.50
        # Balance: 980 + 20 (liability return) + 10 (win) - 0.50 (commission) = 1009.50
        final_balance = pt.get_balance(self.conn)
        self.assertAlmostEqual(final_balance, 1009.50, places=2)

    def test_back_win_with_commission(self):
        """BACK win deducts 5% Betfair commission from net winnings."""
        # Place a BACK bet: £10 @ 3.0 odds → potential profit = £20, stake = £10
        pos_id = pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='Team A',
            bet_type='BACK',
            odds=3.0,
            stake=10.0
        )
        # Balance after placing: 1000 - 10 = 990
        
        # won=True means our back bet WON (selection won)
        pt.settle_position(self.conn, pos_id, won=True, commission=0.05)
        
        # Net winnings: £20 profit - 5% commission = £19
        # Balance: 990 + 10 (stake return) + 20 (profit) - 1 (commission) = 1019
        final_balance = pt.get_balance(self.conn)
        self.assertAlmostEqual(final_balance, 1019.00, places=2)

    def test_back_loss_no_commission(self):
        """BACK loss: no commission (nothing won)."""
        pos_id = pt.place_bet(
            conn=self.conn,
            market_id='1.234',
            selection_id=1,
            event_name='Test',
            selection_name='Team A',
            bet_type='BACK',
            odds=2.5,
            stake=10.0
        )
        
        pt.settle_position(self.conn, pos_id, won=False, commission=0.05)
        
        # Lost: stake was already deducted, no additional commission
        final_balance = pt.get_balance(self.conn)
        self.assertEqual(final_balance, 990.0)  # 1000 - 10 stake


if __name__ == "__main__":
    unittest.main()
