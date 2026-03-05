#!/usr/bin/env python3
"""SQLite storage bootstrap for RPS features."""

from __future__ import annotations

import os
import sqlite3


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
