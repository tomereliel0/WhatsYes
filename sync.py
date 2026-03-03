#!/usr/bin/env python3
"""
WhatsYes Local Sync Script
───────────────────────────
Runs from an Israeli machine, fetches schedules from the Yes API,
and pushes the data to the production Render app.

Usage:
    python3 sync.py                       # uses .env or env vars
    RENDER_URL=https://… SYNC_API_KEY=… python3 sync.py

Environment variables:
    RENDER_URL      – production base URL (e.g. https://whatsyes.onrender.com)
    SYNC_API_KEY    – shared secret matching the Render app's SYNC_API_KEY
    SYNC_DAYS       – how many days to fetch (default: 9 = today + 8 days ahead)
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ── Load .env if present ─────────────────────────────────────────────────────

ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Config ───────────────────────────────────────────────────────────────────

RENDER_URL = os.environ.get("RENDER_URL", "").rstrip("/")
SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")
SYNC_DAYS = int(os.environ.get("SYNC_DAYS", "9"))

if not RENDER_URL or not SYNC_API_KEY:
    print("ERROR: Set RENDER_URL and SYNC_API_KEY environment variables (or in .env)")
    print("  Example .env:")
    print("    RENDER_URL=https://whatsyes.onrender.com")
    print("    SYNC_API_KEY=your-secret-key-here")
    sys.exit(1)

# ── Channel list (import from project) ───────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent))
from channels import CHANNELS

# ── Yes API ──────────────────────────────────────────────────────────────────

YES_API_BASE = "https://svc.yes.co.il/api/content/broadcast-schedule/channels"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.yes.co.il/",
    "Origin": "https://www.yes.co.il",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}


def fetch_schedule(session: requests.Session, channel_id: str, date_str: str) -> list[dict]:
    """Fetch schedule for one channel + date from Yes API."""
    url = f"{YES_API_BASE}/{channel_id}"
    params = {"date": date_str, "ignorePastItems": "false"}
    try:
        resp = session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except Exception as e:
        print(f"  [FAIL] {channel_id} {date_str}: {e}")
        return []


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"WhatsYes Sync — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target : {RENDER_URL}")
    print(f"  Days   : {SYNC_DAYS}")
    print(f"  Channels: {len(CHANNELS)}")
    print()

    # Build date list
    dates = []
    for offset in range(SYNC_DAYS):
        d = datetime.now() + timedelta(days=offset)
        dates.append(f"{d.year}-{d.month}-{d.day}")

    # Create session
    session = requests.Session()
    session.headers.update(HEADERS)
    # Pre-warm
    try:
        session.get("https://www.yes.co.il/", timeout=10)
    except Exception:
        pass

    # Fetch all schedules
    schedules = {}
    total = len(CHANNELS) * len(dates)
    done = 0
    failed = 0

    for date_str in dates:
        print(f"── {date_str} ──")
        for ch_id, ch_name in CHANNELS.items():
            items = fetch_schedule(session, ch_id, date_str)
            key = f"{ch_id}|{date_str}"
            schedules[key] = items
            done += 1
            if items:
                print(f"  ✓ {ch_name} ({ch_id}): {len(items)} programs")
            else:
                failed += 1
                # Small delay on failure to avoid rate limiting
                time.sleep(0.3)
            # Small politeness delay
            time.sleep(0.15)

    print()
    print(f"Fetched {done}/{total} ({failed} empty/failed)")

    # Push to Render
    print(f"Uploading to {RENDER_URL}/api/_sync ...")
    payload = {"schedules": schedules}
    try:
        resp = requests.post(
            f"{RENDER_URL}/api/_sync",
            json=payload,
            headers={"X-Sync-Key": SYNC_API_KEY},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"  ✓ Uploaded: {result}")
    except Exception as e:
        print(f"  ✗ Upload failed: {e}")
        sys.exit(1)

    print("Done!")


if __name__ == "__main__":
    main()
