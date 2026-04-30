# Betfair Automation

Automated betting system using Betfair Exchange API for sports markets.

## Status: 🔴 SPEC → 🟠 BUILD

Spec complete, scaffolding in progress.

## Features

- Certificate-based auth (recommended) or interactive login
- Market discovery (sports, events, markets)
- Odds retrieval with back/lay prices
- Order management (place, cancel, list)
- Account funds monitoring

## Setup

### 1. Install Dependencies

```bash
pip install betfairlightweight
```

### 2. Get API Credentials

1. Create account at [Betfair](https://www.betfair.com/)
2. Apply for API access at [Developer Portal](https://developer.betfair.com/accounts/apps/)
3. Get your app key (free tier available)
4. Generate SSL certificates for non-interactive auth

### 3. Configure

```bash
# Create config template
python betfair_client.py init

# Edit config/credentials.json with your details
# Add certificates to config/certs/
```

### 4. Test

```bash
# List available sports
python betfair_client.py sports

# List NHL events
python betfair_client.py events --sport 7524

# List NHL markets
python betfair_client.py markets --sport 7524 --days 3
```

## Sport IDs

| Sport | ID |
|-------|-----|
| Soccer | 1 |
| Tennis | 2 |
| Horse Racing | 7 |
| NFL | 6423 |
| NBA | 7522 |
| NHL | 7524 |

## Architecture

```
betfair-automation/
├── betfair_client.py    # API wrapper
├── signal_engine.py     # Betting signals (TODO)
├── paper_trader.py      # Paper trading (TODO)
├── config/
│   ├── credentials.json # API keys (gitignored)
│   └── certs/           # SSL certificates (gitignored)
└── betfair.db           # Trade history (TODO)
```

## Next Steps

- [ ] Get Betfair account + API key
- [ ] Add SSL certificates
- [ ] Test market listing
- [ ] Scaffold signal engine
- [ ] Implement paper trading

## Spec

See `specs/betfair-automation.md` for full spec.
