#!/usr/bin/env python3
"""RPS backend smoke test (non-destructive, local temp DB).

Usage:
  python3 scripts/rps_smoke_test.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, UTC
from pathlib import Path


def fail(msg: str) -> int:
    print(f"[rps-smoke] FAIL: {msg}")
    return 1


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    backend_dir = root / "backend"
    sys.path.insert(0, str(backend_dir))

    try:
        from rps_store import (
            ensure_rps_schema,
            create_match_with_lock,
            has_active_match_for_agent,
            resolve_rps_match,
            transition_match_to_terminal,
        )
    except Exception as e:
        return fail(f"import error: {e}")

    fd, db_path = tempfile.mkstemp(prefix="rps_smoke_", suffix=".sqlite3")
    os.close(fd)

    try:
        ensure_rps_schema(db_path)

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()

        required = {"rps_matches", "agent_messages", "game_log"}
        missing = sorted(required - tables)
        if missing:
            return fail(f"missing tables: {missing}")

        now = datetime.now(UTC).isoformat()

        first = create_match_with_lock(
            db_path=db_path,
            match_id="m1",
            challenger_id="agent_a",
            opponent_id="agent_b",
            created_at=now,
            idempotency_key="k1",
        )
        if not first.get("created"):
            return fail("first match was not created")

        if not has_active_match_for_agent(db_path, "agent_a"):
            return fail("expected active match lock for challenger")

        # Retry same idempotency key should not create a duplicate row.
        retry = create_match_with_lock(
            db_path=db_path,
            match_id="m1_retry_ignored",
            challenger_id="agent_a",
            opponent_id="agent_b",
            created_at=now,
            idempotency_key="k1",
        )
        if not retry.get("idempotent"):
            return fail("idempotent retry did not return existing match")

        # Conflicting active match should be blocked.
        try:
            create_match_with_lock(
                db_path=db_path,
                match_id="m2",
                challenger_id="agent_a",
                opponent_id="agent_c",
                created_at=now,
            )
            return fail("expected lock conflict for second active match")
        except ValueError:
            pass

        resolved = resolve_rps_match(db_path, "m1", "rock", "scissors")
        if resolved.get("outcome") != "challenger_win":
            return fail(f"unexpected resolve outcome: {resolved}")

        if has_active_match_for_agent(db_path, "agent_a"):
            return fail("lock should be released after resolved")

        create_match_with_lock(
            db_path=db_path,
            match_id="m3",
            challenger_id="agent_a",
            opponent_id="agent_b",
            created_at=now,
        )
        term = transition_match_to_terminal(db_path=db_path, match_id="m3", terminal_status="timeout")
        if term.get("status") != "timeout":
            return fail(f"unexpected terminal transition result: {term}")

        if has_active_match_for_agent(db_path, "agent_a"):
            return fail("lock should be released after timeout")

        print("[rps-smoke] PASS")
        return 0
    finally:
        try:
            os.remove(db_path)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
