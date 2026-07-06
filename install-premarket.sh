#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# AI Premarket Analyst — Claude + Codex Skill Installer
# Two-brain premarket analysis: Claude + OpenAI Codex
# Based on Humbled Trader's free AI premarket analyst build
# ============================================================

CLAUDE_DIR="${HOME}/.claude"
SKILLS_DIR="${CLAUDE_DIR}/skills"
BIN_DIR="${CLAUDE_DIR}/bin"
INSTALL_DIR="${SKILLS_DIR}/premarket"
DATA_DIR="${HOME}/.premarket"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error()   { echo -e "${RED}✗ $1${NC}"; }
print_info()    { echo -e "${BLUE}→ $1${NC}"; }

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   AI Premarket Analyst Installer          ║${NC}"
echo -e "${BLUE}║   Claude + Codex two-brain morning report ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# ---- Locate source dir ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || SCRIPT_DIR=""
if [ -z "$SCRIPT_DIR" ] || [ ! -f "$SCRIPT_DIR/premarket/SKILL.md" ]; then
    print_error "Run this from the repo root (premarket/SKILL.md not found)."
    exit 1
fi
SOURCE_DIR="$SCRIPT_DIR/premarket"

# ---- Prerequisites ----
print_info "Checking prerequisites..."

PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
fi
if [ -z "$PYTHON_CMD" ]; then
    print_error "Python 3.8+ is required. Install: https://www.python.org/downloads/"
    exit 1
fi
print_success "Python found: $($PYTHON_CMD --version)"

if command -v claude &>/dev/null; then
    print_success "Claude Code CLI found"
else
    print_warning "Claude Code CLI not found in PATH (install: npm install -g @anthropic-ai/claude-code)"
fi

if command -v codex &>/dev/null; then
    print_success "OpenAI Codex CLI found (second brain ready)"
else
    print_warning "OpenAI Codex CLI not found — the second brain will be offline."
    echo "    One-time setup:  npm install -g @openai/codex"
    echo "    Then log in:     codex login   (uses your ChatGPT plan)"
    echo "    The skill still works single-brain until then."
fi

# ---- Install files ----
print_info "Installing skill files..."

mkdir -p "$INSTALL_DIR/scripts" "$BIN_DIR" "$DATA_DIR/reports"
cp "$SOURCE_DIR/SKILL.md" "$INSTALL_DIR/"
cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/"
cp "$SOURCE_DIR/scripts/"*.py "$INSTALL_DIR/scripts/"
chmod +x "$INSTALL_DIR/scripts/"*.py 2>/dev/null || true
print_success "Skill installed → ${INSTALL_DIR}/"

# WATCHLIST_CRITERIA.md is the user's source of truth — never clobber an
# existing (possibly customized) copy.
if [ -f "$INSTALL_DIR/WATCHLIST_CRITERIA.md" ]; then
    print_warning "Existing WATCHLIST_CRITERIA.md kept (your rules were not overwritten)."
else
    cp "$SOURCE_DIR/WATCHLIST_CRITERIA.md" "$INSTALL_DIR/"
    print_success "WATCHLIST_CRITERIA.md installed (edit it to encode your backtested rules)"
fi

cp "$SOURCE_DIR/scripts/codex-ask.sh" "$BIN_DIR/codex-ask.sh"
chmod +x "$BIN_DIR/codex-ask.sh"
print_success "Codex bridge installed → ${BIN_DIR}/codex-ask.sh"

# ---- Python deps ----
print_info "Installing Python dependencies (yfinance, feedparser, markdown, requests)..."
if $PYTHON_CMD -m pip install --user -r "$SOURCE_DIR/requirements.txt" --quiet 2>/dev/null; then
    print_success "Python dependencies installed"
# Some Debian/Ubuntu setups fail building feedparser's legacy sgmllib3k dep
# (setuptools 'install_layout' error) — retry with stdlib distutils.
elif SETUPTOOLS_USE_DISTUTILS=stdlib $PYTHON_CMD -m pip install --user -r "$SOURCE_DIR/requirements.txt" --quiet 2>/dev/null; then
    print_success "Python dependencies installed (stdlib distutils fallback)"
else
    print_warning "pip install failed — run manually: $PYTHON_CMD -m pip install --user -r premarket/requirements.txt"
fi

# ---- Summary ----
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        Installation Complete!             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Reminder: this script COPIES files into place. A future 'git pull' only${NC}"
echo -e "${YELLOW}updates this repo folder — re-run ./install-premarket.sh after every pull${NC}"
echo -e "${YELLOW}to sync fixes into the skill Claude Code actually runs.${NC}"
echo ""
echo "  Skill:        ${INSTALL_DIR}"
echo "  Codex bridge: ${BIN_DIR}/codex-ask.sh"
echo "  Reports:      ${DATA_DIR}/reports/"
echo ""
echo -e "${BLUE}Quick Start (in Claude Code):${NC}"
echo "    /premarket            Full two-brain run, report saved locally"
echo "    /premarket scan       Data only (gappers + snapshot)"
echo "    /premarket email      Full run + email via Resend"
echo "    /premarket schedule   Daily 6am auto-run (launchd/cron)"
echo ""
echo -e "${BLUE}Email setup (optional, for /premarket email):${NC}"
echo "    export RESEND_API_KEY=re_...            # free at resend.com"
echo "    export PREMARKET_EMAIL_FROM='Premarket <onboarding@resend.dev>'"
echo "    export PREMARKET_EMAIL_TO=you@example.com"
echo "    export DISCORD_WEBHOOK_URL=...           # optional"
echo ""
echo -e "${BLUE}Second brain (optional but recommended):${NC}"
echo "    npm install -g @openai/codex && codex login"
echo ""
echo "  Disclaimer: educational information only — not financial advice."
echo ""
