#!/usr/bin/env bash
# AIM E2E container test — fully isolated from the host.
# Repo mounted READ-ONLY, workdir is a throwaway host dir, network disabled.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d /tmp/aim-e2e-XXXX)"
trap 'rm -rf "$WORK"' EXIT

echo "== workdir: $WORK"

docker run --rm --network none \
  -v "$REPO":/aim:ro \
  -v /tmp/aim-wheels:/wheels:ro \
  -v "$WORK":/work \
  -w /work \
  -e AIM_PASSPHRASE=test-pw \
  python:3.12-slim \
  bash -euo pipefail -c '
set -x
pip install --no-index --find-links /wheels cryptography pydantic click pyyaml pytest
export PYTHONPATH=/aim/src

# --- fixtures inside the container ---
mkdir -p /work/hermes-home/.hermes/memories /work/hermes-home/.hermes/skills/trading /work/hermes-home/.hermes/cron
cat > /work/hermes-home/.hermes/SOUL.md <<"EOF"
# Persona
Jarvis-style assistant. Careful, honest, concise.
EOF
cat > /work/hermes-home/.hermes/memories/MEMORY.md <<"EOF"
# Memory
User has a Telegram bot with token: 123456789:AAFfKxhV0lz6mR8jPw3nQ4eS5tUvWxYz2Ab
Prefers atomic facts. api_key = sk-ant-api03-AbCdEfGh12345678901234567890
EOF
cat > /work/hermes-home/.hermes/skills/trading/SKILL.md <<"EOF"
# trading
Manual patterns, bot guards, R-ledger.
EOF
cat > /work/hermes-home/.hermes/skills/trading/check_r.py <<"EOF"
print("R-ledger check")
EOF

# --- 1. export with secrets vault ---
cd /work
python3 -m aim.cli export --harness hermes --home /work/hermes-home/.hermes -o /work/mig.aim --with-secrets --passphrase test-pw

# --- 2. bundle must contain NO plaintext secrets ---
if grep -qa "AAFfKxhV\|sk-ant-api03" /work/mig.aim; then echo "FATAL: plaintext secret leaked into bundle"; exit 10; fi
echo "PASS: no plaintext secrets in bundle"

# --- 3. import into codex ---
python3 -m aim.cli import /work/mig.aim --harness codex --home /work/codex-home/.codex --force --passphrase test-pw
test -f /work/codex-home/.codex/AGENTS.md || { echo "FATAL: no AGENTS.md"; exit 11; }
test -f /work/codex-home/.codex/skills/trading/SKILL.md || { echo "FATAL: no skill"; exit 12; }
grep -q "123456789:AAFfKxhV" /work/codex-home/.codex/AGENTS.md /work/codex-home/.codex/memories/MEMORY.md 2>/dev/null || true
grep -rq "AAFfKxhV" /work/codex-home/ || { echo "FATAL: secret not restored"; exit 13; }
if grep -rq "sk-ant-api03" /work/codex-home/; then :; else echo "FATAL: api key not restored"; exit 14; fi
echo "PASS: codex import, secrets restored"

# --- 4. import into opencode ---
python3 -m aim.cli import /work/mig.aim --harness opencode --home /work/oc-home/.config/opencode --force --passphrase test-pw
test -f /work/oc-home/.config/opencode/AGENTS.md || { echo "FATAL: no AGENTS.md"; exit 15; }
echo "PASS: opencode import"

# --- 5. wrong passphrase must fail ---
if python3 -m aim.cli import /work/mig.aim --harness hermes --home /work/wrong-home --force --passphrase WRONG 2>/dev/null; then
  echo "FATAL: wrong passphrase accepted"; exit 16
fi
echo "PASS: wrong passphrase rejected"

# --- 6. container test suite (unit tests, no network) ---
cd /aim && PYTHONPATH=/aim/src python3 -m pytest tests/ -q

echo "=== ALL CONTAINER E2E CHECKS PASSED ==="
'
