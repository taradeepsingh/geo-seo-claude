#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# codex-ask.sh — the "second brain" bridge
#
# Sends a prompt to OpenAI's Codex CLI in its own separate
# process and prints back an answer Claude had no part in
# writing. Claude runs this via Bash to get a genuinely
# independent second opinion on the same market data.
#
# Usage:
#   codex-ask.sh "your prompt here"
#   echo "your prompt" | codex-ask.sh
#   codex-ask.sh < prompt.txt
#
# The wrapper can be swapped for any CLI that takes a prompt
# on stdin and returns text (e.g. gemini, another claude).
#
# One-time setup:
#   npm install -g @openai/codex
#   codex login        # sign in with your ChatGPT plan
# ============================================================

if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: 'codex' command not found." >&2
    echo "Install it with:  npm install -g @openai/codex" >&2
    echo "Then log in with: codex login" >&2
    exit 127
fi

if [ $# -gt 0 ]; then
    PROMPT="$1"
else
    PROMPT="$(cat)"
fi

if [ -z "${PROMPT// /}" ]; then
    echo "ERROR: empty prompt. Pass it as the first argument or on stdin." >&2
    exit 2
fi

# --skip-git-repo-check : allow running outside a git repo
# --sandbox read-only   : Codex only reads and answers; it must not
#                         touch files or the network on its own
codex exec --skip-git-repo-check --sandbox read-only "$PROMPT" 2>/dev/null
