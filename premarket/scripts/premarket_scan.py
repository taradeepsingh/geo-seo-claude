#!/usr/bin/env python3
"""
premarket_scan.py — free premarket data engine for the /premarket skill.

Pulls everything from keyless sources:
  * Market snapshot        -> yfinance (futures, VIX, rates, dollar, gold, oil, BTC)
  * Premarket gappers      -> yfinance 2-day bars for every S&P 500 ticker,
                              gap computed vs yesterday's close, filtered and
                              ranked, top N written to the watchlist
  * Catalyst headlines     -> yfinance per-ticker news + free RSS feeds,
                              matched against the gapper symbols
  * Economic calendar      -> ForexFactory data-partner "this week" JSON feed,
                              USD + High impact only (data prints AND Fed
                              events like FOMC / Powell), split into today
                              and tomorrow (ET). The raw weekly feed is cached
                              to a local dotfile with a ~4h TTL because the
                              feed rate-limits (429) on rapid calls; if a live
                              fetch fails we fall back to the last cached week
                              and add a note.

Known limitation (by design of the free stack): yfinance reports almost no
premarket volume, so the RVOL number is a full-day stand-in until you wire in
a real premarket feed (e.g. Alpaca).

Output: a single JSON document on stdout (or --output FILE).

Usage:
  python3 premarket_scan.py                        # full scan, JSON to stdout
  python3 premarket_scan.py --output scan.json
  python3 premarket_scan.py --min-gap 3 --min-volume 50000 --top 20
  python3 premarket_scan.py --universe my_tickers.txt
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9
    ZoneInfo = None

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import feedparser
except ImportError:
    feedparser = None

import urllib.request

ET = ZoneInfo("America/New_York") if ZoneInfo else timezone(timedelta(hours=-5))

CACHE_DIR = os.path.expanduser("~/.premarket")
FF_CACHE_FILE = os.path.join(CACHE_DIR, "ff_calendar_cache.json")
SP500_CACHE_FILE = os.path.join(CACHE_DIR, "sp500_tickers.json")

FF_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_CACHE_TTL_HOURS = 4
SP500_CACHE_TTL_DAYS = 7

SNAPSHOT_TICKERS = {
    "ES=F": "S&P 500 futures",
    "NQ=F": "Nasdaq 100 futures",
    "YM=F": "Dow futures",
    "RTY=F": "Russell 2000 futures",
    "SPY": "SPY",
    "QQQ": "QQQ",
    "^VIX": "VIX",
    "^TNX": "US 10Y yield (x10)",
    "DX-Y.NYB": "US dollar index",
    "GC=F": "Gold",
    "CL=F": "WTI crude",
    "BTC-USD": "Bitcoin",
}

RSS_FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://finance.yahoo.com/news/rssindex",
]

# Small liquid fallback universe in case the S&P 500 list can't be fetched.
FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD",
    "NFLX", "COST", "JPM", "V", "MA", "UNH", "XOM", "CVX", "LLY", "JNJ",
    "PG", "HD", "MRK", "ABBV", "PEP", "KO", "BAC", "CRM", "ORCL", "ADBE",
    "WMT", "DIS", "CSCO", "INTC", "QCOM", "TXN", "AMAT", "MU", "PLTR",
    "SMCI", "COIN", "SQ", "PYPL", "SHOP", "UBER", "ABNB", "SNOW", "MRVL",
    "PANW", "CRWD", "NOW",
]


def log(msg):
    print(f"[premarket_scan] {msg}", file=sys.stderr)


def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (premarket-scan)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def now_et():
    return datetime.now(ET)


# ---------------------------------------------------------------- universe

def load_sp500_universe():
    """S&P 500 tickers from Wikipedia, cached ~7 days. Fallback: liquid megacaps."""
    if os.path.exists(SP500_CACHE_FILE):
        try:
            with open(SP500_CACHE_FILE) as f:
                cached = json.load(f)
            age_days = (time.time() - cached.get("fetched_at", 0)) / 86400.0
            if age_days < SP500_CACHE_TTL_DAYS and cached.get("tickers"):
                return cached["tickers"], "cache"
        except Exception:
            pass

    try:
        req = urllib.request.Request(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (premarket-scan)"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # Symbols appear as links in the constituents table.
        symbols = re.findall(r'<a[^>]*href="https://www\.nyse\.com/quote/[^"]*"[^>]*>([A-Z.\-]{1,6})</a>', html)
        symbols += re.findall(r'<a[^>]*href="https?://www\.nasdaq\.com/market-activity/stocks/[^"]*"[^>]*>([A-Z.\-]{1,6})</a>', html)
        symbols = sorted({s.replace(".", "-") for s in symbols})
        if len(symbols) >= 400:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(SP500_CACHE_FILE, "w") as f:
                json.dump({"fetched_at": time.time(), "tickers": symbols}, f)
            return symbols, "wikipedia"
    except Exception as e:
        log(f"S&P 500 fetch failed ({e}); using fallback universe")

    return FALLBACK_UNIVERSE, "fallback"


def load_universe(path):
    if path:
        with open(path) as f:
            tickers = [ln.strip().upper() for ln in f if ln.strip() and not ln.startswith("#")]
        return tickers, f"file:{path}"
    return load_sp500_universe()


# ---------------------------------------------------------------- snapshot

def market_snapshot():
    out = {}
    if yf is None:
        return {"error": "yfinance not installed"}
    for symbol, label in SNAPSHOT_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d", prepost=True)
            if hist.empty:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
            out[symbol] = {
                "label": label,
                "last": round(last, 2),
                "prev_close": round(prev, 2),
                "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
            }
        except Exception as e:
            out[symbol] = {"label": label, "error": str(e)}
    return out


# ---------------------------------------------------------------- gappers

def scan_gappers(universe, min_gap_pct, min_volume, top_n):
    """2-day bars for the whole universe -> gap vs yesterday's close."""
    if yf is None:
        return [], "yfinance not installed"

    note = None
    rows = []
    chunk_size = 100
    for i in range(0, len(universe), chunk_size):
        chunk = universe[i:i + chunk_size]
        try:
            data = yf.download(
                tickers=" ".join(chunk),
                period="1mo",
                interval="1d",
                group_by="ticker",
                threads=True,
                prepost=True,
                progress=False,
                auto_adjust=False,
            )
        except Exception as e:
            log(f"batch download failed for chunk {i // chunk_size}: {e}")
            continue

        for sym in chunk:
            try:
                df = data[sym] if len(chunk) > 1 else data
                df = df.dropna(subset=["Close"])
                if len(df) < 2:
                    continue
                last_close = float(df["Close"].iloc[-1])
                prev_close = float(df["Close"].iloc[-2])
                prev_high = float(df["High"].iloc[-2])
                today_vol = float(df["Volume"].iloc[-1])
                avg_vol = float(df["Volume"].iloc[:-1].tail(20).mean())
                if not prev_close:
                    continue
                gap_pct = (last_close / prev_close - 1) * 100
                rvol = (today_vol / avg_vol) if avg_vol else None
                rows.append({
                    "symbol": sym,
                    "price": round(last_close, 2),
                    "prev_close": round(prev_close, 2),
                    "prev_high": round(prev_high, 2),
                    "gap_pct": round(gap_pct, 2),
                    "volume": int(today_vol),
                    "avg_volume_20d": int(avg_vol) if avg_vol else None,
                    "rvol_fullday_standin": round(rvol, 2) if rvol else None,
                    "above_prev_high": last_close > prev_high,
                })
            except Exception:
                continue

    keep = [
        r for r in rows
        if abs(r["gap_pct"]) >= min_gap_pct and r["volume"] >= min_volume
    ]
    keep.sort(key=lambda r: abs(r["gap_pct"]), reverse=True)
    keep = keep[:top_n]
    for rank, r in enumerate(keep, start=1):
        r["rank"] = rank
    return keep, note


# ---------------------------------------------------------------- news

def fetch_rss_headlines():
    headlines = []
    if feedparser is None:
        return headlines
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                headlines.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "source": url,
                })
        except Exception:
            continue
    return headlines


def enrich_with_news(gappers, rss_headlines):
    """Per-ticker yfinance news + RSS headlines that match the symbol."""
    for g in gappers:
        sym = g["symbol"]
        news = []
        if yf is not None:
            try:
                for item in (yf.Ticker(sym).news or [])[:5]:
                    content = item.get("content", item)
                    title = content.get("title") or item.get("title") or ""
                    if title:
                        news.append({"title": title, "source": "yfinance"})
            except Exception:
                pass
        pattern = re.compile(rf"\b{re.escape(sym)}\b")
        for h in rss_headlines:
            if pattern.search(h["title"]) and len(news) < 8:
                news.append({"title": h["title"], "source": "rss", "link": h.get("link", "")})
        g["news"] = news
        g["catalyst"] = news[0]["title"] if news else "No headline found — check chart/SEC filings"
    return gappers


# ---------------------------------------------------------------- econ calendar

def econ_calendar():
    """US High-impact events for TODAY and TOMORROW (ET) from the ForexFactory
    data-partner this-week JSON feed, with a ~4h dotfile cache (feed 429s on
    rapid calls). Falls back to the last cached week on failure."""
    note = None
    raw = None
    cached = None

    if os.path.exists(FF_CACHE_FILE):
        try:
            with open(FF_CACHE_FILE) as f:
                cached = json.load(f)
        except Exception:
            cached = None

    fresh_enough = (
        cached is not None
        and (time.time() - cached.get("fetched_at", 0)) < FF_CACHE_TTL_HOURS * 3600
    )

    if fresh_enough:
        raw = cached["events"]
    else:
        try:
            raw = http_get_json(FF_FEED_URL)
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(FF_CACHE_FILE, "w") as f:
                json.dump({"fetched_at": time.time(), "events": raw}, f)
        except Exception as e:
            if cached is not None:
                raw = cached["events"]
                age_h = (time.time() - cached.get("fetched_at", 0)) / 3600.0
                note = f"Live calendar fetch failed ({e}); using cached feed ~{age_h:.1f}h old."
            else:
                return {"today": [], "tomorrow": [], "note": f"Economic calendar unavailable: {e}"}

    today = now_et().date()
    tomorrow = today + timedelta(days=1)
    buckets = {"today": [], "tomorrow": []}

    for ev in raw or []:
        try:
            if ev.get("country") != "USD" or ev.get("impact") != "High":
                continue
            # Feed dates look like 2026-07-04T08:30:00-04:00
            dt = datetime.fromisoformat(ev["date"])
            dt_et = dt.astimezone(ET) if dt.tzinfo else dt.replace(tzinfo=ET)
            entry = {
                "time_et": dt_et.strftime("%H:%M"),
                "title": ev.get("title", ""),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            }
            if dt_et.date() == today:
                buckets["today"].append((dt_et, entry))
            elif dt_et.date() == tomorrow:
                buckets["tomorrow"].append((dt_et, entry))
        except Exception:
            continue

    result = {
        "today": [e for _, e in sorted(buckets["today"], key=lambda x: x[0])],
        "tomorrow": [e for _, e in sorted(buckets["tomorrow"], key=lambda x: x[0])],
    }
    if note:
        result["note"] = note
    return result


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Free premarket data scan (yfinance + RSS + econ calendar)")
    ap.add_argument("--min-gap", type=float, default=3.0,
                    help="Minimum absolute gap %% vs yesterday's close (default 3)")
    ap.add_argument("--min-volume", type=int, default=50_000,
                    help="Minimum volume filter; below ~50K names are too illiquid. "
                         "Drop to 20000 for a wider net, raise to 100000+ for size (default 50000)")
    ap.add_argument("--top", type=int, default=20, help="Max gappers to keep (default 20)")
    ap.add_argument("--universe", default=None,
                    help="Optional path to a newline-separated ticker list (default: S&P 500)")
    ap.add_argument("--output", default=None, help="Write JSON here instead of stdout")
    ap.add_argument("--skip-news", action="store_true", help="Skip news enrichment (faster)")
    args = ap.parse_args()

    if yf is None:
        log("FATAL: yfinance is not installed. Run: pip install yfinance feedparser markdown requests")
        sys.exit(1)

    t0 = time.time()
    universe, universe_source = load_universe(args.universe)
    log(f"universe: {len(universe)} tickers ({universe_source})")

    log("fetching market snapshot...")
    snapshot = market_snapshot()

    log("scanning for gappers (2-day bars across the universe)...")
    gappers, gap_note = scan_gappers(universe, args.min_gap, args.min_volume, args.top)
    log(f"gappers kept: {len(gappers)}")

    rss_headlines = []
    if not args.skip_news:
        log("fetching RSS headlines...")
        rss_headlines = fetch_rss_headlines()
        log("enriching gappers with catalysts...")
        gappers = enrich_with_news(gappers, rss_headlines)

    log("fetching economic calendar...")
    calendar = econ_calendar()

    doc = {
        "generated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "universe": {"size": len(universe), "source": universe_source},
        "filters": {"min_gap_pct": args.min_gap, "min_volume": args.min_volume, "top": args.top},
        "notes": [n for n in [
            gap_note,
            "RVOL is a full-day stand-in: yfinance reports almost no premarket volume.",
        ] if n],
        "snapshot": snapshot,
        "gappers": gappers,
        "market_headlines": rss_headlines[:25],
        "econ_calendar": calendar,
        "elapsed_sec": round(time.time() - t0, 1),
    }

    payload = json.dumps(doc, indent=2)
    if args.output:
        with open(args.output, "w") as f:
            f.write(payload)
        log(f"wrote {args.output} ({len(payload)} bytes)")
    else:
        print(payload)


if __name__ == "__main__":
    main()
