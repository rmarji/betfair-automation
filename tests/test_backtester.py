#!/usr/bin/env python3
"""Tests for backtester.py"""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from backtester import (
    BacktestResult,
    BETFAIR_COMMISSION,
    kelly_stake,
    flat_stake,
    run_backtest,
    save_results,
)
from pickwatch_adapter import american_to_decimal


# ── Kelly Stake Tests ──────────────────────────────────────

def test_kelly_positive_edge():
    """Kelly should return positive stake for positive edge."""
    stake = kelly_stake(0.15, 2.5, 1000.0)
    assert stake > 0, "Expected positive stake for positive edge"


def test_kelly_zero_edge():
    """Kelly should return 0 for zero edge."""
    stake = kelly_stake(0.0, 2.5, 1000.0)
    assert stake == 0.0, "Expected zero stake for zero edge"


def test_kelly_negative_edge():
    """Kelly should return 0 for negative edge."""
    stake = kelly_stake(-0.10, 2.5, 1000.0)
    assert stake == 0.0, "Expected zero stake for negative edge"


def test_kelly_respects_max():
    """Kelly stake should not exceed 5% of bankroll."""
    stake = kelly_stake(0.50, 10.0, 1000.0)
    assert stake <= 50.0, f"Stake {stake} exceeds 5% max"


def test_kelly_minimum_stake():
    """Kelly stake should have minimum of 1.0."""
    stake = kelly_stake(0.01, 1.5, 1000.0)
    assert stake >= 1.0, f"Stake {stake} below minimum 1.0"


def test_kelly_odds_1_returns_zero():
    """Kelly with odds <= 1.0 should return 0."""
    assert kelly_stake(0.15, 1.0, 1000.0) == 0.0
    assert kelly_stake(0.15, 0.5, 1000.0) == 0.0


def test_kelly_fractional():
    """Kelly should use 1/4 fraction by default."""
    # Small edge should produce small stake
    stake = kelly_stake(0.05, 2.0, 1000.0, fraction=0.25)
    assert 0 < stake <= 50.0, f"Stake {stake} out of expected range"


# ── Flat Stake Tests ────────────────────────────────────────

def test_flat_stake_default():
    """Flat stake should be 2% of bankroll."""
    stake = flat_stake(1000.0)
    assert stake == 20.0, f"Expected 20.0, got {stake}"


def test_flat_stake_custom():
    """Flat stake with custom percentage."""
    stake = flat_stake(1000.0, pct=0.05)
    assert stake == 50.0, f"Expected 50.0, got {stake}"


# ── BacktestResult Tests ────────────────────────────────────

def test_result_summary_positive():
    """Result summary for positive ROI."""
    result = BacktestResult(
        bankroll_start=1000.0,
        bankroll_end=1150.0,
        total_bets=50,
        wins=30,
        losses=20,
        roi_pct=15.0,
        win_rate=60.0,
        profit_loss=150.0,
    )
    summary = result.summary()
    assert "🟢" in summary
    assert "+15.0%" in summary


def test_result_summary_negative():
    """Result summary for negative ROI."""
    result = BacktestResult(
        bankroll_start=1000.0,
        bankroll_end=850.0,
        total_bets=50,
        wins=20,
        losses=30,
        roi_pct=-15.0,
        win_rate=40.0,
        profit_loss=-150.0,
    )
    summary = result.summary()
    assert "🔴" in summary
    assert "-15.0%" in summary


# ── Run Backtest with Mock DB ──────────────────────────────

def _create_test_db(tmp_dir: str) -> str:
    """Create a temporary Pickwatch DB with test data."""
    db_path = str(Path(tmp_dir) / "test_pickwatch.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE picks (
            id INTEGER PRIMARY KEY,
            date TEXT,
            sport TEXT,
            matchup TEXT,
            pick_team TEXT,
            pick_type TEXT,
            odds_american INTEGER,
            edge REAL,
            confidence_score REAL,
            value_rating INTEGER,
            recommendation TEXT,
            outcome TEXT
        )
    """)
    
    # Insert test picks
    test_picks = [
        (1, "2026-01-01", "NBA", "LAL vs BOS", "Lakers", "ML", 150, 15.0, 70, 4, "BET", "WIN"),
        (2, "2026-01-01", "NBA", "MIA vs NYK", "Heat", "ML", -110, 20.0, 75, 4, "BET", "LOSS"),
        (3, "2026-01-02", "NHL", "BOS vs TOR", "Bruins", "ML", -150, 25.0, 80, 5, "STRONG BET", "WIN"),
        (4, "2026-01-02", "MLB", "NYY vs BOS", "Yankees", "ML", 200, 10.0, 65, 3, "LEAN", "WIN"),  # Below min edge if >10
        (5, "2026-01-03", "NBA", "GSW vs LAC", "Warriors", "ML", -120, 30.0, 85, 5, "STRONG BET", "WIN"),
        (6, "2026-01-03", "NFL", "KC vs BUF", "Chiefs", "ML", -180, 18.0, 78, 4, "BET", "LOSS"),
        (7, "2026-01-04", "NHL", "DET vs CHI", "Red Wings", "ML", 120, 12.0, 62, 3, "BET", "PUSH"),
        (8, "2026-01-04", "NBA", "PHI vs MIL", "76ers", "ML", 100, 35.0, 90, 5, "STRONG BET", "WIN"),
        (9, "2026-01-05", "MLB", "LAD vs SF", "Dodgers", "ML", -140, 8.0, 55, 2, "LEAN", "LOSS"),  # Below min edge + confidence
        (10, "2026-01-05", "NBA", "DAL vs PHX", "Mavs", "ML", 180, 22.0, 72, 4, "BET", "LOSS"),
    ]
    
    c.executemany(
        "INSERT INTO picks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        test_picks,
    )
    
    conn.commit()
    conn.close()
    return db_path


def test_backtest_basic():
    """Run backtest with test data."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=10.0, use_kelly=True)
        
        assert result.total_bets > 0, "Should have some bets"
        assert result.bankroll_start == 1000.0
        # Should have at least the winning bets counted
        assert result.wins > 0, "Should have at least 1 win"
        assert result.equity_curve[0] == 1000.0, "First equity point should be starting bankroll"


def test_backtest_flat_staking():
    """Run backtest with flat staking."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=10.0, use_kelly=False)
        
        assert result.kelly_staking is False
        assert result.total_bets > 0


def test_backtest_sport_filter():
    """Run backtest filtered to one sport."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result = run_backtest(db_path=db_path, sport="NBA", bankroll=1000.0, min_edge=10.0)
        
        # Should only have NBA picks (ids 1,2,5,8,10 pass filters)
        assert result.total_bets > 0
        # All by_sport keys should be NBA
        for sport in result.by_sport:
            assert sport == "NBA", f"Expected NBA only, got {sport}"


def test_backtest_min_edge_filter():
    """Higher min edge should result in fewer bets."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result_low = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=5.0)
        result_high = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=25.0)
        
        assert result_high.total_bets <= result_low.total_bets


def test_backtest_commission_deducted():
    """Verify Betfair commission is deducted from winnings."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=10.0)
        
        # Commission should be > 0 if any wins occurred
        if result.wins > 0:
            assert result.total_commission > 0, "Should have commission on wins"


def test_backtest_drawdown():
    """Drawdown should be tracked."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=10.0)
        
        assert result.max_drawdown >= 0, "Drawdown should be non-negative"


def test_backtest_equity_curve():
    """Equity curve should start at initial bankroll and have correct length."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=10.0)
        
        assert len(result.equity_curve) > 1, "Equity curve should have multiple points"
        assert result.equity_curve[0] == 1000.0, "First point should be starting bankroll"


# ── Save Results Tests ──────────────────────────────────────

def test_save_results():
    """Test that results are saved to DB."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = _create_test_db(tmp_dir)
        result_backtest = run_backtest(db_path=db_path, bankroll=1000.0, min_edge=10.0)
        
        # Use temp DB for results
        import backtester
        orig_db = backtester.BETFAIR_DB
        backtester.BETFAIR_DB = Path(tmp_dir) / "backtest_results.db"
        
        try:
            save_results(result_backtest, sport="NBA")
            
            # Read back
            conn = sqlite3.connect(str(backtester.BETFAIR_DB))
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM backtest_runs")
            count = c.fetchone()[0]
            conn.close()
            
            assert count == 1, "Should have 1 saved run"
        finally:
            backtester.BETFAIR_DB = orig_db


# ── Run All ─────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  ✅ {test.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {test.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  💥 {test.__name__}: {e}")
    
    print(f"\n{'━' * 28}")
    print(f"  {passed} passed, {failed} failed out of {passed + failed}")
    
    sys.exit(1 if failed > 0 else 0)