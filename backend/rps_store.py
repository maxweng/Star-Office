#!/usr/bin/env python3
"""SQLite storage bootstrap for RPS features."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime


def _connect(db_path: str) -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(db_path)) or "."
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


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

        # Helpful indexes for upcoming challenge/reply and log views
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


VALID_CHOICES = {"rock", "paper", "scissors"}
ACTIVE_MATCH_STATUSES = {"pending", "waiting_reply"}
TERMINAL_MATCH_STATUSES = {"resolved", "rejected", "timeout", "error"}


def _normalize_choice(choice: str | None) -> str | None:
    if choice is None:
        return None
    c = str(choice).strip().lower()
    if c in VALID_CHOICES:
        return c
    return None


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
    """Create a pending match with single-active-match lock enforcement.

    Lock rule:
    - challenger/opponent cannot have existing pending/waiting_reply match.
    """
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")

        # idempotent retry: if same key already exists, return existing row
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


def resolve_rps_match(db_path: str, match_id: str, challenger_choice: str, opponent_choice: str):
    """Resolve a match using server-side validator and persist canonical result."""
    c = _normalize_choice(challenger_choice)
    o = _normalize_choice(opponent_choice)
    if c is None or o is None:
        raise ValueError("invalid choice; expected rock|paper|scissors")

    outcome, winner_side = compute_rps_outcome(c, o)

    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT match_id, challenger_id, opponent_id, status FROM rps_matches WHERE match_id = ?",
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

        now = datetime.utcnow().isoformat()
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
