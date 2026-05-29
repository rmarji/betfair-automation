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

def _run_live_cycle(conn, cfg, now):
    """Execute a live trading cycle with Betfair credentials."""
    import betfair_client

    app_key = os.getenv("BETFAIR_APP_KEY")
    username = os.getenv("BETFAIR_USERNAME")
    cert_dir = os.getenv("BETFAIR_CERTS_PATH", "/app/certs")

    # Resolve certificate paths
    cert_path = os.path.join(cert_dir, "client-2048.crt")
    key_path = os.path.join(cert_dir, "client-2048.key")

    if not app_key or not username:
        print(f"[{now}] ⚠️ Demo mode: BETFAIR_USERNAME or BETFAIR_APP_KEY not set.")
        return

    # Try cert-based auth first, fall back to interactive login
    client = None
    if os.path.exists(cert_path) and os.path.exists(key_path):
        print(f"[{now}] 🔐 Cert-based auth detected")
        try:
            client = betfair_client.BetfairClient.from_certs(
                username=username,
                app_key=app_key,
                cert_path=cert_path,
                key_path=key_path,
            )
        except Exception as e:
            print(f"[{now}] ⚠️ Cert auth failed: {e}, trying interactive login...")
            client = None

    if client is None:
        password = os.getenv("BETFAIR_PASSWORD")
        if not password:
            print(f"[{now}] ❌ No cert files and BETFAIR_PASSWORD not set. Cannot authenticate.")
            return
        try:
            client = betfair_client.BetfairClient.interactive(
                username=username,
                password=password,
                app_key=app_key,
            )
        except Exception as e:
            print(f"[{now}] ❌ Interactive login failed: {e}")
            return

    try:
        print(f"[{now}] 🚀 Connected to Betfair. Scanning markets...")

        # Map tracked sport names to Betfair sport IDs
        sport_id_map = betfair_client.SPORT_IDS
        all_markets = []

        for sport_name in cfg.tracked_sports:
            sport_id = sport_id_map.get(sport_name)
            if not sport_id:
                print(f"[{now}] ⚠️ Unknown sport: {sport_name}, skipping")
                continue

            try:
                markets = client.list_markets(sport_id=sport_id, max_results=50)
                all_markets.extend(markets)
            except Exception as e:
                print(f"[{now}] ⚠️ Error fetching {sport_name}: {e}")

        if not all_markets:
            print(f"[{now}] 📭 No markets found across tracked sports")
            return

        # Fetch odds for discovered markets (batch of 5 to stay within API limits)
        market_ids = [m["market_id"] for m in all_markets]
        odds_data = {}
        for i in range(0, len(market_ids), 5):
            batch = market_ids[i:i+5]
            try:
                books = client.get_market_odds(batch)
                for book in books:
                    odds_data[book["market_id"]] = book
            except Exception as e:
                print(f"[{now}] ⚠️ Odds batch error: {e}")

        # Enrich markets with odds data and run signal engine
        enriched = []
        for m in all_markets:
            mid = m["market_id"]
            if mid in odds_data:
                # Merge market catalogue + book data for signal engine
                runners = []
                for r in m.get("runners", []):
                    # Find matching runner in odds data
                    book_runners = [br for br in odds_data[mid].get("runners", [])
                                    if br["selection_id"] == r["selection_id"]]
                    if book_runners:
                        br = book_runners[0]
                        r["ex"] = {
                            "availableToBack": br.get("back", []),
                            "availableToLay": br.get("lay", []),
                        }
                    runners.append(r)
                m["runners"] = runners
            enriched.append(m)

        engine = SignalEngine()
        signals = engine.generate_signals(enriched)

        print(f"[{now}] 📊 Found {len(signals)} signals from {len(enriched)} markets")

        # Place paper bets for qualifying signals (Kelly Criterion sizing)
        balance = paper_trader.get_balance(conn)
        open_pos = paper_trader.get_open_positions(conn)
        placed = 0
        for sig in signals:
            if len(open_pos) >= cfg.max_positions:
                print(f"[{now}] ⛔ Max positions ({cfg.max_positions}) reached, skipping remaining signals")
                break

            # Kelly stake: f* = (b*p - q) / b where b=odds-1, p=confidence, q=1-p
            b = sig.odds - 1  # net odds
            p = sig.confidence
            q = 1 - p
            kelly_frac = (b * p - q) / b if b > 0 else 0
            kelly_frac = max(0, min(kelly_frac, cfg.max_stake_pct))  # Cap at max_stake_pct
            stake = round(balance * kelly_frac, 2)

            # Fall back to default stake if Kelly is too small
            if stake < 1.0:
                stake = min(cfg.default_stake, balance * cfg.max_stake_pct)
            stake = round(stake, 2)

            if stake < 1.0:
                continue
            pid = paper_trader.place_bet(
                conn,
                sig.market_id, sig.selection_id, sig.event_name,
                sig.selection_name, sig.bet_type.value, sig.odds,
                stake,
            )
            if pid:
                placed += 1
                open_pos.append({"id": pid})  # Track locally for max check

        print(f"[{now}] ✅ Placed {placed} paper trades from {len(signals)} signals")

    finally:
        if client:
            client.logout()


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

            # 1. Check credentials — run live cycle if available
            app_key = os.getenv("BETFAIR_APP_KEY")
            if app_key:
                try:
                    _run_live_cycle(conn, cfg, now)
                except Exception as e:
                    print(f"[{now}] ❌ Live cycle error: {e}")
            else:
                print(f"[{now}] ⚠️ Demo mode: no BETFAIR_APP_KEY. Skipping live scan.")

            # 2. Auto-settle positions
            if cfg.auto_settle_enabled:
                hours_limit = cfg.get("settlement_check_hours", 24)
                positions = paper_trader.get_open_positions(conn)
                for pos in positions:
                    opened_at = datetime.fromisoformat(pos["opened_at"])
                    if datetime.utcnow() - opened_at > timedelta(hours=hours_limit):
                        print(f"[{now}] ⏳ Auto-settling expired position {pos['id']} (Lost)")
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
