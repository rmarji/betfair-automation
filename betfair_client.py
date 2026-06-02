#!/usr/bin/env python3
"""
Betfair Exchange API Client

Provides authenticated access to Betfair Exchange for:
- Market discovery (sports, events, markets)
- Odds retrieval
- Order placement (paper and live)

Auth Methods:
1. Certificate-based (recommended for automation)
2. Interactive login (password-based, for testing)

Usage:
    # With certificates
    client = BetfairClient.from_certs(
        username="your_username",
        app_key="your_app_key",
        cert_path="config/certs/client-2048.crt",
        key_path="config/certs/client-2048.key"
    )
    
    # Interactive (testing only)
    client = BetfairClient.interactive(
        username="your_username",
        password="your_password",
        app_key="your_app_key"
    )
    
    # List sports
    sports = client.list_sports()
    
    # Get markets for a sport
    markets = client.list_markets(sport_id=7524)  # NHL
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Sport IDs for key markets
SPORT_IDS = {
    "soccer": 1,
    "tennis": 2,
    "golf": 3,
    "cricket": 4,
    "rugby_union": 5,
    "boxing": 6,
    "horse_racing": 7,
    "motor_sport": 8,
    "american_football": 6423,  # NFL
    "basketball": 7522,          # NBA
    "ice_hockey": 7524,          # NHL
    "baseball": 7523,            # MLB
}

# Market types
MARKET_TYPES = {
    "match_odds": "MATCH_ODDS",
    "over_under": "OVER_UNDER_25",
    "moneyline": "MONEY_LINE",
    "spread": "HANDICAP",
    "winner": "WINNER",
}


class BetfairClient:
    """Betfair Exchange API client with multiple auth methods."""
    
    def __init__(self):
        self._trading = None
        self._logged_in = False
        self._username = None
        self._app_key = None
    
    @classmethod
    def from_certs(
        cls,
        username: str,
        app_key: str,
        cert_path: str,
        key_path: str
    ) -> "BetfairClient":
        """
        Create client with certificate-based auth (recommended).
        
        Certificates can be generated at:
        https://developer.betfair.com/accounts/apps/
        
        Args:
            username: Betfair username
            app_key: Betfair API app key
            cert_path: Path to .crt file
            key_path: Path to .key file
        """
        try:
            import betfairlightweight
        except ImportError:
            raise ImportError(
                "betfairlightweight not installed. Run: pip install betfairlightweight"
            )
        
        # Validate cert files exist
        if not os.path.exists(cert_path):
            raise FileNotFoundError(f"Certificate not found: {cert_path}")
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Key file not found: {key_path}")
        
        client = cls()
        client._username = username
        client._app_key = app_key
        
        # Create trading client with certificates
        client._trading = betfairlightweight.APIClient(
            username=username,
            app_key=app_key,
            certs=(cert_path, key_path)
        )
        
        # Login
        try:
            client._trading.login()
            client._logged_in = True
        except Exception as e:
            raise ConnectionError(f"Certificate login failed: {e}")
        
        return client
    
    @classmethod
    def interactive(
        cls,
        username: str,
        password: str,
        app_key: str
    ) -> "BetfairClient":
        """
        Create client with interactive (password) login.
        
        Note: Certificate auth is more secure and recommended for automation.
        
        Args:
            username: Betfair username
            password: Betfair password
            app_key: Betfair API app key
        """
        try:
            import betfairlightweight
        except ImportError:
            raise ImportError(
                "betfairlightweight not installed. Run: pip install betfairlightweight"
            )
        
        client = cls()
        client._username = username
        client._app_key = app_key
        
        # Create trading client with password
        client._trading = betfairlightweight.APIClient(
            username=username,
            password=password,
            app_key=app_key
        )
        
        # Login
        try:
            client._trading.login_interactive()
            client._logged_in = True
        except Exception as e:
            raise ConnectionError(f"Interactive login failed: {e}")
        
        return client
    
    @classmethod
    def from_config(cls, config_path: str = "config/credentials.json") -> "BetfairClient":
        """
        Create client from config file.
        
        Config format:
        {
            "username": "...",
            "app_key": "...",
            "cert_path": "config/certs/client.crt",
            "key_path": "config/certs/client.key"
        }
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Config not found: {config_path}\n"
                f"Create it with your Betfair credentials."
            )
        
        with open(config_path) as f:
            config = json.load(f)
        
        return cls.from_certs(
            username=config["username"],
            app_key=config["app_key"],
            cert_path=config.get("cert_path", "config/certs/client.crt"),
            key_path=config.get("key_path", "config/certs/client.key")
        )
    
    def _ensure_logged_in(self):
        """Verify we're logged in."""
        if not self._logged_in or not self._trading:
            raise RuntimeError("Not logged in. Create client with from_certs() or interactive().")
    
    def logout(self):
        """Logout and cleanup."""
        if self._trading and self._logged_in:
            try:
                self._trading.logout()
            except Exception:
                pass
            self._logged_in = False
    
    # ========== Market Discovery ==========
    
    def list_sports(self) -> list[dict]:
        """
        List all available sports/event types.
        
        Returns:
            List of {id, name, market_count}
        """
        self._ensure_logged_in()
        
        event_types = self._trading.betting.list_event_types()
        
        return [
            {
                "id": et.event_type.id,
                "name": et.event_type.name,
                "market_count": et.market_count,
            }
            for et in event_types
        ]
    
    def list_events(
        self,
        sport_id: int,
        days_ahead: int = 7
    ) -> list[dict]:
        """
        List upcoming events for a sport.
        
        Args:
            sport_id: Sport ID (use SPORT_IDS dict)
            days_ahead: How many days ahead to look
            
        Returns:
            List of {id, name, country_code, timezone, open_date, market_count}
        """
        self._ensure_logged_in()
        
        market_filter = {
            "eventTypeIds": [str(sport_id)],
            "marketStartTime": {
                "from": datetime.utcnow().isoformat(),
                "to": (datetime.utcnow() + timedelta(days=days_ahead)).isoformat()
            }
        }
        
        events = self._trading.betting.list_events(filter=market_filter)
        
        return [
            {
                "id": e.event.id,
                "name": e.event.name,
                "country_code": e.event.country_code,
                "timezone": e.event.timezone,
                "open_date": e.event.open_date.isoformat() if e.event.open_date else None,
                "market_count": e.market_count,
            }
            for e in events
        ]
    
    def list_markets(
        self,
        sport_id: Optional[int] = None,
        event_id: Optional[str] = None,
        market_types: Optional[list[str]] = None,
        days_ahead: int = 7,
        max_results: int = 100
    ) -> list[dict]:
        """
        List available markets.
        
        Args:
            sport_id: Filter by sport ID
            event_id: Filter by event ID
            market_types: Filter by market types (e.g., ["MATCH_ODDS"])
            days_ahead: How many days ahead
            max_results: Maximum results to return
            
        Returns:
            List of market info dicts
        """
        self._ensure_logged_in()
        
        market_filter = {}
        
        if sport_id:
            market_filter["eventTypeIds"] = [str(sport_id)]
        
        if event_id:
            market_filter["eventIds"] = [str(event_id)]
        
        if market_types:
            market_filter["marketTypeCodes"] = market_types
        
        market_filter["marketStartTime"] = {
            "from": datetime.utcnow().isoformat(),
            "to": (datetime.utcnow() + timedelta(days=days_ahead)).isoformat()
        }
        
        markets = self._trading.betting.list_market_catalogue(
            filter=market_filter,
            market_projection=["EVENT", "COMPETITION", "MARKET_START_TIME", "RUNNER_DESCRIPTION"],
            max_results=max_results,
            sort="FIRST_TO_START"
        )
        
        return [
            {
                "market_id": m.market_id,
                "market_name": m.market_name,
                "market_start_time": m.market_start_time.isoformat() if m.market_start_time else None,
                "total_matched": m.total_matched,
                "event": {
                    "id": m.event.id if m.event else None,
                    "name": m.event.name if m.event else None,
                },
                "competition": {
                    "id": m.competition.id if m.competition else None,
                    "name": m.competition.name if m.competition else None,
                },
                "runners": [
                    {
                        "selection_id": r.selection_id,
                        "runner_name": r.runner_name,
                        "sort_priority": r.sort_priority,
                    }
                    for r in (m.runners or [])
                ]
            }
            for m in markets
        ]
    
    def get_market_odds(self, market_ids: list[str]) -> list[dict]:
        """
        Get current odds for markets.
        
        Args:
            market_ids: List of market IDs
            
        Returns:
            List of market books with runner odds
        """
        self._ensure_logged_in()
        
        if not market_ids:
            return []
        
        books = self._trading.betting.list_market_book(
            market_ids=market_ids,
            price_projection={"priceData": ["EX_BEST_OFFERS"]}
        )
        
        results = []
        for book in books:
            market_data = {
                "market_id": book.market_id,
                "status": book.status,
                "total_matched": book.total_matched,
                "total_available": book.total_available,
                "runners": []
            }
            
            for runner in (book.runners or []):
                runner_data = {
                    "selection_id": runner.selection_id,
                    "status": runner.status,
                    "last_price_traded": runner.last_price_traded,
                    "total_matched": runner.total_matched,
                }
                
                # Best back (buy) prices
                if runner.ex and runner.ex.available_to_back:
                    runner_data["back"] = [
                        {"price": p.price, "size": p.size}
                        for p in runner.ex.available_to_back[:3]
                    ]
                else:
                    runner_data["back"] = []
                
                # Best lay (sell) prices
                if runner.ex and runner.ex.available_to_lay:
                    runner_data["lay"] = [
                        {"price": p.price, "size": p.size}
                        for p in runner.ex.available_to_lay[:3]
                    ]
                else:
                    runner_data["lay"] = []
                
                market_data["runners"].append(runner_data)
            
            results.append(market_data)
        
        return results
    
    # ========== Orders (Paper Trading Stubs) ==========
    
    def place_order(
        self,
        market_id: str,
        selection_id: int,
        side: str,  # "BACK" or "LAY"
        price: float,
        size: float,
        persist_type: str = "LAPSE"  # LAPSE, PERSIST, MARKET_ON_CLOSE
    ) -> dict:
        """
        Place an order (back or lay).
        
        Args:
            market_id: Market to bet on
            selection_id: Runner/selection to bet on
            side: "BACK" (bet for) or "LAY" (bet against)
            price: Odds (decimal, e.g., 2.5)
            size: Stake amount in GBP
            persist_type: What happens at in-play
            
        Returns:
            Order result dict
        """
        self._ensure_logged_in()
        
        # Build instruction
        instruction = {
            "selectionId": selection_id,
            "handicap": 0,
            "side": side,
            "orderType": "LIMIT",
            "limitOrder": {
                "size": size,
                "price": price,
                "persistenceType": persist_type
            }
        }
        
        result = self._trading.betting.place_orders(
            market_id=market_id,
            instructions=[instruction]
        )
        
        return {
            "status": result.status,
            "market_id": result.market_id,
            "instructions": [
                {
                    "status": ir.status,
                    "bet_id": ir.bet_id,
                    "placed_date": ir.placed_date.isoformat() if ir.placed_date else None,
                    "average_price_matched": ir.average_price_matched,
                    "size_matched": ir.size_matched,
                    "error_code": ir.error_code,
                }
                for ir in (result.instruction_reports or [])
            ]
        }
    
    def cancel_orders(
        self,
        market_id: Optional[str] = None,
        bet_ids: Optional[list[str]] = None
    ) -> dict:
        """
        Cancel orders.
        
        Args:
            market_id: Market to cancel orders in (cancels all if no bet_ids)
            bet_ids: Specific bet IDs to cancel
            
        Returns:
            Cancel result dict
        """
        self._ensure_logged_in()
        
        instructions = None
        if bet_ids:
            instructions = [{"betId": bid} for bid in bet_ids]
        
        result = self._trading.betting.cancel_orders(
            market_id=market_id,
            instructions=instructions
        )
        
        return {
            "status": result.status,
            "market_id": result.market_id,
            "cancelled": len(result.instruction_reports or [])
        }
    
    def list_current_orders(self) -> list[dict]:
        """
        Get all current (unmatched/partially matched) orders.
        
        Returns:
            List of order dicts
        """
        self._ensure_logged_in()
        
        orders = self._trading.betting.list_current_orders()
        
        return [
            {
                "bet_id": o.bet_id,
                "market_id": o.market_id,
                "selection_id": o.selection_id,
                "side": o.side,
                "price_size": {
                    "price": o.price_size.price if o.price_size else None,
                    "size": o.price_size.size if o.price_size else None,
                },
                "status": o.status,
                "size_matched": o.size_matched,
                "size_remaining": o.size_remaining,
                "placed_date": o.placed_date.isoformat() if o.placed_date else None,
            }
            for o in (orders.orders or [])
        ]
    
    def list_cleared_orders(
        self,
        days_back: int = 30
    ) -> list[dict]:
        """
        Get historical (settled) orders.
        
        Args:
            days_back: How many days of history
            
        Returns:
            List of settled order dicts
        """
        self._ensure_logged_in()
        
        orders = self._trading.betting.list_cleared_orders(
            bet_status="SETTLED",
            settled_date_range={
                "from": (datetime.utcnow() - timedelta(days=days_back)).isoformat(),
                "to": datetime.utcnow().isoformat()
            }
        )
        
        return [
            {
                "bet_id": o.bet_id,
                "market_id": o.market_id,
                "selection_id": o.selection_id,
                "side": o.side,
                "price_requested": o.price_requested,
                "price_matched": o.price_matched,
                "size_settled": o.size_settled,
                "profit": o.profit,
                "placed_date": o.placed_date.isoformat() if o.placed_date else None,
                "settled_date": o.settled_date.isoformat() if o.settled_date else None,
            }
            for o in (orders.orders or [])
        ]
    
    # ========== Account ==========
    
    def get_account_funds(self) -> dict:
        """
        Get account balance and exposure.
        
        Returns:
            Account funds dict
        """
        self._ensure_logged_in()
        
        funds = self._trading.account.get_account_funds()
        
        return {
            "available_to_bet": funds.available_to_bet_balance,
            "exposure": funds.exposure,
            "retained_commission": funds.retained_commission,
            "exposure_limit": funds.exposure_limit,
            "discount_rate": funds.discount_rate,
            "points_balance": funds.points_balance,
        }


def create_config_template():
    """Create a template config file."""
    config_path = Path("config/credentials.json")
    
    if config_path.exists():
        print(f"Config already exists: {config_path}")
        return
    
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    template = {
        "username": "YOUR_BETFAIR_USERNAME",
        "app_key": "YOUR_APP_KEY",
        "cert_path": "config/certs/client.crt",
        "key_path": "config/certs/client.key"
    }
    
    with open(config_path, "w") as f:
        json.dump(template, f, indent=2)
    
    print(f"Created config template: {config_path}")
    print("\nNext steps:")
    print("1. Get app key from https://developer.betfair.com/accounts/apps/")
    print("2. Generate certificates (for non-interactive auth)")
    print("3. Update config/credentials.json with your details")
    print("4. Add certificates to config/certs/")


def main():
    """CLI for testing the client."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Betfair API Client")
    parser.add_argument("command", choices=[
        "init", "sports", "events", "markets", "odds", "account"
    ])
    parser.add_argument("--sport", type=int, help="Sport ID")
    parser.add_argument("--event", help="Event ID")
    parser.add_argument("--market", help="Market ID")
    parser.add_argument("--days", type=int, default=7, help="Days ahead")
    parser.add_argument("--config", default="config/credentials.json")
    
    args = parser.parse_args()
    
    if args.command == "init":
        create_config_template()
        return
    
    # All other commands need a client
    try:
        client = BetfairClient.from_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nRun 'python betfair_client.py init' to create config template.")
        sys.exit(1)
    except Exception as e:
        print(f"Login failed: {e}")
        sys.exit(1)
    
    try:
        if args.command == "sports":
            sports = client.list_sports()
            print(json.dumps(sports, indent=2))
        
        elif args.command == "events":
            if not args.sport:
                print("--sport required for events command")
                sys.exit(1)
            events = client.list_events(args.sport, args.days)
            print(json.dumps(events, indent=2))
        
        elif args.command == "markets":
            markets = client.list_markets(
                sport_id=args.sport,
                event_id=args.event,
                days_ahead=args.days
            )
            print(json.dumps(markets, indent=2))
        
        elif args.command == "odds":
            if not args.market:
                print("--market required for odds command")
                sys.exit(1)
            odds = client.get_market_odds([args.market])
            print(json.dumps(odds, indent=2))
        
        elif args.command == "account":
            funds = client.get_account_funds()
            print(json.dumps(funds, indent=2))
    
    finally:
        client.logout()


if __name__ == "__main__":
    main()
