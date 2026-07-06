#!/usr/bin/env python3
"""
send_report.py — deliver the premarket report by email (Resend) and/or Discord.

Everything runs locally; the only things that leave your machine are the
report email (via Resend) and the optional Discord post.

Environment variables:
  RESEND_API_KEY        Resend API key (https://resend.com — free tier is fine)
  PREMARKET_EMAIL_FROM  From address (must be a verified Resend sender/domain,
                        e.g. "Premarket Analyst <onboarding@resend.dev>")
  PREMARKET_EMAIL_TO    Recipient address (comma-separated for several)
  DISCORD_WEBHOOK_URL   Optional Discord channel webhook

Usage:
  python3 send_report.py --report ~/.premarket/reports/2026-07-04-premarket.md
  python3 send_report.py --report report.md --subject "Premarket Report" --discord
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import date

try:
    import markdown as md
except ImportError:
    md = None

RESEND_URL = "https://api.resend.com/emails"
DISCORD_CHUNK = 1900  # Discord hard limit is 2000 chars per message


def post_json(url, payload, headers):
    body = json.dumps(payload).encode("utf-8")
    # Cloudflare (fronting both Resend and Discord) blocks urllib's default
    # "Python-urllib/x.y" User-Agent as bot traffic (error code 1010) even
    # with a valid, correctly-authorized request. A generic tool-like UA
    # clears it; there's nothing browser-specific required.
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "curl/8.7.1", **headers},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def to_html(md_text):
    if md is not None:
        body = md.markdown(md_text, extensions=["tables", "fenced_code"])
    else:
        import html
        body = f"<pre>{html.escape(md_text)}</pre>"
    return (
        "<div style=\"font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;"
        "max-width:760px;margin:0 auto;line-height:1.5\">"
        "<style>table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px}"
        "th{background:#f4f4f4}</style>"
        f"{body}</div>"
    )


def send_email(md_text, subject):
    api_key = os.environ.get("RESEND_API_KEY")
    email_from = os.environ.get("PREMARKET_EMAIL_FROM")
    email_to = os.environ.get("PREMARKET_EMAIL_TO")
    missing = [n for n, v in [("RESEND_API_KEY", api_key),
                              ("PREMARKET_EMAIL_FROM", email_from),
                              ("PREMARKET_EMAIL_TO", email_to)] if not v]
    if missing:
        print(f"[send_report] email skipped — missing env: {', '.join(missing)}", file=sys.stderr)
        return False

    payload = {
        "from": email_from,
        "to": [a.strip() for a in email_to.split(",") if a.strip()],
        "subject": subject,
        "html": to_html(md_text),
        "text": md_text,
    }
    status, body = post_json(RESEND_URL, payload, {"Authorization": f"Bearer {api_key}"})
    if 200 <= status < 300:
        print(f"[send_report] email sent ({body.strip()})", file=sys.stderr)
        return True
    print(f"[send_report] Resend error {status}: {body}", file=sys.stderr)
    return False


def send_discord(md_text):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("[send_report] discord skipped — DISCORD_WEBHOOK_URL not set", file=sys.stderr)
        return False

    chunks, current = [], ""
    for line in md_text.splitlines(keepends=True):
        if len(current) + len(line) > DISCORD_CHUNK:
            chunks.append(current)
            current = ""
        current += line
    if current.strip():
        chunks.append(current)

    ok = True
    for chunk in chunks:
        status, body = post_json(webhook, {"content": chunk}, {})
        if not (200 <= status < 300):
            print(f"[send_report] Discord error {status}: {body}", file=sys.stderr)
            ok = False
    if ok:
        print(f"[send_report] posted {len(chunks)} Discord message(s)", file=sys.stderr)
    return ok


def main():
    ap = argparse.ArgumentParser(description="Send the premarket report via Resend email and/or Discord")
    ap.add_argument("--report", required=True, help="Path to the markdown report")
    ap.add_argument("--subject", default=None, help="Email subject (default: dated)")
    ap.add_argument("--discord", action="store_true", help="Also post to Discord webhook")
    ap.add_argument("--no-email", action="store_true", help="Skip email, e.g. Discord-only")
    args = ap.parse_args()

    with open(args.report) as f:
        md_text = f.read()

    subject = args.subject or f"Premarket Report — {date.today().strftime('%A %B %d, %Y')}"

    sent_any = False
    if not args.no_email:
        sent_any = send_email(md_text, subject) or sent_any
    if args.discord:
        sent_any = send_discord(md_text) or sent_any

    sys.exit(0 if sent_any else 1)


if __name__ == "__main__":
    main()
