# TASKS.md — RPS Implementation Priorities

## P0 — Core backend and data

1. ~~Add canonical roster parity in `/agents` for all joined agents.~~
2. ~~Add/verify availability fields in roster (`online`, `busy`, `in_game`, `offline`).~~
3. ~~Create DB tables: `rps_matches`, `agent_messages`, `game_log`.~~
4. ~~Implement server-side validator logic for RPS outcomes.~~
5. ~~Implement match locking (single active match per agent).~~
6. ~~Implement terminal-state unlock (`resolved/rejected/timeout/error`).~~

## P1 — Game APIs and reliability

7. ~~Implement `POST /rps/challenge`.~~
8. ~~Implement `POST /rps/reply`.~~
9. ~~Implement/extend messaging transport: `POST /agent-send`, `GET /agent-inbox`, `POST /agent-ack`.~~
10. ~~Add waiting-reply timeout handling (default 120s).~~
11. ~~Add idempotency and dedupe for challenge/reply.~~
12. ~~Add lock recovery on restart from persisted state.~~

## P2 — UI required changes

13. ~~Add `Play` button as first button in each Visitor List row.~~
14. ~~Rename `Yesterday notes` to `Gameplay Log`.~~
15. Show gameplay lock/status in existing agent state text (`waiting_reply`, `in_game`, unavailable reason).
16. Add `updated Xs ago` after agent state text in Visitor List rows.
17. Disable repeated Play on same target while in `waiting_reply`.
18. Render public Gameplay Log (challenger/opponent, raw moves, outcome, timestamp).
19. Add Gameplay Log outcome colors (win=green, loss=red, draw=gray, timeout/rejected=amber).

## P3 — Ops and hardening

20. Add config constants with defaults:
   - `RPS_WAITING_REPLY_TIMEOUT_SECONDS=120`
   - `RPS_ALLOW_MULTI_MATCH_PER_AGENT=false`
   - `RPS_PUBLIC_GAME_LOG_RETENTION_DAYS=30`
21. Add retention cleanup job for public game log.
22. Add rate limiting and audit logging for challenge/reply paths.
