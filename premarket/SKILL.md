---
name: premarket
description: >
  Free AI premarket stock analyst with a two-brain design (Claude + OpenAI
  Codex as rival analysts). Scans premarket movers with keyless yfinance,
  finds catalysts from free RSS news, applies backtested watchlist rules,
  gets an independent second opinion from Codex via codex-ask.sh, and emails
  a clean morning report. Use when the user says "premarket", "pre-market",
  "morning report", "gappers", "watchlist", "market open prep", "two-brain",
  or asks for a daily trading report.
allowed-tools: Read, Grep, Glob, Bash, Write
---

# AI Premarket Analyst — Claude + Codex Two-Brain Skill

> Based on Humbled Trader's "How to Build a Free AI Premarket Analyst with
> Claude & Codex" (humbledtrader.com/blog/claude-codex-ai-premarket-analyst).
> Market data comes from keyless yfinance, news from free RSS, and the
> economic calendar from a free feed. Everything runs locally; only the report
> email (Resend) and optional Discord post leave the machine.

**Why two brains:** Claude can run shell commands, so it hands the exact same
data to OpenAI Codex in its own separate process (`codex-ask.sh`) and reads
back an answer it had no part in writing. Two different models means genuinely
independent analysis — when they agree it actually means something. The
wrapper can be swapped for any CLI that takes a prompt on stdin and returns
text.

---

## Quick Reference

| Command | What It Does |
|---------|-------------|
| `/premarket` | Full run: scan → two-brain analysis → report saved locally |
| `/premarket scan` | Data only: run the scanner, show gappers + snapshot, no analysis |
| `/premarket report` | Full run and print the report (no sending) |
| `/premarket email` | Full run, then email via Resend (and Discord if configured) |
| `/premarket schedule` | Set up the daily auto-run (launchd on macOS, cron on Linux) |

Paths used by this skill:

- Skill home: `~/.claude/skills/premarket/`
- Codex bridge: `~/.claude/bin/codex-ask.sh`
- Rules: `~/.claude/skills/premarket/WATCHLIST_CRITERIA.md` (source of truth)
- Output: `~/.premarket/reports/YYYY-MM-DD-premarket.md`
- Scratch: `~/.premarket/scan-YYYY-MM-DD.json`

---

## Workflow

### Phase 0 — Preflight

1. `mkdir -p ~/.premarket/reports`
2. Check the Codex bridge: `~/.claude/bin/codex-ask.sh "Reply with the single word: ready"`.
   - If you see `command not found: codex`, the Codex CLI is not installed or
     not on PATH. Tell the user to run `npm install -g @openai/codex` and then
     `codex login` (signs in with their ChatGPT plan), and continue in
     **single-brain mode**: produce the report anyway, mark every "Codex
     check" cell as `n/a (Codex offline)`, and cap conviction at 3.
3. Read `WATCHLIST_CRITERIA.md` from the skill directory. These rules are the
   source of truth — never loosen a rule to make a ticker qualify.

### Phase 1 — Scan (deterministic, no AI judgment)

Run the data engine:

```bash
python3 ~/.claude/skills/premarket/scripts/premarket_scan.py \
  --output ~/.premarket/scan-$(date +%F).json
```

It pulls 2-day bars for every S&P 500 ticker from Yahoo Finance, computes the
gap from yesterday's close, filters for gaps above 3% and volume above 50K,
and writes the top 20 to the watchlist, along with: a market snapshot
(futures, VIX, 10Y, dollar, gold, oil, BTC), per-gapper catalysts (yfinance
news + matching RSS headlines), and today/tomorrow US High-impact economic
events (cached ForexFactory feed).

Flags if the user wants a different net: `--min-gap`, `--min-volume` (20K for
a wider net, 100K+ for size), `--top`, `--universe path/to/tickers.txt`.

If the scan returns zero gappers, say so plainly and still produce the report
(snapshot + econ calendar + "no qualifying gappers today") — do not lower the
thresholds on your own.

### Phase 2 — Claude pass (first brain)

Analyze the scan JSON against `WATCHLIST_CRITERIA.md`:

1. For each gapper, check every selection rule for Setup 1 (Trend Join Long)
   and the swing setup. A ticker only makes a watchlist if ALL required rules
   pass. Rules the data can't verify (e.g. true premarket RVOL) are marked
   "unverified", never assumed true.
2. For each qualifying day-trade name, write: catalyst (one line), key levels
   (premarket high, yesterday high, yesterday close), and the plan from the
   criteria file (trigger, 1R stop, scaling, flat by 3:51pm ET).
3. For each swing name: catalyst, trend context, and the positional idea.
4. Draft your verdict on the overall tape (risk-on/risk-off/mixed) from the
   snapshot + econ calendar.
5. Assign a provisional conviction score (1–5) per the scale in the criteria
   file — final score waits for the Codex check.

### Phase 3 — Codex pass (second brain)

Build a rival prompt and run it through the bridge. Critical: the rival gets
the **same raw data**, the **same rules**, and **none of your conclusions** —
do not leak your picks, your verdict, or your scores into its prompt.

```bash
~/.claude/bin/codex-ask.sh "$(cat <<'EOF'
You are an independent premarket analyst. You are auditing raw scan data
against fixed rules. Be skeptical; your job is to catch bad picks.

RULES (source of truth, do not loosen):
<paste WATCHLIST_CRITERIA.md here>

RAW SCAN DATA (JSON):
<paste the scan JSON here — trim market_headlines to ~10 if needed for size>

Answer with:
1. TAPE: one-line read of the overall tape (risk-on / risk-off / mixed) and why.
2. DAY TRADES: tickers that fully qualify for Setup 1, each with a one-line
   reason. List near-misses separately with the rule they fail.
3. SWING: tickers that fit the swing template, one line each.
4. RED FLAGS: any ticker in the data you would refuse to trade and why
   (dilution risk, stale catalyst, illiquidity, fake gap, etc.).
5. CONVICTION: for each qualifying ticker, a 1-5 score per the scale in the rules.
EOF
)"
```

If the bridge errors or times out, fall back to single-brain mode as in
Phase 0 and note it in the report.

### Phase 4 — Compare and settle conviction

- **Agree** (same ticker, same direction, same setup): conviction = min of the
  two scores, +1 if both scored ≥4 (cap 5). Codex check cell: `✅ agrees — <its one-line reason>`.
- **Partial** (same ticker, different read on quality): conviction = lower of
  the two. Codex check: `⚠️ <its objection>`.
- **Disagree** (Codex rejects the pick or flags a red flag): conviction capped
  at 2, disagreement shown verbatim in the Codex check cell. Never silently
  drop or overrule the objection.
- Tickers only Codex picked: list them in the report body under the relevant
  watchlist as "Codex-only pick" with your counter-reasoning — do not adopt
  them as your own.
- The two-brain verdict on the tape: if the brains disagree, the summary says
  so explicitly ("Claude: risk-on / Codex: mixed — trade smaller").

### Phase 5 — Render the report

Write `~/.premarket/reports/YYYY-MM-DD-premarket.md` with EXACTLY these
sections in this order:

1. **Title + dated subtitle** — `# Premarket Report` /
   `### <Weekday, Month D, YYYY> — Claude + Codex, two independent passes`
2. **Disclaimer** (one line): `> Educational information only — not financial
   advice. Two AIs reading free data can both be wrong. The trade is yours.`
3. **Summary of the Tape** — 3-5 sentences + the two-brain verdict line.
4. **Pre-Market Gappers** — table: Rank | Ticker | Price | Gap % | Volume |
   RVOL* | Catalyst headline. Footnote: `*RVOL is a full-day stand-in
   (yfinance premarket volume limitation).`
5. **Day Trading Watchlist** — table: Ticker | Catalyst | Levels | Plan |
   Codex check | Conviction.
6. **Swing Watchlist** — table: Ticker | Catalyst | Trend context | Idea |
   Codex check | Conviction.
7. **Market Trends of the Day** — sector/theme reads from the snapshot and
   headlines (2-4 bullets).
8. **Technical Signals for Today** — SPY/QQQ levels that matter, VIX regime,
   anything at a decision point (2-4 bullets).
9. **Economic Data, Rates & the Fed** — econ_calendar.today (time ET + title +
   forecast vs previous) plus the 10Y/dollar read from the snapshot. Include
   the calendar staleness note if the scanner emitted one.
10. **Coming Up** — econ_calendar.tomorrow + notable earnings you saw in the
    headlines.

Keep it tight — the whole report should read in under 3 minutes. No filler,
no hedging paragraphs, no repeated disclaimers.

### Phase 6 — Deliver (only for `/premarket email` or if scheduled)

```bash
python3 ~/.claude/skills/premarket/scripts/send_report.py \
  --report ~/.premarket/reports/$(date +%F)-premarket.md \
  --discord   # only if DISCORD_WEBHOOK_URL is set
```

Requires env vars: `RESEND_API_KEY`, `PREMARKET_EMAIL_FROM`,
`PREMARKET_EMAIL_TO`, optional `DISCORD_WEBHOOK_URL`. If they're missing, show
the user exactly which ones and where to get them (resend.com free tier), and
leave the report on disk. Email, Discord, Slack, or SMS — the setup pattern is
the same: give Claude the credentials, tell it the format, it wires the rest.

---

## `/premarket schedule` — daily auto-run

Goal: the report is waiting before the user sits down, with a smart catch-up
layer so the run fires when the Mac wakes inside the valid window — better
than keeping the laptop awake all night.

**macOS (launchd + catch-up):** write
`~/Library/LaunchAgents/com.premarket.analyst.plist` running a small wrapper
script daily at 06:00 local, with `RunAtLoad` true. The wrapper is the
catch-up layer — it exits unless BOTH: (a) current ET time is within the valid
window (05:00–09:25 ET on a weekday), and (b) today's report doesn't already
exist at `~/.premarket/reports/$(date +%F)-premarket.md`. The wrapper then
runs: `claude -p "/premarket email" --dangerously-skip-permissions` (or the
user's preferred flags). Load with `launchctl load -w <plist>`.

**Linux / cloud:** cron instead —
`30 5 * * 1-5 <wrapper.sh>` (5:30am ET server time; same guard logic).

**Windows:** Task Scheduler, daily trigger + "run task as soon as possible
after a scheduled start is missed" as the catch-up, same wrapper guard.

Always show the user the plist/cron entry before installing it, and confirm
the schedule time in THEIR timezone vs ET.

---

## Guardrails

- Never invent a catalyst. If no headline explains the gap, say
  "no headline found — check chart/SEC filings".
- Never loosen a WATCHLIST_CRITERIA.md rule to fill an empty watchlist. An
  empty watchlist is a valid, honest output.
- Never leak the first brain's conclusions into the second brain's prompt.
- Codex disagreement is always shown, never smoothed over.
- This skill analyzes and reports. It never places, sizes, or suggests
  placing live orders.
