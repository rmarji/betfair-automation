# Betfair Automation — Deployment Guide

## Prerequisites

- Docker & Docker Compose
- Betfair Exchange account with API access
- SSL certificates from Betfair

## Getting Betfair API Access

1. Register at https://www.betfair.com
2. Apply for API-NG access: https://docs.developer.betfair.com/
3. Generate SSL certificates (self-signed for non-interactive login)
4. Get your Application Key from the Betfair Developer dashboard

## Quick Start (Demo Mode)

```bash
# Clone and run without credentials (demo/paper trading only)
cd betfair-automation
python3 betfair_cli.py status    # Portfolio status
python3 betfair_cli.py markets --demo  # Sample markets
python3 betfair_cli.py health    # System health
```

## Docker Deployment

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your Betfair credentials

# 2. Place SSL certs
mkdir -p certs/
# Copy your Betfair certs to certs/

# 3. Build and run
docker-compose up -d

# 4. Check status
docker-compose exec betfair-trader python3 betfair_cli.py status
```

## Coolify Deployment

1. Push repo to GitHub (clawgeeks org)
2. In Coolify: New Resource → Docker Compose
3. Set environment variables:
   - `BETFAIR_USERNAME`
   - `BETFAIR_PASSWORD`
   - `BETFAIR_APP_KEY`
4. Mount certs volume
5. Deploy

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BETFAIR_USERNAME` | Yes (live) | Betfair account username |
| `BETFAIR_PASSWORD` | Yes (live) | Betfair account password |
| `BETFAIR_APP_KEY` | Yes (live) | Betfair API application key |
| `BETFAIR_CERTS_PATH` | No | Path to SSL certs (default: /app/certs) |

## CLI Reference

```bash
betfair_cli.py status     # Portfolio overview
betfair_cli.py run        # Execute trading cycle
betfair_cli.py history    # Trade history
betfair_cli.py signals    # Current signals
betfair_cli.py markets    # Available markets (--demo, --sport, --limit)
betfair_cli.py stats      # Trading statistics
betfair_cli.py config     # View/modify configuration
betfair_cli.py health     # System health check
betfair_cli.py reset      # Reset portfolio
```

## Architecture

```
betfair_client.py  → Betfair API client (auth + market data)
signal_engine.py   → 3 strategies: Value, Momentum, Arbitrage
paper_trader.py    → Paper trading with SQLite persistence
config.py          → Configurable parameters
betfair_cli.py     → Unified CLI interface
```

## Supported Sports

| Sport | Betfair ID | Notes |
|-------|-----------|-------|
| NHL | 7524 | Hockey |
| NBA | 7522 | Basketball |
| NFL | 6423 | American Football |
| Soccer | 1 | Global coverage |
| Tennis | 2 | Grand Slams + ATP/WTA |
| Horse Racing | 7 | UK/IRE/AUS |
