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
#
# A single codex exec call normally returns in well under a minute. If it
# doesn't, it's usually a dropped/expired login session hanging on a network
# call rather than working slowly, so this wrapper kills it after
# CODEX_TIMEOUT_SECONDS (default 120) instead of hanging the whole skill.
# Override with: CODEX_TIMEOUT_SECONDS=180 codex-ask.sh "..."
# ============================================================

CODEX_TIMEOUT_SECONDS="${CODEX_TIMEOUT_SECONDS:-120}"

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

STDERR_FILE="$(mktemp)"
trap 'rm -f "$STDERR_FILE"' EXIT

# --skip-git-repo-check : allow running outside a git repo
# --sandbox read-only   : Codex only reads and answers; it must not
#                         touch files or the network on its own
codex exec --skip-git-repo-check --sandbox read-only "$PROMPT" 2>"$STDERR_FILE" &
codex_pid=$!
( sleep "$CODEX_TIMEOUT_SECONDS" && kill -TERM "$codex_pid" 2>/dev/null ) &
watchdog_pid=$!

status=0
wait "$codex_pid" 2>/dev/null || status=$?

kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true

if [ "$status" -ne 0 ]; then
    if [ "$status" -eq 143 ] || [ "$status" -eq 137 ]; then
        echo "ERROR: codex exec did not respond within ${CODEX_TIMEOUT_SECONDS}s — killed it." >&2
        echo "Most likely cause: the 'codex login' session expired or dropped." >&2
        echo "Fix: run 'codex login' again, then retry." >&2
    else
        echo "ERROR: codex exec failed (exit $status)." >&2
        cat "$STDERR_FILE" >&2
    fi
    exit "$status"
fi
