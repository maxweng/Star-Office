#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path("/root/.openclaw/workspace")
SESSIONS_FILE = Path("/root/.openclaw/agents/main/sessions/sessions.json")
STATE_FILE = WORKSPACE / "Star-Office-UI" / "state.json"

POLL_SECONDS = float(os.environ.get("STAR_BRIDGE_POLL_SECONDS", "3"))
ACTIVE_SECONDS = float(os.environ.get("STAR_BRIDGE_ACTIVE_SECONDS", "120"))
DETAIL_PREFIX = os.environ.get("STAR_BRIDGE_DETAIL_PREFIX", "OpenClaw auto-sync")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_activity_ts_ms() -> int | None:
    if not SESSIONS_FILE.exists():
        return None
    data = read_json(SESSIONS_FILE)
    latest = None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            ts = item.get("updatedAt") or item.get("updated_at")
            if isinstance(ts, (int, float)):
                latest = max(latest or 0, int(ts))
    elif isinstance(data, dict):
        # Newer OpenClaw format: top-level map keyed by sessionKey
        for item in data.values():
            if not isinstance(item, dict):
                continue
            ts = item.get("updatedAt") or item.get("updated_at")
            if isinstance(ts, (int, float)):
                latest = max(latest or 0, int(ts))

        # Legacy/alternate format: { recent: [...] }
        recent = data.get("recent")
        if isinstance(recent, list):
            for item in recent:
                if not isinstance(item, dict):
                    continue
                ts = item.get("updatedAt") or item.get("updated_at")
                if isinstance(ts, (int, float)):
                    latest = max(latest or 0, int(ts))
    return latest


def write_state(state: str, detail: str):
    payload = {
        "state": state,
        "detail": detail,
        "progress": 0,
        "updated_at": now_iso(),
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(STATE_FILE)


def read_current_state() -> str | None:
    try:
        return read_json(STATE_FILE).get("state")
    except Exception:
        return None


def main():
    last_state = None
    while True:
        try:
            latest_ms = get_latest_activity_ts_ms()
            now_ms = int(time.time() * 1000)
            age_sec = None if latest_ms is None else max(0, (now_ms - latest_ms) / 1000)

            if age_sec is not None and age_sec <= ACTIVE_SECONDS:
                target_state = "writing"
                detail = f"{DETAIL_PREFIX}: working ({age_sec:.0f}s since last activity)"
            else:
                target_state = "idle"
                detail = f"{DETAIL_PREFIX}: idle"

            current = read_current_state()
            if current != target_state or last_state != target_state:
                write_state(target_state, detail)
                last_state = target_state
        except Exception as e:
            write_state("error", f"{DETAIL_PREFIX}: bridge error: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
