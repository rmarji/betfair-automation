#!/usr/bin/env python3
"""Tests for config.py - Betfair Trading Configuration"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Reset singleton before importing
import importlib
import config as config_module


def reset_config_singleton():
    """Reset the Config singleton for test isolation."""
    config_module.Config._instance = None


class TestConfigDefaults(unittest.TestCase):
    """Tests for default configuration values."""
    
    def setUp(self):
        reset_config_singleton()
        # Patch CONFIG_FILE to prevent real file access
        self.temp_dir = tempfile.mkdtemp()
        self.fake_config = Path(self.temp_dir) / "config.json"
        self.patcher = patch.object(config_module, 'CONFIG_FILE', self.fake_config)
        self.patcher.start()
        reset_config_singleton()
    
    def tearDown(self):
        self.patcher.stop()
        reset_config_singleton()
        # Cleanup
        if self.fake_config.exists():
            self.fake_config.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_default_initial_balance(self):
        """Test default initial balance is £1000."""
        cfg = config_module.Config()
        self.assertEqual(cfg.initial_balance, 1000.00)
    
    def test_default_max_positions(self):
        """Test default max positions is 5."""
        cfg = config_module.Config()
        self.assertEqual(cfg.max_positions, 5)
    
    def test_default_stake(self):
        """Test default stake is £10."""
        cfg = config_module.Config()
        self.assertEqual(cfg.default_stake, 10.00)
    
    def test_default_odds_filters(self):
        """Test default odds filters."""
        cfg = config_module.Config()
        self.assertEqual(cfg.min_odds, 1.10)
        self.assertEqual(cfg.max_odds, 10.0)
    
    def test_default_signal_params(self):
        """Test default signal parameters (MLB-optimized per backtesting)."""
        cfg = config_module.Config()
        self.assertEqual(cfg.min_edge, 30.0)  # Raised from 2.0 per backtesting
        self.assertEqual(cfg.min_confidence, 0.6)
    
    def test_default_strategy_weights(self):
        """Test strategy weights sum to 1.0."""
        cfg = config_module.Config()
        weights = cfg.strategy_weights
        
        self.assertIn("value", weights)
        self.assertIn("momentum", weights)
        self.assertIn("arbitrage", weights)
        
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=2)
    
    def test_default_tracked_sports(self):
        """Test default tracked sports list (MLB-focused per backtesting)."""
        cfg = config_module.Config()
        sports = cfg.tracked_sports
        
        self.assertIn("baseball", sports)  # MLB-only default per backtesting
    
    def test_default_auto_settle(self):
        """Test auto settle is enabled by default."""
        cfg = config_module.Config()
        self.assertTrue(cfg.auto_settle_enabled)


class TestConfigFileIO(unittest.TestCase):
    """Tests for config file operations."""
    
    def setUp(self):
        reset_config_singleton()
        self.temp_dir = tempfile.mkdtemp()
        self.fake_config = Path(self.temp_dir) / "config.json"
        self.patcher = patch.object(config_module, 'CONFIG_FILE', self.fake_config)
        self.patcher.start()
        reset_config_singleton()
    
    def tearDown(self):
        self.patcher.stop()
        reset_config_singleton()
        if self.fake_config.exists():
            self.fake_config.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_load_missing_file_uses_defaults(self):
        """Test loading non-existent file returns defaults."""
        cfg = config_module.Config()
        
        self.assertEqual(cfg.initial_balance, 1000.00)
        self.assertEqual(cfg.max_positions, 5)
    
    def test_save_creates_file(self):
        """Test save creates config file."""
        cfg = config_module.Config()
        cfg.save()
        
        self.assertTrue(self.fake_config.exists())
        
        with open(self.fake_config) as f:
            data = json.load(f)
        
        self.assertEqual(data["initial_balance"], 1000.00)
    
    def test_load_partial_override(self):
        """Test loading partial config overrides only specified values."""
        with open(self.fake_config, 'w') as f:
            json.dump({
                "initial_balance": 2000.00,
                "max_positions": 10
            }, f)
        
        cfg = config_module.Config()
        
        # Overridden values
        self.assertEqual(cfg.initial_balance, 2000.00)
        self.assertEqual(cfg.max_positions, 10)
        
        # Default values preserved
        self.assertEqual(cfg.default_stake, 10.00)
        self.assertEqual(cfg.min_odds, 1.10)
    
    def test_reload_picks_up_changes(self):
        """Test reload picks up file changes."""
        cfg = config_module.Config()
        self.assertEqual(cfg.initial_balance, 1000.00)
        
        # Write new config
        with open(self.fake_config, 'w') as f:
            json.dump({"initial_balance": 5000.00}, f)
        
        cfg.reload()
        self.assertEqual(cfg.initial_balance, 5000.00)
    
    def test_set_and_save(self):
        """Test set() saves to file."""
        cfg = config_module.Config()
        cfg.set("max_positions", 7)
        
        # Check saved
        with open(self.fake_config) as f:
            data = json.load(f)
        
        self.assertEqual(data["max_positions"], 7)
    
    def test_reset_restores_defaults(self):
        """Test reset() restores default values."""
        cfg = config_module.Config()
        cfg.set("max_positions", 20)
        self.assertEqual(cfg.max_positions, 20)
        
        cfg.reset()
        self.assertEqual(cfg.max_positions, 5)


class TestConfigSingleton(unittest.TestCase):
    """Tests for singleton pattern."""
    
    def setUp(self):
        reset_config_singleton()
        self.temp_dir = tempfile.mkdtemp()
        self.fake_config = Path(self.temp_dir) / "config.json"
        self.patcher = patch.object(config_module, 'CONFIG_FILE', self.fake_config)
        self.patcher.start()
        reset_config_singleton()
    
    def tearDown(self):
        self.patcher.stop()
        reset_config_singleton()
        if self.fake_config.exists():
            self.fake_config.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_singleton_returns_same_instance(self):
        """Test Config() returns same instance."""
        cfg1 = config_module.Config()
        cfg2 = config_module.Config()
        self.assertIs(cfg1, cfg2)
    
    def test_singleton_preserves_changes(self):
        """Test changes persist across Config() calls."""
        cfg1 = config_module.Config()
        cfg1._data["max_positions"] = 99
        
        cfg2 = config_module.Config()
        self.assertEqual(cfg2.max_positions, 99)
    
    def test_to_dict_returns_copy(self):
        """Test to_dict returns a copy, not reference."""
        cfg = config_module.Config()
        data = cfg.to_dict()
        
        data["max_positions"] = 999
        
        self.assertNotEqual(cfg.max_positions, 999)


class TestConfigEdgeCases(unittest.TestCase):
    """Edge case tests."""
    
    def setUp(self):
        reset_config_singleton()
        self.temp_dir = tempfile.mkdtemp()
        self.fake_config = Path(self.temp_dir) / "config.json"
        self.patcher = patch.object(config_module, 'CONFIG_FILE', self.fake_config)
        self.patcher.start()
        reset_config_singleton()
    
    def tearDown(self):
        self.patcher.stop()
        reset_config_singleton()
        if self.fake_config.exists():
            self.fake_config.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_invalid_json_uses_defaults(self):
        """Test invalid JSON file falls back to defaults."""
        with open(self.fake_config, 'w') as f:
            f.write("not valid json {{{")
        
        cfg = config_module.Config()
        
        # Should have defaults
        self.assertEqual(cfg.initial_balance, 1000.00)
    
    def test_get_with_default(self):
        """Test get() returns default for missing keys."""
        cfg = config_module.Config()
        
        result = cfg.get("nonexistent_key", "default_value")
        self.assertEqual(result, "default_value")
    
    def test_get_existing_key(self):
        """Test get() returns value for existing keys."""
        cfg = config_module.Config()
        
        result = cfg.get("max_positions")
        self.assertEqual(result, 5)


class TestFormatConfigDisplay(unittest.TestCase):
    """Tests for display formatting."""
    
    def setUp(self):
        reset_config_singleton()
        self.temp_dir = tempfile.mkdtemp()
        self.fake_config = Path(self.temp_dir) / "config.json"
        self.patcher = patch.object(config_module, 'CONFIG_FILE', self.fake_config)
        self.patcher.start()
        reset_config_singleton()
    
    def tearDown(self):
        self.patcher.stop()
        reset_config_singleton()
        if self.fake_config.exists():
            self.fake_config.unlink()
        Path(self.temp_dir).rmdir()
    
    def test_format_includes_sections(self):
        """Test format output includes key sections."""
        cfg = config_module.Config()
        output = config_module.format_config_display(cfg)
        
        self.assertIn("BETFAIR TRADING CONFIG", output)
        self.assertIn("Risk Management", output)
        self.assertIn("Odds Filters", output)
        self.assertIn("Signal Parameters", output)
        self.assertIn("Strategy Weights", output)
        self.assertIn("Tracked Sports", output)
    
    def test_format_includes_values(self):
        """Test format output includes actual values."""
        cfg = config_module.Config()
        output = config_module.format_config_display(cfg)
        
        self.assertIn("£1,000.00", output)  # Initial balance
        self.assertIn("5", output)  # Max positions
        self.assertIn("baseball", output)  # MLB-focused sport


if __name__ == "__main__":
    unittest.main()
