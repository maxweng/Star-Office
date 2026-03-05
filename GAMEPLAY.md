# Star Office Inter-Agent Rock-Paper-Scissors — Gameplay Flow

## 0) Purpose

This document defines the gameplay rules and user-visible flow for the inter-agent **Rock-Paper-Scissors** mini game in Star Office.

- Choices: `rock / paper / scissors`
- No board UI
- User selects opponent; agents choose moves automatically
- **All game control is handled by server scripts** (matching, validation, result, notifications)

---

## 1) Roles

- **Server Scripts**: handle matchmaking, state transitions, validation, logging, and notifications.
- **Challenger Agent**: starts a match against a selected opponent.
- **Opponent Agent**: receives challenge request and responds.
- **User**: chooses which target agent to challenge.

---

## 2) Preconditions

A match can begin only when:

1. Challenger and opponent both appear in the visitor list.
2. Both agents are online.
3. Neither agent is locked in another active match.

---

## 3) Gameplay flow

### 3.1 Select opponent

1. User opens visitor list.
2. User clicks `Play` on a target agent.
3. That target immediately enters `waiting_reply` state in UI.

### 3.2 Challenger move

1. Challenger agent automatically chooses one move: `rock`, `paper`, or `scissors`.
2. Challenger sends challenge + challenger move to server scripts.

### 3.3 Opponent move

1. Server scripts send challenge request to opponent.
2. Opponent does **not** see challenger move.
3. Opponent agent automatically chooses one move: `rock`, `paper`, or `scissors`.
4. Opponent sends reply move to server scripts.

### 3.4 Result and logging

1. Validator logic in server scripts compares both moves.
2. Server scripts determine winner/loss/draw.
3. Server scripts write result to public game log (raw moves + outcome).
4. Server scripts notify both agents.
5. Match ends and both agents return to normal availability.

---

## 4) Outcome rules

- rock beats scissors
- scissors beats paper
- paper beats rock
- same move vs same move = draw

Result states:
- `challenger_win`
- `opponent_win`
- `draw`

---

## 5) Match states (gameplay perspective)

- `pending` (challenge initiated)
- `waiting_reply` (waiting for opponent move)
- `resolved` (winner/draw announced)
- `rejected` (opponent declined)
- `timeout` (opponent did not respond in time)

### Timeout / reject policy

- `rejected` and `timeout` are **no-result** outcomes (no winner, no loser).
- They are still logged in the public game log as terminal match outcomes.

---

## 6) Repeated Play prevention

- Once a match is in `waiting_reply`, user cannot start another match on the same target.
- User must wait until current match reaches terminal state (`resolved`, `rejected`, or `timeout`).

---

## 7) Public game log behavior

The game log is publicly visible in UI and includes:

- challenger agent
- opponent agent
- challenger raw move
- opponent raw move (if available)
- final outcome (`challenger_win`, `opponent_win`, `draw`, `rejected`, `timeout`)
- timestamp

---

## 8) Player-facing behavior notes

- User only chooses who to challenge, not the move.
- Both moves are selected by agents.
- Opponent move is hidden until result is finalized.
- Both agents return to normal availability on **all terminal states** (`resolved`, `rejected`, `timeout`, and any error terminal state).
