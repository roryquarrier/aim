#!/usr/bin/env python3
"""AIM format canary — catches silent file-format drift.

Exports the hermes fixture to a bundle, imports it into scratch homes for every
adapter, and diffs the resulting file layout against docs/canary-golden.json.
Usage:
  canary.py update   — regenerate golden manifest (run when adapters change ON PURPOSE)
  canary.py check    — diff vs golden; exit 1 + print drift on mismatch
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(REPO / "tests")) if False else None

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# import cli module so adapter registry is populated
from aim import cli as aim_cli  # noqa: E402
from aim.adapters.base import all_adapters  # noqa: E402
from click.testing import CliRunner  # noqa: E402

TARGETS = ["claude-code", "codex", "opencode", "goose", "grok", "deepseek-harness", "roo", "buzz", "openclaw"]
GOLDEN = REPO / "docs" / "canary-golden.json"


def make_hermes_home(root: Path) -> Path:
    """Mirror of tests/test_roundtrip.py make_hermes_home (kept in sync by TestBackupRestore)."""
    import json as _json
    home = root / ".hermes"
    (home / "memories").mkdir(parents=True)
    (home / "skills" / "stitch-frontend").mkdir(parents=True)
    (home / "cron").mkdir(parents=True)
    (home / "SOUL.md").write_text("# Persona\nYou are Jarvis, concise technical expert.")
    (home / "memories" / "MEMORY.md").write_text("VAULT=halHermes;index.md 1st\nUSER: ESL teacher ages 5-12")
    (home / "memories" / "USER.md").write_text("USER: Rory, HK children market, sans-only design")
    (home / "config.yaml").write_text("agent:\n  name: jarvis\nauto_source_bashrc: true\n")
    (home / "skills" / "stitch-frontend" / "SKILL.md").write_text("# stitch-frontend\nUse Stitch CLI for designs.")
    (home / "skills" / "stitch-frontend" / "run.sh").write_bytes(b"#!/bin/bash\necho stitch\n")
    (home / "cron" / "jobs.json").write_text(_json.dumps({
        "jobs": [{"name": "Weekly memory prune", "schedule": "0 4 * * 0", "prompt": "prune memories", "enabled": True}]
    }))
    return home


def layout(home: Path) -> dict:
    out = {}
    for p in sorted(home.rglob("*")):
        rel = p.relative_to(home).as_posix()
        out[rel] = "dir" if p.is_dir() else "file"
    return out


def run(mode: str) -> int:
    runner = CliRunner()
    with tempfile.TemporaryDirectory(prefix="aim-canary-") as td:
        td = Path(td)
        bundle = td / "canary.aim"
        fx_home = make_hermes_home(td)
        r = runner.invoke(aim_cli.main, ["export", "--harness", "hermes",
                                         "--home", str(fx_home),
                                         "-o", str(bundle)], input="pw\npw\n")
        if r.exit_code != 0:
            print("CANARY FAIL: export step broken:", r.output[-400:])
            return 1
        result = {}
        for name in TARGETS:
            home = td / name.replace("-", "_")
            r = runner.invoke(aim_cli.main, ["import", str(bundle), "--harness", name,
                                             "--home", str(home), "--force"],  # scratch home
                              input="pw\n", env={"AIM_PASSPHRASE": "pw"})
            if r.exit_code != 0:
                print(f"CANARY FAIL: import into {name} broken:", r.output[-400:])
                return 1
            result[name] = layout(home)

        if mode == "update" or not GOLDEN.exists():
            GOLDEN.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
            print(f"golden updated: {GOLDEN} ({len(result)} harnesses)")
            return 0

        golden = json.loads(GOLDEN.read_text())
        drift = False
        for name in TARGETS:
            g, c = golden.get(name, {}), result.get(name, {})
            missing = set(g) - set(c)
            added = set(c) - set(g)
            if missing or added:
                drift = True
                print(f"DRIFT {name}:")
                for p in sorted(missing):
                    print(f"  - missing {p} ({g[p]})")
                for p in sorted(added):
                    print(f"  + new     {p} ({c[p]})")
        if not drift:
            print(f"NO-DRIFT: layouts match golden for {len(TARGETS)} harnesses")
            return 0
        print("CANARY DRIFT DETECTED — adapter layout changed; update golden ONLY if intended")
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "check"))
