#!/usr/bin/env python3
"""SQLite storage helpers for Star Office RPS + agent messaging."""

from __future__ import annotations

import json
import os
import random
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta


VALID_CHOICES = {"rock", "paper", "scissors"}
ACTIVE_MATCH_STATUSES = {"pending", "waiting_reply"}
TERMINAL_MATCH_STATUSES = {"resolved", "rejected", "timeout", "error"}


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(db_path)) or "."
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _from_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        t = str(ts).strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _normalize_choice(choice: str | None) -> str | None:
    if choice is None:
        return None
    c = str(choice).strip().lower()
    if c in VALID_CHOICES:
        return c
    return None


def ensure_rps_schema(db_path: str):
    """Create RPS tables if they do not exist."""
    conn = _connect(db_path)
    try:
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS rps_matches (
                match_id TEXT PRIMARY KEY,
                challenger_id TEXT NOT NULL,
                opponent_id TEXT NOT NULL,
                challenger_choice TEXT,
                opponent_choice TEXT,
                status TEXT NOT NULL,
                outcome TEXT,
                winner_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                idempotency_key TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                seq INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ttl_seconds INTEGER
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                challenger_id TEXT NOT NULL,
                opponent_id TEXT NOT NULL,
                challenger_move TEXT,
                opponent_move TEXT,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        cur.execute("CREATE INDEX IF NOT EXISTS idx_rps_matches_status ON rps_matches(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rps_matches_challenger ON rps_matches(challenger_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rps_matches_opponent ON rps_matches(opponent_id)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rps_matches_idempotency_key ON rps_matches(idempotency_key) WHERE idempotency_key IS NOT NULL")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_to_seq ON agent_messages(to_agent, seq)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_status ON agent_messages(status)")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_game_log_created_at ON game_log(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_game_log_match_id ON game_log(match_id)")

        conn.commit()
    finally:
        conn.close()


def compute_rps_outcome(challenger_choice: str, opponent_choice: str):
    """Server-side RPS validator.

    Returns: (outcome, winner_side)
    - outcome: challenger_win | opponent_win | draw
    - winner_side: challenger | opponent | None
    """
    c = _normalize_choice(challenger_choice)
    o = _normalize_choice(opponent_choice)
    if c is None or o is None:
        raise ValueError("invalid choice; expected rock|paper|scissors")

    if c == o:
        return "draw", None

    wins = {
        ("rock", "scissors"),
        ("scissors", "paper"),
        ("paper", "rock"),
    }
    if (c, o) in wins:
        return "challenger_win", "challenger"

    return "opponent_win", "opponent"


def has_active_match_for_agent(db_path: str, agent_id: str) -> bool:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ACTIVE_MATCH_STATUSES)
        sql = f"""
            SELECT 1
            FROM rps_matches
            WHERE status IN ({placeholders})
              AND (challenger_id = ? OR opponent_id = ?)
            LIMIT 1
        """
        params = [*ACTIVE_MATCH_STATUSES, agent_id, agent_id]
        cur.execute(sql, params)
        return cur.fetchone() is not None
    finally:
        conn.close()


def create_match_with_lock(
    db_path: str,
    *,
    match_id: str,
    challenger_id: str,
    opponent_id: str,
    created_at: str,
    expires_at: str | None = None,
    idempotency_key: str | None = None,
):
    """Create a pending match with single-active-match lock enforcement."""
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")

        if idempotency_key:
            cur.execute(
                "SELECT match_id, status, challenger_id, opponent_id FROM rps_matches WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            existing = cur.fetchone()
            if existing is not None:
                conn.commit()
                return {
                    "created": False,
                    "match_id": existing["match_id"],
                    "status": existing["status"],
                    "challenger_id": existing["challenger_id"],
                    "opponent_id": existing["opponent_id"],
                    "idempotent": True,
                }

        placeholders = ",".join("?" for _ in ACTIVE_MATCH_STATUSES)
        sql = f"""
            SELECT challenger_id, opponent_id, status
            FROM rps_matches
            WHERE status IN ({placeholders})
              AND (challenger_id IN (?, ?) OR opponent_id IN (?, ?))
            LIMIT 1
        """
        params = [*ACTIVE_MATCH_STATUSES, challenger_id, opponent_id, challenger_id, opponent_id]
        cur.execute(sql, params)
        conflict = cur.fetchone()
        if conflict is not None:
            conn.rollback()
            raise ValueError("match lock conflict: one of agents already has an active match")

        cur.execute(
            """
            INSERT INTO rps_matches (
                match_id,
                challenger_id,
                opponent_id,
                status,
                created_at,
                updated_at,
                expires_at,
                idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                challenger_id,
                opponent_id,
                "pending",
                created_at,
                created_at,
                expires_at,
                idempotency_key,
            ),
        )
        conn.commit()
        return {
            "created": True,
            "match_id": match_id,
            "status": "pending",
            "challenger_id": challenger_id,
            "opponent_id": opponent_id,
            "idempotent": False,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def create_challenge(
    db_path: str,
    *,
    challenger_id: str,
    opponent_id: str,
    challenger_choice: str | None,
    timeout_seconds: int,
    idempotency_key: str | None = None,
):
    now = datetime.now(UTC)
    created_at = now.isoformat()
    expires_at = (now + timedelta(seconds=max(1, int(timeout_seconds)))).isoformat()
    match_id = f"m_{uuid.uuid4().hex[:16]}"

    created = create_match_with_lock(
        db_path,
        match_id=match_id,
        challenger_id=challenger_id,
        opponent_id=opponent_id,
        created_at=created_at,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
    )

    if created.get("idempotent"):
        return created

    # move to waiting_reply immediately; challenger move is committed here
    c = _normalize_choice(challenger_choice) or random.choice(sorted(VALID_CHOICES))
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE rps_matches
            SET status = 'waiting_reply', challenger_choice = ?, updated_at = ?
            WHERE match_id = ?
            """,
            (c, utcnow_iso(), created["match_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    created["status"] = "waiting_reply"
    created["challenger_choice"] = c
    created["expires_at"] = expires_at
    return created


def resolve_rps_match(db_path: str, match_id: str, challenger_choice: str, opponent_choice: str):
    c = _normalize_choice(challenger_choice)
    o = _normalize_choice(opponent_choice)
    if c is None or o is None:
        raise ValueError("invalid choice; expected rock|paper|scissors")

    outcome, winner_side = compute_rps_outcome(c, o)

    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT match_id, challenger_id, opponent_id FROM rps_matches WHERE match_id = ?",
            (match_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("match not found")

        winner_id = None
        if winner_side == "challenger":
            winner_id = row["challenger_id"]
        elif winner_side == "opponent":
            winner_id = row["opponent_id"]

        now = utcnow_iso()
        cur.execute(
            """
            UPDATE rps_matches
            SET challenger_choice = ?,
                opponent_choice = ?,
                status = ?,
                outcome = ?,
                winner_id = ?,
                updated_at = ?
            WHERE match_id = ?
            """,
            (c, o, "resolved", outcome, winner_id, now, match_id),
        )

        cur.execute(
            """
            INSERT INTO game_log (
                match_id, challenger_id, opponent_id,
                challenger_move, opponent_move, outcome, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (match_id, row["challenger_id"], row["opponent_id"], c, o, outcome, now),
        )

        conn.commit()
        return {
            "match_id": match_id,
            "status": "resolved",
            "challenger_choice": c,
            "opponent_choice": o,
            "outcome": outcome,
            "winner_id": winner_id,
        }
    finally:
        conn.close()


def reply_to_challenge(
    db_path: str,
    *,
    match_id: str,
    opponent_id: str,
    opponent_choice: str | None,
    idempotency_key: str | None = None,
):
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute(
            """
            SELECT match_id, challenger_id, opponent_id, challenger_choice,
                   opponent_choice, status, outcome, winner_id, expires_at, idempotency_key
            FROM rps_matches WHERE match_id = ?
            """,
            (match_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("match not found")
        if row["opponent_id"] != opponent_id:
            raise ValueError("reply agent is not the expected opponent")

        if row["status"] == "resolved":
            conn.commit()
            return {
                "idempotent": True,
                "match_id": row["match_id"],
                "challenger_id": row["challenger_id"],
                "opponent_id": row["opponent_id"],
                "status": row["status"],
                "outcome": row["outcome"],
                "winner_id": row["winner_id"],
                "challenger_choice": row["challenger_choice"],
                "opponent_choice": row["opponent_choice"],
            }
        if row["status"] not in {"waiting_reply", "pending"}:
            raise ValueError("match is not waiting for reply")

        exp = _from_iso(row["expires_at"])
        if exp is not None and datetime.now(UTC) > exp:
            now = utcnow_iso()
            cur.execute(
                "UPDATE rps_matches SET status='timeout', outcome='timeout', updated_at=? WHERE match_id=?",
                (now, match_id),
            )
            conn.commit()
            return {"match_id": match_id, "status": "timeout", "outcome": "timeout", "idempotent": False}

        if idempotency_key and row["idempotency_key"] == idempotency_key and row["opponent_choice"]:
            conn.commit()
            return {
                "idempotent": True,
                "match_id": row["match_id"],
                "challenger_id": row["challenger_id"],
                "opponent_id": row["opponent_id"],
                "status": row["status"],
                "outcome": row["outcome"],
                "winner_id": row["winner_id"],
                "challenger_choice": row["challenger_choice"],
                "opponent_choice": row["opponent_choice"],
            }

        c = _normalize_choice(row["challenger_choice"]) or random.choice(sorted(VALID_CHOICES))
        o = _normalize_choice(opponent_choice) or random.choice(sorted(VALID_CHOICES))
        outcome, winner_side = compute_rps_outcome(c, o)
        winner_id = row["challenger_id"] if winner_side == "challenger" else (row["opponent_id"] if winner_side == "opponent" else None)
        now = utcnow_iso()

        cur.execute(
            """
            UPDATE rps_matches
            SET status='resolved', challenger_choice=?, opponent_choice=?,
                outcome=?, winner_id=?, updated_at=?
            WHERE match_id=?
            """,
            (c, o, outcome, winner_id, now, match_id),
        )
        cur.execute(
            """
            INSERT INTO game_log(match_id, challenger_id, opponent_id, challenger_move, opponent_move, outcome, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (match_id, row["challenger_id"], row["opponent_id"], c, o, outcome, now),
        )
        conn.commit()
        return {
            "idempotent": False,
            "match_id": match_id,
            "challenger_id": row["challenger_id"],
            "opponent_id": row["opponent_id"],
            "status": "resolved",
            "outcome": outcome,
            "winner_id": winner_id,
            "challenger_choice": c,
            "opponent_choice": o,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def transition_match_to_terminal(
    db_path: str,
    *,
    match_id: str,
    terminal_status: str,
    outcome: str | None = None,
):
    status = (terminal_status or "").strip().lower()
    if status not in TERMINAL_MATCH_STATUSES:
        raise ValueError("invalid terminal status")

    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT match_id, challenger_id, opponent_id, outcome FROM rps_matches WHERE match_id = ?",
            (match_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("match not found")

        final_outcome = outcome or (status if status in {"rejected", "timeout", "error"} else row["outcome"])
        now = utcnow_iso()
        cur.execute(
            "UPDATE rps_matches SET status = ?, outcome = ?, updated_at = ? WHERE match_id = ?",
            (status, final_outcome, now, match_id),
        )
        if status in {"rejected", "timeout", "error"}:
            cur.execute(
                """
                INSERT INTO game_log(match_id, challenger_id, opponent_id, challenger_move, opponent_move, outcome, created_at)
                VALUES (?, ?, ?, NULL, NULL, ?, ?)
                """,
                (match_id, row["challenger_id"], row["opponent_id"], final_outcome, now),
            )
        conn.commit()
        return {
            "match_id": match_id,
            "status": status,
            "outcome": final_outcome,
            "lock_released": True,
            "unlocked_agents": [row["challenger_id"], row["opponent_id"]],
        }
    finally:
        conn.close()


def sweep_expired_waiting_replies(db_path: str, now: datetime | None = None) -> int:
    t = now or datetime.now(UTC)
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE rps_matches
            SET status='timeout', outcome='timeout', updated_at=?
            WHERE status='waiting_reply'
              AND expires_at IS NOT NULL
              AND expires_at != ''
              AND expires_at <= ?
            """,
            (t.isoformat(), t.isoformat()),
        )
        changed = cur.rowcount or 0
        if changed:
            cur.execute(
                """
                INSERT INTO game_log(match_id, challenger_id, opponent_id, challenger_move, opponent_move, outcome, created_at)
                SELECT match_id, challenger_id, opponent_id, challenger_choice, NULL, 'timeout', ?
                FROM rps_matches
                WHERE status='timeout' AND outcome='timeout' AND updated_at=?
                """,
                (t.isoformat(), t.isoformat()),
            )
        conn.commit()
        return changed
    finally:
        conn.close()


def recover_locks_from_persisted_state(db_path: str):
    """No-op lock recovery metadata (locks derive from persisted match status)."""
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in ACTIVE_MATCH_STATUSES)
        cur.execute(
            f"SELECT match_id, challenger_id, opponent_id, status FROM rps_matches WHERE status IN ({placeholders})",
            list(ACTIVE_MATCH_STATUSES),
        )
        rows = cur.fetchall()
        return {
            "active_match_count": len(rows),
            "active_matches": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def enqueue_agent_message(
    db_path: str,
    *,
    from_agent: str,
    to_agent: str,
    msg_type: str,
    payload: dict,
    ttl_seconds: int | None = None,
):
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT COALESCE(MAX(seq), 0) FROM agent_messages")
        next_seq = int(cur.fetchone()[0]) + 1
        cur.execute(
            """
            INSERT INTO agent_messages(from_agent, to_agent, type, payload_json, seq, status, created_at, ttl_seconds)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                from_agent,
                to_agent,
                msg_type,
                json.dumps(payload or {}, ensure_ascii=False),
                next_seq,
                utcnow_iso(),
                int(ttl_seconds) if ttl_seconds is not None else None,
            ),
        )
        conn.commit()
        return {"ok": True, "seq": next_seq}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _message_is_expired(created_at: str, ttl_seconds: int | None, now: datetime) -> bool:
    if ttl_seconds is None:
        return False
    dt = _from_iso(created_at)
    if dt is None:
        return False
    return now > (dt + timedelta(seconds=int(ttl_seconds)))


def fetch_agent_inbox(db_path: str, *, to_agent: str, since_seq: int = 0, limit: int = 100):
    limit_n = max(1, min(int(limit or 100), 500))
    since = max(0, int(since_seq or 0))
    now = datetime.now(UTC)

    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, from_agent, to_agent, type, payload_json, seq, status, created_at, ttl_seconds
            FROM agent_messages
            WHERE to_agent = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (to_agent, since, limit_n),
        )
        rows = cur.fetchall()

        out = []
        delivered_ids = []
        expired_ids = []
        for r in rows:
            if _message_is_expired(r["created_at"], r["ttl_seconds"], now):
                expired_ids.append(r["id"])
                continue
            payload = {}
            try:
                payload = json.loads(r["payload_json"] or "{}")
            except Exception:
                payload = {"raw": r["payload_json"]}
            out.append(
                {
                    "from": r["from_agent"],
                    "to": r["to_agent"],
                    "type": r["type"],
                    "payload": payload,
                    "seq": r["seq"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                }
            )
            if r["status"] == "queued":
                delivered_ids.append(r["id"])

        if delivered_ids:
            q = ",".join("?" for _ in delivered_ids)
            cur.execute(f"UPDATE agent_messages SET status='delivered' WHERE id IN ({q})", delivered_ids)
        if expired_ids:
            q = ",".join("?" for _ in expired_ids)
            cur.execute(f"UPDATE agent_messages SET status='expired' WHERE id IN ({q})", expired_ids)
        conn.commit()

        return {
            "messages": out,
            "nextSince": out[-1]["seq"] if out else since,
        }
    finally:
        conn.close()


def ack_agent_messages(db_path: str, *, to_agent: str, up_to_seq: int):
    seq = max(0, int(up_to_seq or 0))
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE agent_messages
            SET status='read'
            WHERE to_agent=? AND seq<=? AND status IN ('queued','delivered')
            """,
            (to_agent, seq),
        )
        conn.commit()
        return {"ok": True, "acked": cur.rowcount or 0, "up_to_seq": seq}
    finally:
        conn.close()
