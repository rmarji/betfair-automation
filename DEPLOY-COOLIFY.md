# Deploying Betfair Automation to Coolify

A step-by-step guide for deploying the Betfair Automation trading bot on Coolify.

## Prerequisites

- Coolify instance running (self-hosted or cloud)
- Git repository with Betfair Automation code
- Betfair API credentials (or use demo mode)

---

## Step 1: Prepare Your Repository

### 1.1 Ensure Required Files Exist

Before deploying, verify these files exist in your repository:

```
betfair-automation/
├── Dockerfile              # Multi-stage production build
├── docker-compose.yml      # With resource limits
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── config.json            # Trading configuration
├── betfair_cli.py         # Main CLI entry point
├── signal_engine.py       # Signal generation
├── paper_trader.py        # Paper trading logic
└── scripts/
    └── validate-deployment.py  # Pre-deployment validation
```

### 1.2 Configure Environment Variables

Create a `.env` file (or configure in Coolify) with your Betfair credentials:

```bash
BETFAIR_USERNAME=your_username
BETFAIR_PASSWORD=your_password
BETFAIR_APP_KEY=your_app_key
```

**Security Note:** Never commit `.env` to version control. Use Coolify's environment variable feature instead.

### 1.3 Prepare SSL Certificates (Optional)

For live trading, place Betfair SSL certificates in `config/certs/`:

```bash
mkdir -p config/certs
cp /path/to/client.crt config/certs/client.crt
cp /path/to/client.key config/certs/client.key
```

---

## Step 2: Connect Repository to Coolify

### 2.1 Add New Application

1. Log into Coolify dashboard
2. Click **Add New Resource** → **Application**
3. Select **Import from Git Repository**

### 2.2 Configure Repository

| Setting | Value |
|---------|-------|
| Repository URL | `https://github.com/your-org/betfair-automation.git` |
| Branch | `main` (or your deployment branch) |
| Build Type | `Dockerfile` |

### 2.3 Configure Build Settings

```
Dockerfile Path: ./Dockerfile
Context Path: ./
```

---

## Step 3: Configure Application Settings

### 3.1 General Settings

| Setting | Value |
|---------|-------|
| Application Name | `betfair-trader` |
| Instance Type | `256MB RAM minimum` (512MB recommended) |
| Number of Instances | `1` |

### 3.2 Resource Limits

The `docker-compose.yml` includes these limits, but you can also set in Coolify:

```yaml
# Limits (already configured in docker-compose.yml)
cpus: '0.5'      # 0.5 CPU cores
memory: 512M     # 512 MB RAM
```

### 3.3 Health Check

Coolify will automatically use the `HEALTHCHECK` defined in Dockerfile:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python3 -c "import betfair_cli, signal_engine, paper_trader; print('OK')" || exit 1
```

---

## Step 4: Configure Environment Variables

### 4.1 Required Variables

In Coolify → Application → Environment Variables, add:

```bash
# Betfair API Credentials (from .env)
BETFAIR_USERNAME=your_username
BETFAIR_PASSWORD=your_password
BETFAIR_APP_KEY=your_app_key

# Python Settings
PYTHONDONTWRITEBYTECODE=1
PYTHONUNBUFFERED=1
PYTHONPATH=/app

# Paths
BETFAIR_CERTS_PATH=/app/certs
```

### 4.2 Optional Variables

```bash
# Trading Configuration (can override config.json)
# INITIAL_BALANCE=1000.0
# MAX_POSITIONS=5
# DEFAULT_STAKE=10.0
```

---

## Step 5: Configure Persistent Storage

### 5.1 Required Volumes

The application requires persistent volumes for:

| Volume | Host Path | Container Path | Purpose |
|--------|----------|----------------|---------|
| Data | `/data/betfair-data` | `/app/data` | SQLite database, logs |
| Certs | `/data/betfair-certs` | `/app/certs` | SSL certificates (read-only) |
| Config | `/data/betfair-config/config.json` | `/app/config.json` | Trading config (read-only) |

### 5.2 Configure in Coolify

1. Go to Application → **Persistent Storage**
2. Add each volume:

```
/data/betfair-data:/app/data
/data/betfair-certs:/app/certs:ro
/data/betfair-config/config.json:/app/config.json:ro
```

---

## Step 6: Configure Logging

### 6.1 Log Settings (Coolify)

```
Log Driver: json-file
Log Options:
  max-size: 10m
  max-file: "3"
```

### 6.2 Application Logs

View logs in Coolify console:

```bash
# Via Coolify Console
docker logs betfair-trader

# Real-time logs
docker logs -f betfair-trader
```

---

## Step 7: Deployment Commands

### 7.1 Pre-deployment Validation

Run before deploying to catch issues early:

```bash
# Local validation (optional)
python scripts/validate-deployment.py
```

### 7.2 Deploy Command

The Dockerfile handles everything. No custom commands needed.

Default command in `docker-compose.yml`:
```bash
python3 betfair_cli.py run
```

### 7.3 Alternative Commands

You can override the command in Coolify:

```bash
# Status check only
python3 betfair_cli.py status

# Health check
python3 betfair_cli.py health

# Show trading history
python3 betfair_cli.py history
```

---

## Step 8: Post-Deployment Verification

### 8.1 Check Container Status

In Coolify dashboard, verify:
- ✅ Container status: **Running**
- ✅ Health check: **Healthy**
- ✅ Logs: No errors

### 8.2 Verify Deployment

SSH into Coolify host and run:

```bash
# Check container
docker ps | grep betfair

# Check health
docker inspect betfair-trader --format='{{.State.Health.Status}}'

# View logs
docker logs betfair-trader --tail 50
```

### 8.3 Test Connection

```bash
# Exec into container
docker exec -it betfair-trader bash

# Run health check
python3 betfair_cli.py health

# Check status
python3 betfair_cli.py status
```

---

## Step 9: Monitoring & Alerts

### 9.1 Health Check Alerts

Configure in Coolify:
- Alert if health check fails 3 times
- Alert if container restarts

### 9.2 Log Monitoring

Set up alerts for:
- `ERROR` or `Exception` in logs
- Container restart events
- Out of memory (OOM) events

### 9.3 Resource Monitoring

Watch for:
- Memory usage approaching 512MB limit
- High CPU usage (>80%)

---

## Step 10: Maintenance

### 10.1 Updating the Application

1. Push changes to Git repository
2. Coolify auto-deploys on push (if webhook configured)
3. Or manually trigger **Deploy** in dashboard

### 10.2 Backup

Back up these directories regularly:
- `/data/betfair-data/` - Database and trade history
- `/data/betfair-certs/` - SSL certificates

### 10.3 Restart Commands

```bash
# Via Docker
docker restart betfair-trader

# Via Coolify Console
restart betfair-trader
```

---

## Troubleshooting

### Container Won't Start

1. Check logs: `docker logs betfair-trader`
2. Verify environment variables set correctly
3. Ensure volumes mounted properly
4. Run validation script: `python scripts/validate-deployment.py`

### Health Check Failing

1. Check Python imports: `docker exec betfair-trader python3 -c "import betfair_cli"`
2. Verify all dependencies installed
3. Check startup command completes

### Out of Memory

1. Increase memory limit in docker-compose.yml
2. Or reduce in Coolify resource settings
3. Monitor memory usage: `docker stats betfair-trader`

### Can't Connect to Betfair API

1. Verify credentials in environment variables
2. Check SSL certificates mounted correctly
3. Test network connectivity from container

---

## Quick Reference

### Coolify Settings Summary

| Setting | Value |
|---------|-------|
| Instance | 512MB RAM |
| CPU | 0.5 cores |
| Restart Policy | Unless Stopped |
| Health Check | Built-in (30s interval) |
| Log Max Size | 10MB (3 files) |

### Important Paths

| Path | Purpose |
|------|---------|
| `/app` | Application root |
| `/app/data` | Persistent SQLite DB |
| `/app/certs` | SSL certificates |
| `/app/config.json` | Trading config |

### Useful Commands

```bash
# View deployment logs
docker logs betfair-trader

# Check health status
docker inspect betfair-trader --format='{{.State.Health.Status}}'

# Access container shell
docker exec -it betfair-trader /bin/bash

# Run health check manually
docker exec betfair-trader python3 betfair_cli.py health

# View resource usage
docker stats betfair-trader
```

---

## Security Best Practices

1. **Never commit secrets** - Use Coolify environment variables
2. **Read-only volumes** - Certs and config mounted read-only
3. **Non-root user** - Container runs as `betfair` user (UID 10001)
4. **No new privileges** - `no-new-privileges:true` set in compose
5. **Resource limits** - Prevents resource exhaustion attacks