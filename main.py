"""
WhatsYes - TV Schedule for Grandma
A simple, accessible web app that scrapes Yes TV broadcast schedules
and presents them in a grandma-friendly interface.
"""

import os

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import requests
from datetime import datetime, timedelta
from typing import Optional
import time

from channels import CHANNELS

app = FastAPI(title="WhatsYes - לוח שידורים")

# ── Yes API Configuration ────────────────────────────────────────────────────

YES_API_BASE = "https://svc.yes.co.il/api/content/broadcast-schedule/channels"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.yes.co.il/",
    "Origin": "https://www.yes.co.il",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "Connection": "keep-alive",
}

# Persistent session — keeps cookies/connection alive across requests.
_session: requests.Session | None = None
_session_ts: float = 0
SESSION_TTL = 30 * 60  # refresh session every 30 min


def _get_session() -> requests.Session:
    """Return a warm requests.Session, refreshing it when stale."""
    global _session, _session_ts
    now = time.time()
    if _session is None or (now - _session_ts) > SESSION_TTL:
        s = requests.Session()
        s.headers.update(HEADERS)
        # Pre-warm: visit main site to pick up cookies / pass WAF challenge
        try:
            s.get("https://www.yes.co.il/", timeout=10)
        except Exception:
            pass
        _session = s
        _session_ts = now
    return _session

# ── In-Memory Cache ──────────────────────────────────────────────────────────
# Key: (channel_id, date_str)  →  Value: {"ts": epoch, "data": [...]}
# TTL: 10 minutes — schedules rarely change within that window.

CACHE_TTL = 10 * 60  # seconds
_cache: dict[tuple[str, str], dict] = {}


def _cache_get(channel_id: str, date_str: str) -> list[dict] | None:
    """Return cached items if still fresh, else None."""
    key = (channel_id, date_str)
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(channel_id: str, date_str: str, data: list[dict]) -> None:
    """Store items in cache with current timestamp."""
    _cache[(channel_id, date_str)] = {"ts": time.time(), "data": data}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _israel_now() -> datetime:
    """Return current datetime in Israel timezone (UTC+2 / UTC+3 summer)."""
    # Simple approach: Israel is generally UTC+2 (winter) or UTC+3 (summer)
    # For scheduling purposes, we just need the date
    return datetime.utcnow() + timedelta(hours=3)


def _format_time(iso_str: str) -> str:
    """Convert ISO datetime to Israel-local HH:MM string."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    israel_dt = dt + timedelta(hours=3)  # approximate Israel time
    return israel_dt.strftime("%H:%M")


def _fetch_schedule(channel_id: str, date_str: str) -> list[dict]:
    """Fetch schedule from Yes API for a single channel and date (with cache)."""
    # Check cache first
    cached = _cache_get(channel_id, date_str)
    if cached is not None:
        return cached

    url = f"{YES_API_BASE}/{channel_id}"
    params = {"date": date_str, "ignorePastItems": "false"}
    try:
        session = _get_session()
        resp = session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        _cache_set(channel_id, date_str, items)
        return items
    except Exception as e:
        print(f"[warn] Failed to fetch {channel_id} for {date_str}: {e}")
        return []


def _enrich_item(item: dict) -> dict:
    """Transform a raw API item into a frontend-friendly dict."""
    return {
        "title": item.get("title", ""),
        "description": item.get("description", ""),
        "image": item.get("imageUrl", ""),
        "starts": item.get("starts", ""),
        "ends": item.get("ends", ""),
        "start_time": _format_time(item["starts"]) if item.get("starts") else "",
        "end_time": _format_time(item["ends"]) if item.get("ends") else "",
        "channel_id": item.get("channelId", ""),
    }


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/channels")
def get_channels():
    """Return the list of known channels."""
    return [
        {"id": cid, "name": name}
        for cid, name in CHANNELS.items()
    ]


@app.get("/api/schedule/{channel_id}")
def get_schedule(
    channel_id: str,
    date: Optional[str] = Query(None, description="Date as YYYY-M-D, defaults to today"),
):
    """Return the broadcast schedule for a channel on a given date."""
    if date is None:
        now = _israel_now()
        date = f"{now.year}-{now.month}-{now.day}"

    items = _fetch_schedule(channel_id, date)
    enriched = [_enrich_item(it) for it in items]

    # Sort by start time
    enriched.sort(key=lambda x: x["starts"])

    channel_name = CHANNELS.get(channel_id, channel_id)
    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "date": date,
        "programs": enriched,
    }


@app.get("/api/now")
def whats_on_now():
    """Return what's currently airing across all channels."""
    now = _israel_now()
    date_str = f"{now.year}-{now.month}-{now.day}"
    now_iso = datetime.utcnow().isoformat() + "Z"

    results = []
    for cid, cname in CHANNELS.items():
        items = _fetch_schedule(cid, date_str)
        for item in items:
            if item.get("starts", "") <= now_iso <= item.get("ends", ""):
                enriched = _enrich_item(item)
                enriched["channel_name"] = cname
                results.append(enriched)
                break

    return {"now": now_iso, "programs": results}


# ── Static Files & Frontend ─────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
