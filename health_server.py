#!/usr/bin/env python3
"""
Health Check Server

Simple HTTP server for container health checks.
Runs on port 8000 and responds to /health with system status.
Exits gracefully on SIGTERM.
"""

import json
import os
import signal
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal health check handler."""

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            status = {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "version": "1.0.0",
                "mode": "paper_trading",
                "credentials_configured": bool(os.getenv("BETFAIR_APP_KEY")),
            }

            self.wfile.write(json.dumps(status).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    port = int(os.getenv("HEALTH_PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    def handle_signal(signum, frame):
        print(f"Received signal {signum}, shutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print(f"🏥 Health server listening on :{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()