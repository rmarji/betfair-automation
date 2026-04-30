#!/usr/bin/env python3
"""
Betfair Signal Engine

Generates betting signals using multiple strategies:
1. Value Betting - Edge vs market odds
2. Steam Moves - Sharp line movement detection
3. Pickwatch Integration - Use +Edge picks as signals

Usage:
    from signal_engine import SignalEngine
    
    engine = SignalEngine()
    signals = engine.generate_signals(markets)
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


class BetType(Enum):
    BACK = "BACK"
    LAY = "LAY"


class SignalStrength(Enum):
    WEAK = 1      # Edge 1-2%
    MODERATE = 2  # Edge 2-5%
    STRONG = 3    # Edge 5-10%
    ELITE = 4     # Edge >10%


@dataclass
class Signal:
    """A betting signal with conviction and metadata."""
    market_id: str
    selection_id: int
    event_name: str
    selection_name: str
    bet_type: BetType
    odds: float
    edge_pct: float
    strength: SignalStrength
    strategy: str
    confidence: float  # 0-1
    reason: str
    expires_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "selection_id": self.selection_id,
            "event_name": self.event_name,
            "selection_name": self.selection_name,
            "bet_type": self.bet_type.value,
            "odds": self.odds,
            "edge_pct": self.edge_pct,
            "strength": self.strength.name,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "reason": self.reason,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None
        }


class SignalEngine:
    """Generates betting signals from market data."""
    
    # Minimum edge required for each strength level
    EDGE_THRESHOLDS = {
        SignalStrength.WEAK: 0.01,
        SignalStrength.MODERATE: 0.02,
        SignalStrength.STRONG: 0.05,
        SignalStrength.ELITE: 0.10,
    }
    
    # Minimum confidence to emit signal
    MIN_CONFIDENCE = 0.6
    
    def __init__(self):
        self.strategies = [
            self._value_betting,
            self._steam_move,
            self._pickwatch_edge,
        ]
    
    def generate_signals(self, markets: list) -> list[Signal]:
        """
        Generate signals for a list of markets.
        
        Args:
            markets: List of market data from Betfair API
            
        Returns:
            List of Signal objects, sorted by edge
        """
        signals = []
        
        for market in markets:
            for strategy in self.strategies:
                market_signals = strategy(market)
                signals.extend(market_signals)
        
        # Filter by minimum confidence
        signals = [s for s in signals if s.confidence >= self.MIN_CONFIDENCE]
        
        # Sort by edge (highest first)
        signals.sort(key=lambda s: s.edge_pct, reverse=True)
        
        return signals
    
    def _get_strength(self, edge_pct: float) -> SignalStrength:
        """Determine signal strength from edge percentage."""
        if edge_pct >= self.EDGE_THRESHOLDS[SignalStrength.ELITE]:
            return SignalStrength.ELITE
        elif edge_pct >= self.EDGE_THRESHOLDS[SignalStrength.STRONG]:
            return SignalStrength.STRONG
        elif edge_pct >= self.EDGE_THRESHOLDS[SignalStrength.MODERATE]:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def _value_betting(self, market: dict) -> list[Signal]:
        """
        Value betting strategy.
        
        Compares market odds to a fair value model.
        Signal when edge > threshold.
        
        Requirements:
        - Market must have 'fair_odds' calculated (e.g., from external model)
        - Or implied from vig-removed odds
        """
        signals = []
        
        # Skip if no fair odds available
        if "fair_odds" not in market:
            return signals
        
        fair_odds = market["fair_odds"]
        
        for runner in market.get("runners", []):
            selection_id = runner.get("selectionId")
            selection_name = runner.get("runnerName", f"Selection {selection_id}")
            
            # Get best back/lay prices
            back_prices = runner.get("ex", {}).get("availableToBack", [])
            lay_prices = runner.get("ex", {}).get("availableToLay", [])
            
            if not back_prices:
                continue
                
            best_back = back_prices[0]["price"]
            runner_fair = fair_odds.get(selection_id)
            
            if not runner_fair:
                continue
            
            # Calculate edge: (back_odds - fair_odds) / fair_odds
            edge = (best_back - runner_fair) / runner_fair
            
            if edge >= self.EDGE_THRESHOLDS[SignalStrength.WEAK]:
                signals.append(Signal(
                    market_id=market["marketId"],
                    selection_id=selection_id,
                    event_name=market.get("eventName", "Unknown Event"),
                    selection_name=selection_name,
                    bet_type=BetType.BACK,
                    odds=best_back,
                    edge_pct=edge,
                    strength=self._get_strength(edge),
                    strategy="value",
                    confidence=min(0.5 + edge * 5, 0.95),  # Scale confidence with edge
                    reason=f"Back @ {best_back:.2f} vs fair {runner_fair:.2f} ({edge*100:.1f}% edge)"
                ))
        
        return signals
    
    def _steam_move(self, market: dict) -> list[Signal]:
        """
        Steam move detection.
        
        Identifies sharp line movement (significant odds drops).
        Requires historical odds data.
        
        Requirements:
        - Market must have 'odds_history' with timestamps
        """
        signals = []
        
        # Skip if no odds history
        if "odds_history" not in market:
            return signals
        
        history = market["odds_history"]
        
        for runner in market.get("runners", []):
            selection_id = runner.get("selectionId")
            selection_name = runner.get("runnerName", f"Selection {selection_id}")
            
            runner_history = history.get(selection_id, [])
            if len(runner_history) < 2:
                continue
            
            # Get current and previous odds
            current = runner_history[-1]["price"]
            previous = runner_history[-2]["price"]
            time_diff = (
                datetime.fromisoformat(runner_history[-1]["timestamp"]) - 
                datetime.fromisoformat(runner_history[-2]["timestamp"])
            )
            
            # Calculate move percentage
            move_pct = (previous - current) / previous
            
            # Steam move: >5% drop in <1 hour
            if move_pct >= 0.05 and time_diff <= timedelta(hours=1):
                # Back the selection (follow the steam)
                back_prices = runner.get("ex", {}).get("availableToBack", [])
                if not back_prices:
                    continue
                
                best_back = back_prices[0]["price"]
                
                signals.append(Signal(
                    market_id=market["marketId"],
                    selection_id=selection_id,
                    event_name=market.get("eventName", "Unknown Event"),
                    selection_name=selection_name,
                    bet_type=BetType.BACK,
                    odds=best_back,
                    edge_pct=move_pct * 0.3,  # Estimated edge from steam
                    strength=SignalStrength.MODERATE,
                    strategy="steam",
                    confidence=0.65,
                    reason=f"Steam: {previous:.2f} → {current:.2f} ({move_pct*100:.1f}% drop in {time_diff})"
                ))
        
        return signals
    
    def _pickwatch_edge(self, market: dict) -> list[Signal]:
        """
        Pickwatch integration strategy.
        
        Uses +Edge picks from Pickwatch as betting signals.
        
        Requirements:
        - Market must have 'pickwatch_data' with edge scores
        """
        signals = []
        
        # Skip if no Pickwatch data
        if "pickwatch_data" not in market:
            return signals
        
        pickwatch = market["pickwatch_data"]
        
        for runner in market.get("runners", []):
            selection_id = runner.get("selectionId")
            selection_name = runner.get("runnerName", f"Selection {selection_id}")
            
            # Match Pickwatch pick to runner
            pick = pickwatch.get(selection_name) or pickwatch.get(selection_id)
            if not pick:
                continue
            
            edge = pick.get("edge", 0)
            expert_pct = pick.get("expert_pct", 0.5)
            
            # Signal if +Edge and majority expert support
            if edge >= self.EDGE_THRESHOLDS[SignalStrength.WEAK] and expert_pct >= 0.6:
                back_prices = runner.get("ex", {}).get("availableToBack", [])
                if not back_prices:
                    continue
                
                best_back = back_prices[0]["price"]
                
                signals.append(Signal(
                    market_id=market["marketId"],
                    selection_id=selection_id,
                    event_name=market.get("eventName", "Unknown Event"),
                    selection_name=selection_name,
                    bet_type=BetType.BACK,
                    odds=best_back,
                    edge_pct=edge,
                    strength=self._get_strength(edge),
                    strategy="pickwatch",
                    confidence=expert_pct,
                    reason=f"Pickwatch +{edge*100:.1f}% edge, {expert_pct*100:.0f}% experts"
                ))
        
        return signals


def demo():
    """Demo with mock data."""
    engine = SignalEngine()
    
    # Mock market with fair odds
    mock_market = {
        "marketId": "1.234567890",
        "eventName": "NHL: Bruins vs Maple Leafs",
        "runners": [
            {
                "selectionId": 12345,
                "runnerName": "Boston Bruins",
                "ex": {
                    "availableToBack": [{"price": 2.20, "size": 500}],
                    "availableToLay": [{"price": 2.22, "size": 300}]
                }
            },
            {
                "selectionId": 12346,
                "runnerName": "Toronto Maple Leafs", 
                "ex": {
                    "availableToBack": [{"price": 1.85, "size": 400}],
                    "availableToLay": [{"price": 1.87, "size": 350}]
                }
            }
        ],
        "fair_odds": {
            12345: 2.05,  # Fair odds for Bruins
            12346: 1.95,  # Fair odds for Leafs
        }
    }
    
    signals = engine.generate_signals([mock_market])
    
    print("🎯 **DEMO SIGNALS**")
    print("━" * 20)
    
    for signal in signals:
        strength_emoji = {
            SignalStrength.WEAK: "⚪",
            SignalStrength.MODERATE: "🟡",
            SignalStrength.STRONG: "🟠",
            SignalStrength.ELITE: "🔴"
        }
        
        print(f"{strength_emoji[signal.strength]} {signal.event_name}")
        print(f"   {signal.bet_type.value} {signal.selection_name} @ {signal.odds:.2f}")
        print(f"   Edge: {signal.edge_pct*100:.1f}% | Confidence: {signal.confidence*100:.0f}%")
        print(f"   Reason: {signal.reason}")
        print()


if __name__ == "__main__":
    demo()
