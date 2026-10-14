"""OS adjustments overlay (SPEC §1.2) + running-harness detection + transactional import."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ADJUSTMENTS: dict[str, list[tuple[str, str, str]]] = {
    # target_os: [(key_substring, new_yaml_fragment, reason)]
    "macos": [
        ("auto_source_bashrc: true", "auto_source_bashrc: false", "macOS uses .zshrc/.bash_profile"),
    ],
    "windows": [
        ("auto_source_bashrc: true", "auto_source_bashrc: false", "Windows has no .bashrc"),
        ("persistent_shell: true", "persistent_shell: false", "Windows shell model"),
    ],
}


def target_os() -> str:
    s = platform.system()
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(s, s.lower())


def apply_adjustments(config_text: str) -> tuple[str, list[str]]:
    notes = []
    for old, new, reason in ADJUSTMENTS.get(target_os(), []):
        if old in config_text:
            config_text = config_text.replace(old, new)
            notes.append(f"{old} -> {new} ({reason})")
    return config_text, notes


def path_map(args: list[str]) -> dict[str, str]:
    """Parse --map src=dst pairs."""
    m = {}
    for a in args or []:
        if "=" in a:
            src, dst = a.split("=", 1)
            m[src] = dst
    return m


def remap_text(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    n = 0
    for src, dst in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        if src in text:
            n += text.count(src)
            text = text.replace(src, dst)
    return text, n


def harness_running(harness: str) -> bool:
    """Detect a live harness/gateway process we'd collide with (SPEC §3)."""
    probes = {
        "hermes": ["hermes"],
        "openclaw": ["openclaw", "openclaude"],
        "claude-code": [],
    }.get(harness, [])
    me = Path(sys.argv[0]).name
    try:
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return False  # can't check (e.g. Windows without ps) — don't block
    for line in out.splitlines():
        if not line.strip() or f" {me}" in line or line.startswith("ps -eo"):
            continue
        for probe in probes:
            if probe in line and "aim" not in line:
                return True
    return False


def snapshot_home(home: Path) -> Path | None:
    """0600 backup of target home before import (SPEC §3)."""
    if not home.exists():
        return None
    import time
    bak = home.parent / f"{home.name}.aimbak.{int(time.time())}"
    shutil.copytree(home, bak)
    for root, dirs, files in os.walk(bak):
        for d in dirs:
            os.chmod(Path(root) / d, 0o700)
        for f in files:
            os.chmod(Path(root) / f, 0o600)
    os.chmod(bak, 0o700)
    return bak


def transactional_import(home: Path, stage_fn, dry_run: bool = False) -> Path | None:
    """Stage into temp dir next to target, then atomic rename swap (SPEC §3)."""
    if dry_run:
        stage_fn(home)  # adapters in dry-run write nothing
        return None
    home.parent.mkdir(parents=True, exist_ok=True)
    staging = home.parent / f".{home.name}.aimstage.{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    if home.exists():
        shutil.copytree(home, staging)
    else:
        staging.mkdir()
    stage_fn(staging)
    bak = snapshot_home(home)
    if home.exists():
        tmp_old = home.parent / f".{home.name}.aimold.{os.getpid()}"
        home.rename(tmp_old)
        staging.rename(home)
        shutil.rmtree(tmp_old)
    else:
        staging.rename(home)
    return bak
