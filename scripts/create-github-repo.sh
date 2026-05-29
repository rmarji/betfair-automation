#!/bin/bash
# GitHub Repo Setup Helper for Betfair Automation
# Run this after creating the repo on GitHub

set -e

REPO_NAME="betfair-automation"
GITHUB_ORG="clawgeeks"

echo "🔧 Betfair Automation - GitHub Setup"
echo "===================================="

# Check if remote already exists
if git remote | grep -q origin; then
    echo "Remote 'origin' already exists"
    git remote -v
else
    echo "Adding GitHub remote..."
    git remote add origin "https://github.com/${GITHUB_ORG}/${REPO_NAME}.git"
    echo "✅ Remote added"
fi

echo ""
echo "📤 Pushing to GitHub..."
echo "You may need to authenticate. Options:"
echo "  1. Use GitHub CLI (gh auth login)"
echo "  2. Use HTTPS with personal access token"
echo "  3. Add PAT to Coolify for automatic access"

# Attempt push
if git push -u origin main; then
    echo "✅ Successfully pushed to GitHub!"
    echo ""
    echo "Next steps:"
    echo "  1. Go to https://claw.jogeeks.com"
    echo "  2. Create new project → GitHub → ${REPO_NAME}"
    echo "  3. Configure environment variables in Coolify:"
    echo "     - BETFAIR_APP_KEY"
    echo "     - BETFAIR_SESSION_TOKEN (or username/password)"
    echo "     - Optional: TELEGRAM_BOT_TOKEN for notifications"
else
    echo "❌ Push failed. Common causes:"
    echo "  - Repository doesn't exist on GitHub yet"
    echo "  - Need authentication credentials"
    echo "  - Branch naming (try 'master' instead of 'main')"
fi
