#!/usr/bin/env bash
set -euo pipefail

# Star Office UI - non-destructive release preflight
# Purpose: one-command regression checks before/after each stability phase

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${1:-http://127.0.0.1:18790}"

echo "[preflight] root=$ROOT_DIR"
echo "[preflight] base_url=$BASE_URL"

echo "\n[preflight] 1) python syntax check"
python3 -m py_compile backend/app.py backend/security_utils.py backend/store_utils.py scripts/security_check.py scripts/smoke_test.py

echo "\n[preflight] 2) security preflight"
python3 scripts/security_check.py

echo "\n[preflight] 3) smoke test"
python3 scripts/smoke_test.py --base-url "$BASE_URL"

echo "\n[preflight] PASS"
