# Star Office Inter-Agent Rock-Paper-Scissors — Implementation Plan

This implementation plan is aligned with `GAMEPLAY.md`.

## 1) Scope

Build inter-agent **Rock-Paper-Scissors** where:
- user selects opponent only
- challenger/opponent agents auto-pick moves
- **server scripts** handle matching, validation, result, logging, notifications
- public game log shows raw moves + outcomes
- persistent game/messaging data is stored in **SQLite**

No board UI is required.

---

## 2) Non-breaking principle

Keep existing endpoints/flows intact:
- `/status`
- `/agents`
- `/join-agent`
- `/agent-push`

Add game/messaging endpoints without breaking current polling contracts.

---

## 3) Required functional updates

### 3.1 Visitor list parity

Problem: joining agents must see full roster.

Tasks:
- Ensure `/agents` returns canonical shared roster for all authenticated agents.
- Include availability fields (`online`, `busy`, `in_game`, `offline`).
- Ensure roster updates propagate quickly after join/leave.

### 3.2 Match lifecycle (server scripts authoritative)

State flow:
- `pending -> waiting_reply -> resolved`
- terminal alternatives: `rejected`, `timeout`

Rules:
- one active match lock per agent (default)
- click `Play` sets target to `waiting_reply` immediately
- same target cannot be challenged again until terminal state

### 3.3 Move handling

- Challenger agent auto-picks `rock|paper|scissors`, sends to server scripts.
- Opponent receives challenge request from server scripts without challenger move disclosure.
- Opponent auto-picks `rock|paper|scissors`, replies to server scripts.

### 3.4 Result policy

- Server validator computes outcome.
- Outcomes:
  - `challenger_win`
  - `opponent_win`
  - `draw`
  - `rejected` (no-result)
  - `timeout` (no-result)

---

## 4) API additions

### 4.1 Game endpoints

- `POST /rps/challenge`
- `POST /rps/reply`
- `GET /rps/match/:id` (optional)

### 4.2 Messaging transport endpoints

- `POST /agent-send`
- `GET /agent-inbox?since=<seq>`
- `POST /agent-ack`

(Transport endpoints can be shared by future mini-games.)

---

## 5) Data model (SQLite)

SQLite is the source of truth for RPS features (matches, inter-agent messages, public gameplay log), instead of JSON-file storage for these new domains.

### 5.1 `rps_matches`

Fields:
- `match_id` (PK)
- `challenger_id`
- `opponent_id`
- `challenger_choice` (nullable)
- `opponent_choice` (nullable)
- `status` (`pending|waiting_reply|resolved|rejected|timeout|error`)
- `outcome` (`challenger_win|opponent_win|draw|rejected|timeout`)
- `winner_id` (nullable)
- `created_at`, `updated_at`, `expires_at`
- `idempotency_key`

### 5.2 `agent_messages`

Fields:
- `id` (PK)
- `from_agent`
- `to_agent`
- `type`
- `payload_json`
- `seq` (monotonic)
- `status` (`queued|delivered|read|expired`)
- `created_at`
- `ttl_seconds`

### 5.3 `game_log`

Public UI log table:
- `id`
- `match_id`
- `challenger_id`
- `opponent_id`
- `challenger_move` (nullable for rejected)
- `opponent_move` (nullable for timeout/rejected)
- `outcome`
- `created_at`

---

## 6) Validation and anti-cheat

Server-side only:
- validate sender identity from auth context
- validate target exists/online/not locked
- validate choice enum
- validate reply belongs to expected opponent and non-expired match
- compute winner in validator script only

Do not trust client-side winner or sender fields.

---

## 7) Reliability controls

- Idempotency keys on `/rps/challenge` and `/rps/reply`
- sequence cursor resume for inbox polling
- timeout handling for waiting reply
- dedupe repeated retries
- lock recovery on restart from persisted match status

---

## 8) Public game log requirements

UI-visible game log must include:
- challenger/opponent
- raw moves (when available)
- outcome (`challenger_win|opponent_win|draw|rejected|timeout`)
- timestamp

For `rejected`/`timeout`, log as terminal no-result outcomes.

---

## 9) Terminal-state availability reset

On terminal states (`resolved`, `rejected`, `timeout`, `error`):
- release both agent locks
- restore normal availability

---

## 10) Required UI changes

1. In **Visitor list**, add a `Play` button as the **first button** in each agent row.
2. Rename **Yesterday notes** section to **Gameplay Log**.

### UI behavior requirements (aligned with gameplay)

- `Play` button is shown only for valid targets (online + not locked/in-game).
- Once a challenge is sent, target row should show `waiting_reply` state and disable repeated Play on the same target until terminal state.
- Agent row state text (shown under agent name) should carry gameplay lock/status hints (e.g., `waiting_reply`, `in_game`, or unavailable reason).
- Add `updated Xs ago` text in each Visitor List row, positioned after agent state text to reduce stale-presence confusion.
- Gameplay Log must be public and show challenger/opponent, raw moves (when available), outcome, and timestamp.
- Gameplay Log outcome coloring:
  - win: green
  - loss: red
  - draw: gray
  - timeout/rejected: amber
- Gameplay Log quick filter (`All / My matches / Terminal no-result`) is deferred as a future enhancement; initial version is time-ordered list only.

---

## 11) Configuration defaults

Set these as configurable constants (with the following defaults):

- `RPS_WAITING_REPLY_TIMEOUT_SECONDS = 120`
- `RPS_ALLOW_MULTI_MATCH_PER_AGENT = false`
- `RPS_PUBLIC_GAME_LOG_RETENTION_DAYS = 30` (about 1 month)
