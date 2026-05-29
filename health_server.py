#!/usr/bin/env python3
"""
Betfair Trading API Server

Enhanced health server that provides portfolio status, positions, 
signals, and configuration. Runs a background trading scheduler.
"""

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Standard library imports only as per constraints
import sqlite3

# Local project imports
from config import Config
import paper_trader
from signal_engine import SignalEngine

class TradingAPIHandler(BaseHTTPRequestHandler):
    """API handler for Betfair Automation."""

    def _send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        
        response = {
            "status": "ok" if status_code == 200 else "error",
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        self.wfile.write(json.dumps(response).encode())

    def do_GET(self):
        # 1. Health Endpoint
        if self.path == "/health":
            data = {
                "status": "healthy",
                "version": "2.0.0",
                "mode": "paper_trading",
                "credentials_configured": bool(os.getenv("BETFAIR_APP_KEY")),
            }
            return self._send_json(data)

        # 2. Status Endpoint
        elif self.path == "/status":
            conn = paper_trader.init_db()
            try:
                balance = paper_trader.get_balance(conn)
                open_pos = paper_trader.get_open_positions(conn)
                realized = paper_trader.get_realized_pnl(conn)
                data = {
                    "balance": balance,
                    "initial_balance": Config().initial_balance,
                    "positions_count": len(open_pos),
                    "realized_pnl": realized
                }
                return self._send_json(data)
            finally:
                conn.close()

        # 3. Positions Endpoint
        elif self.path == "/positions":
            conn = paper_trader.init_db()
            try:
                positions = paper_trader.get_open_positions(conn)
                return self._send_json(positions)
            finally:
                conn.close()

        # 4. Signals Endpoint
        elif self.path == "/signals":
            # Run SignalEngine demo mock data
            engine = SignalEngine()
            # We simulate a market for the demo as seen in signal_engine.demo()
            mock_market = {
                "marketId": "1.234567890",
                "eventName": "API Demo: Market A vs B",
                "runners": [
                    {
                        "selectionId": 12345,
                        "runnerName": "Selection A",
                        "ex": {"availableToBack": [{"price": 2.20, "size": 500}]}
                    }
                ],
                "fair_odds": {12345: 2.05}
            }
            signals = engine.generate_signals([mock_market])
            data = [s.to_dict() for s in signals]
            return self._send_json(data)

        # 5. Config Endpoint
        elif self.path == "/config":
            return self._send_json(Config().to_dict())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def trading_scheduler():
    """Background thread for periodic trading cycles."""
    interval_min = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
    cfg = Config()
    
    print(f"🕒 Trading scheduler started (Interval: {interval_min}m)")
    
    while True:
        try:
            now = datetime.utcnow().isoformat()
            print(f"[{now}] 🔍 Starting trading cycle...")

            conn = paper_trader.init_db()
            
            # 1. Check credentials
            app_key = os.getenv("BETFAIR_APP_KEY")
            app_secret = os.getenv("BETFAIR_APP_SECRET")
            
            if not app_key or not app_secret:
                print(f"[{now}] ⚠️ Demo mode: no live credentials configured. Skipping live scan.")
            else:
                # Lazy import to prevent startup failure
                try:
                    import betfair_client
                    print(f"[{now}] 🚀 Connecting to Betfair for live signals...")
                    # Minimal implementation of the cycle
                    # 1. Fetch markets -> 2. Generate signals -> 3. Place paper trades
                    # Note: We assume betfair_client provides the glue
                    client = betfair_client.BetfairClient()
                    markets = client.get_markets(cfg.tracked_sports)
                    
                    engine = SignalEngine()
                    signals = engine.generate_signals(markets)
                    
                    for sig in signals:
                        paper_trader.place_bet(
                            conn, 
                            sig.market_id, sig.selection_id, sig.event_name, 
                            sig.selection_name, sig.bet_type.value, sig.odds, 
                            cfg.default_stake
                        )
                except Exception as e:
                    print(f"[{now}] ❌ Error during live trading cycle: {e}")

            # 2. Auto-settle positions
            if cfg.auto_settle_enabled:
                hours_limit = cfg.get("settlement_check_hours", 24)
                positions = paper_trader.get_open_positions(conn)
                for pos in positions:
                    opened_at = datetime.fromisoformat(pos["opened_at"])
                    if datetime.utcnow() - opened_at > timedelta(hours=hours_limit):
                        print(f"[{now}] ⏳ Auto-settling expired position {pos['id']} (Lost)")
                        # Simple auto-settle as Lost for expired positions that weren't updated
                        paper_trader.settle_position(conn, pos["id"], won=False)
            
            conn.close()
            print(f"[{now}] ✅ Trading cycle complete. Sleeping for {interval_min}m.")
            
        except Exception as e:
            print(f"❌ Scheduler error: {e}")
        
        time.sleep(interval_min * 60)

def main():
    port = int(os.getenv("HEALTH_PORT", "8000"))
    
    # Start the background scheduler
    scheduler_thread = threading.Thread(target=trading_scheduler, daemon=True)
    scheduler_thread.start()

    server = HTTPServer(("0.0.0.0", port), TradingAPIHandler)

    def handle_signal(signum, frame):
        print(f"Received signal {signum}, shutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print(f"🚀 Trading API listening on :{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
