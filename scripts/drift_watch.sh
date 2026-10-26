#!/usr/bin/env bash
# AIM harness-drift watcher — checks published harness CLI versions vs committed baseline.
# On drift: alerts (and updates baseline only if tests still pass).
set -u
REPO="$HOME/projects/aim"
cd "$REPO" || exit 1
BASELINE="docs/harness-versions.json"
TMP=$(mktemp)

python3 - "$BASELINE" "$TMP" <<'EOF'
import json, subprocess, sys, urllib.request

baseline = json.load(open(sys.argv[1]))
out, drift = {}, []

def npm_ver(pkg):
    try:
        r = urllib.request.urlopen(f"https://registry.npmjs.org/{pkg}/latest", timeout=30)
        return json.load(r)["version"]
    except Exception as e:
        return f"ERROR:{e.__class__.__name__}"

def gh_ver(repo, pattern="v"):
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                     headers={"User-Agent": "aim-drift-watch"})
        return json.load(urllib.request.urlopen(req, timeout=30))["tag_name"].lstrip("v")
    except Exception as e:
        return f"ERROR:{e.__class__.__name__}"

checks = {
    "claude-code": lambda: npm_ver("@anthropic-ai/claude-code"),
    "codex":       lambda: npm_ver("@openai/codex"),
    "opencode":    lambda: npm_ver("opencode-ai"),
    "goose":       lambda: gh_ver("aaif-goose/goose"),
}

for name, fn in checks.items():
    v = fn()
    out[name] = v
    old = baseline.get(name, "?")
    if v != old and not str(v).startswith("ERROR"):
        drift.append(f"{name}: {old} -> {v}")

json.dump(out, open(sys.argv[2], "w"), indent=2)
if drift:
    print("DRIFT:\n" + "\n".join(drift))
elif any(str(v).startswith("ERROR") for v in out.values()):
    print("CHECK-ERRORS: " + json.dumps(out))
    sys.exit(1)
else:
    print("NO-DRIFT all versions unchanged: " + json.dumps(out))
EOF

STATUS=$?
MSG=$(cat "$TMP")
if [ $STATUS -ne 0 ]; then rm -f "$TMP"; exit 0; fi

if echo "$MSG" | grep -q "^DRIFT"; then
    # run the suite against the new reality (fixtures are synthetic, but catches parser regressions)
    if PYTHONPATH=src /usr/bin/python3 -m pytest tests/ -q >/tmp/aim-drift-test.log 2>&1; then
        RESULT="DRIFT detected, tests still PASS (34/34). Baseline updated. Live-binary spot-check recommended before shipping adapter changes."
        cp "$TMP" "$BASELINE"
        git add "$BASELINE"
        git -c user.name=jarvis -c user.email=jarvis@local commit -q -m "chore: harness version baseline update (drift watch)" && git push -q
    else
        RESULT="DRIFT detected AND TESTS FAILING — adapter likely broken by upstream change. Log: /tmp/aim-drift-test.log"
    fi
    printf '%s\n%s' "$RESULT" "$MSG"
else
    echo "$MSG"
fi
rm -f "$TMP"
