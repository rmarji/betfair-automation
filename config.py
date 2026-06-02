#!/usr/bin/env python3
"""
Betfair Trading Configuration

Centralizes all configurable parameters for the Betfair paper trading system.
Parameters can be adjusted via config.json without code changes.

Usage:
    from config import Config
    cfg = Config()
    max_stake = cfg.max_stake_pct
    cfg.set("max_stake_pct", 0.08)
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_FILE = Path(__file__).parent / "config.json"

# Default configuration values
DEFAULTS = {
    # Risk Management
    "initial_balance": 1000.00,      # £1000 paper money
    "max_positions": 5,              # Max concurrent positions
    "default_stake": 10.00,          # £10 per bet
    "max_stake_pct": 0.05,           # Max 5% of balance per bet
    
    # Odds Filters
    "min_odds": 1.10,                # Minimum acceptable odds
    "max_odds": 10.0,                # Maximum acceptable odds (avoid longshots)
    
    # Signal Parameters
    "min_edge": 30.0,                # Minimum edge % to trigger trade (backtested: MLB ≥30%)
    "min_confidence": 0.6,           # Minimum signal confidence (0-1)
    
    # Strategy Weights (must sum to 1.0)
    "strategy_weights": {
        "value": 0.5,                # Value betting (implied vs actual prob)
        "momentum": 0.3,             # Price momentum / steam moves
        "arbitrage": 0.2,            # Arb opportunities
    },
    
    # Markets to Track (MLB-focused per backtesting results)
    "tracked_sports": [
        "baseball",
    ],
    
    # Per-sport thresholds (override global min_edge/min_confidence)
    # Backtesting showed only MLB ≥30% edge, ≥60% confidence is profitable
    "sport_thresholds": {
        "baseball": {
            "min_edge": 30.0,
            "min_confidence": 0.6,
            "enabled": True,
        },
        "basketball": {
            "min_edge": 30.0,
            "min_confidence": 0.65,
            "enabled": False,
        },
        "ice_hockey": {
            "min_edge": 30.0,
            "min_confidence": 0.65,
            "enabled": False,
        },
        "american_football": {
            "min_edge": 30.0,
            "min_confidence": 0.65,
            "enabled": False,
        },
    },
    
    # Betfair commission on net winnings (standard rate)
    "betfair_commission": 0.05,      # 5% standard rate
    
    # Auto-settlement
    "auto_settle_enabled": True,     # Auto-settle expired positions
    "settlement_check_hours": 24,    # Check for settlements every N hours
}


class Config:
    """Singleton configuration manager."""
    
    _instance: Optional["Config"] = None
    _data: Dict[str, Any]
    
    def __new__(cls) -> "Config":
        """Ensure single instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = cls._load_config()
        return cls._instance
    
    @classmethod
    def _load_config(cls) -> Dict[str, Any]:
        """Load config from file or use defaults."""
        config = DEFAULTS.copy()
        
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    user_config = json.load(f)
                config.update(user_config)
            except (json.JSONDecodeError, IOError) as e:
                print(f"⚠️ Config load error: {e}, using defaults")
        
        return config
    
    def reload(self) -> None:
        """Reload configuration from file."""
        self._data = self._load_config()
    
    def save(self) -> None:
        """Save current configuration to file."""
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set a configuration value and save."""
        self._data[key] = value
        self.save()
    
    def reset(self) -> None:
        """Reset to defaults."""
        self._data = DEFAULTS.copy()
        self.save()
    
    def to_dict(self) -> Dict[str, Any]:
        """Return full config as dict."""
        return self._data.copy()
    
    # Convenience properties
    @property
    def initial_balance(self) -> float:
        return self._data["initial_balance"]
    
    @property
    def max_positions(self) -> int:
        return self._data["max_positions"]
    
    @property
    def default_stake(self) -> float:
        return self._data["default_stake"]
    
    @property
    def max_stake_pct(self) -> float:
        return self._data["max_stake_pct"]
    
    @property
    def min_odds(self) -> float:
        return self._data["min_odds"]
    
    @property
    def max_odds(self) -> float:
        return self._data["max_odds"]
    
    @property
    def min_edge(self) -> float:
        return self._data["min_edge"]
    
    @property
    def min_confidence(self) -> float:
        return self._data["min_confidence"]
    
    @property
    def strategy_weights(self) -> Dict[str, float]:
        return self._data["strategy_weights"]
    
    @property
    def tracked_sports(self) -> List[str]:
        return self._data["tracked_sports"]
    
    @property
    def auto_settle_enabled(self) -> bool:
        return self._data["auto_settle_enabled"]
    
    @property
    def sport_thresholds(self) -> Dict[str, Any]:
        return self._data.get("sport_thresholds", {})
    
    @property
    def betfair_commission(self) -> float:
        return self._data.get("betfair_commission", 0.05)
    
    def get_sport_config(self, sport: str) -> Dict[str, Any]:
        """Get sport-specific thresholds merged with global defaults."""
        sport_cfg = self.sport_thresholds.get(sport, {})
        return {
            "min_edge": sport_cfg.get("min_edge", self.min_edge),
            "min_confidence": sport_cfg.get("min_confidence", self.min_confidence),
            "enabled": sport_cfg.get("enabled", True),
        }


def format_config_display(cfg: Config) -> str:
    """Format config for terminal display."""
    weights = cfg.strategy_weights
    sports = cfg.tracked_sports
    
    lines = [
        "📊 **BETFAIR TRADING CONFIG**",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "**Risk Management**",
        f"  Initial Balance: £{cfg.initial_balance:,.2f}",
        f"  Max Positions:   {cfg.max_positions}",
        f"  Default Stake:   £{cfg.default_stake:.2f}",
        f"  Max Stake %:     {cfg.max_stake_pct * 100:.1f}%",
        "",
        "**Odds Filters**",
        f"  Min Odds: {cfg.min_odds:.2f}",
        f"  Max Odds: {cfg.max_odds:.2f}",
        "",
        "**Signal Parameters**",
        f"  Min Edge:       {cfg.min_edge:.1f}%",
        f"  Min Confidence: {cfg.min_confidence * 100:.0f}%",
        "",
        "**Strategy Weights**",
    ]
    
    for strategy, weight in weights.items():
        lines.append(f"  {strategy}: {weight * 100:.0f}%")
    
    lines.extend([
        "",
        "**Tracked Sports**",
        f"  {', '.join(sports)}",
        "",
        "**Settlement**",
        f"  Auto-settle: {'enabled' if cfg.auto_settle_enabled else 'disabled'}",
    ])
    
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    
    cfg = Config()
    
    if len(sys.argv) < 2:
        print(format_config_display(cfg))
    elif sys.argv[1] == "--set" and len(sys.argv) >= 4:
        key = sys.argv[2]
        value = sys.argv[3]
        
        # Type conversion
        if value.replace(".", "").isdigit():
            value = float(value) if "." in value else int(value)
        elif value.lower() in ("true", "false"):
            value = value.lower() == "true"
        
        cfg.set(key, value)
        print(f"✅ Set {key} = {value}")
        print(f"   Config saved to {CONFIG_FILE.name}")
    elif sys.argv[1] == "--reset":
        cfg.reset()
        print("✅ Config reset to defaults")
    elif sys.argv[1] == "--json":
        print(json.dumps(cfg.to_dict(), indent=2))
    else:
        print("Usage: config.py [--set KEY VALUE | --reset | --json]")
