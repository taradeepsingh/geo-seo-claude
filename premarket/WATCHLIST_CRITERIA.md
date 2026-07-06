# WATCHLIST_CRITERIA.md — Source of Truth

This file captures the validated, backtested watchlist setups. **The rules pick
the watchlist, the two AIs judge quality, and the trader makes the trade.**
The scanner and both AI passes must treat this file as the source of truth —
neither AI is allowed to loosen a rule to make a ticker qualify.

Edit this file to encode your own backtested setups. Every setup needs:
selection rules (all required), an intraday/positional plan, and the backtest
stats that earned it a spot here.

---

## Setup 1: Trend Join Long (Day Trading Watchlist)

**Backtest:** 54.6% win rate, 1.59 profit factor, 280 trades.

### Premarket selection criteria (ALL required)

| Rule | Threshold |
|------|-----------|
| Gap % vs previous close | > 3% |
| Price | > $3 |
| Market cap | > $1B |
| Premarket relative volume (RVOL) | > 1.5 |
| Price action | Breaking above yesterday's high |

> Note: with the free yfinance stack, RVOL is a full-day stand-in (yfinance
> reports almost no premarket volume). Treat borderline RVOL reads with
> suspicion until a real premarket feed (e.g. Alpaca) is wired in.

### Intraday plan

- **Window:** 10:00am – 3:30pm ET (skip the open chop)
- **Trigger:** price > premarket high AND > prior high-of-day
- **Stop (1R):** 1% below the premarket high or low-of-day, whichever is lower
- **Scaling:** 1/3 off at +1R, 1/3 off at +2R, trail the last 1/3 on the 21-EMA
- **Hard exit:** flat by 3:51pm ET, no exceptions

---

## Setup 2: Swing Watchlist (template — replace with your backtested rules)

Candidates that don't fit the day-trade window but have a multi-day catalyst.

### Selection criteria (ALL required)

| Rule | Threshold |
|------|-----------|
| Catalyst | Fresh, named catalyst (earnings, guidance, FDA, M&A, contract) |
| Market cap | > $1B |
| Trend context | Above rising 50-day SMA, or reclaiming it on the catalyst |
| Gap behaviour | Holding the gap (not fading below yesterday's high) |

### Positional plan

- **Entry idea:** first orderly pullback / first red-to-green after the gap day
- **Stop:** below the gap-day low
- **Target:** scale at prior swing highs; time-stop after 10 sessions if flat

> This setup is a scaffold — it has NOT been backtested. Replace it with rules
> you have actually validated before giving its picks any conviction above 2.

---

## Volume filter guidance

The scanner's default volume floor is **50K shares** — below that names are too
illiquid. Drop to **20K** for a wider net, raise to **100K+** for larger
account sizes. Adjust with `--min-volume` on `premarket_scan.py`.

## Conviction scale (used by both AI passes)

| Score | Meaning |
|-------|---------|
| 5 | Every rule met with room to spare, clear catalyst, both AIs agree |
| 4 | Every rule met, both AIs agree, one soft spot (e.g. stand-in RVOL) |
| 3 | Rules met but catalyst is weak/second-hand, or AIs mildly disagree |
| 2 | A rule is borderline OR the second brain flags a real objection |
| 1 | Only listed for awareness — do not trade |

Hard cap: if the rival AI (Codex) disagrees on direction or setup validity,
conviction cannot exceed 2 and the disagreement must be shown in the report.
