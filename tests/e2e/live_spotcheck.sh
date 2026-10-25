#!/usr/bin/env bash
# AIM live spot-checks: real harness binaries, offline container.
# Image aim-live:2 was built WITH network (npm install) but these runs are --network none.
set -uo pipefail
export PATH="$PATH:/mnt/c/Program Files/Docker/Docker/resources/bin"
REPO=/home/hal/projects/aim
# Docker Desktop WSL-integration can drop after restarts; stage repo Windows-side (C: mounts always work)
STAGE=/mnt/c/Users/hal/aim-tmp
rm -rf "$STAGE" && mkdir -p "$STAGE" && cp -r "$REPO"/src "$REPO"/tests "$REPO"/pyproject.toml "$STAGE/"
REPO_MOUNT="C:\\Users\\hal\\aim-tmp"
WORK=/mnt/c/Users/hal/aim-work; rm -rf "$WORK"; mkdir -p "$WORK"
PASS=0; FAIL=0; declare -a RESULTS

run_offline() { docker.exe run --rm --network none -v "$REPO_MOUNT":/aim:ro -v "C:\\Users\\hal\\aim-work:/work" -w /work aim-live:2 bash -c "$1"; }

echo "== 0. binaries present =="
run_offline '
set -e
for b in claude codex opencode goose node python3; do command -v $b >/dev/null || { echo "MISSING $b"; exit 1; }; done
echo "binaries: $(claude --version 2>&1 | head -1) | $(codex --version 2>&1 | head -1) | $(opencode --version 2>&1 | head -1) | $(goose --version 2>&1 | head -1)"
' || { echo "FATAL: binaries missing"; exit 1; }

echo "== 1. build fixture bundle (hermes) =="
run_offline '
set -e
mkdir -p /work/src/.hermes/skills/demo /work/src/.hermes/memories
printf "# Persona\nLive spot-check persona SENTINEL-PERSONA-42\n" > /work/src/.hermes/SOUL.md
printf "# demo skill\nSentinel skill body\n" > /work/src/.hermes/skills/demo/SKILL.md
printf "# mem\natomic facts only\n" > /work/src/.hermes/memories/MEMORY.md
cd /work && python3 -m aim.cli export --harness hermes --home /work/src/.hermes -o /work/mig.aim
' || { echo "FATAL: export failed"; exit 1; }

check() { # name harness home_rel assert_cmd
  local name=$1 harness=$2 home=$3 assert=$4
  if out=$(run_offline "
    set -e
    python3 -m aim.cli import /work/mig.aim --harness $harness --home /work/tgt-$name/$home --force
    $assert
  " 2>&1); then
    RESULTS+=("PASS  $name"); PASS=$((PASS+1)); echo "$out" | tail -2
  else
    RESULTS+=("FAIL  $name"); FAIL=$((FAIL+1)); echo "---- $name FAILED ----"; echo "$out" | tail -8
  fi
}

# claude-code: binary must run offline (--version) and files intact
check claude-code claude-code .claude '
  claude --version >/dev/null 2>&1 || { echo "claude binary cannot run offline"; exit 1; }
  grep -q SENTINEL-PERSONA-42 /work/tgt-claude-code/.claude/CLAUDE.md
  grep -q "Sentinel skill body" /work/tgt-claude-code/.claude/skills/demo/SKILL.md
  echo "claude: files intact, binary runs"'

# codex: import + binary runs
check codex codex .codex '
  codex --version >/dev/null 2>&1 || { echo "codex binary cannot run"; exit 1; }
  grep -q SENTINEL-PERSONA-42 /work/tgt-codex/.codex/AGENTS.md
  grep -q "Sentinel skill body" /work/tgt-codex/.codex/skills/demo/SKILL.md
  echo "codex: files intact, binary runs"'

# opencode
check opencode opencode .config/opencode '
  opencode --version >/dev/null 2>&1 || { echo "opencode binary cannot run"; exit 1; }
  grep -q SENTINEL-PERSONA-42 /work/tgt-opencode/.config/opencode/AGENTS.md
  echo "opencode: files intact, binary runs"'

# goose: binary runs + config dir recognized
check goose goose .config/goose '
  goose --version >/dev/null 2>&1 || { echo "goose binary cannot run"; exit 1; }
  grep -q SENTINEL-PERSONA-42 /work/tgt-goose/.config/goose/AGENTS.md
  goose agent list >/dev/null 2>&1 || true   # may need auth; file layout is the check
  echo "goose: files intact, binary runs"'

echo; echo "===== RESULTS ====="
printf "%s\n" "${RESULTS[@]}"
echo "PASS=$PASS FAIL=$FAIL"
docker.exe run --rm -v /tmp:/tmp aim-live:2 rm -rf "$WORK" 2>/dev/null
[ $FAIL -eq 0 ] && echo "=== LIVE SPOT-CHECKS ALL GREEN ===" || exit 1
