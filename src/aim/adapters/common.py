"""Common helpers for adapters."""
from __future__ import annotations

import platform
import os
import re
from pathlib import Path

from aim.canonical.models import (
    AgentState,
    Capability,
    Document,
    GapItem,
    Job,
    Kind,
    Scope,
)


def source_os() -> str:
    s = platform.system()
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(s, s.lower())


def read_docs(home: Path, harness: str, persona_paths: list[str], memory_globs: list[str]) -> list[Document]:
    """Load persona + memory markdown docs verbatim as canonical Documents."""
    docs: list[Document] = []
    idx = 0
    for rel in persona_paths:
        p = home / rel
        if p.is_file() and not p.is_symlink():
            docs.append(Document(
                id=f"doc-{idx}", path=rel, scope=Scope.user,
                kind=Kind.persona, content=p.read_text("utf-8", "replace"),
                source_adapter=harness,
            ))
            idx += 1
    for pattern in memory_globs:
        for p in sorted(home.glob(pattern)):
            if p.is_symlink():
                continue  # never follow symlinks out of the home (audit opus #8)
            rel = str(p.relative_to(home)).replace("\\", "/")
            docs.append(Document(
                id=f"doc-{idx}", path=rel, scope=Scope.user,
                kind=Kind.memory, content=p.read_text("utf-8", "replace"),
                source_adapter=harness,
            ))
            idx += 1
    return docs


def load_skills(home: Path, skills_dir: str, harness: str):
    from aim.canonical.models import Skill

    skills = []
    base = home / skills_dir
    if not base.is_dir():
        return skills
    for skill_md in sorted(base.glob("*/SKILL.md")):
        if skill_md.is_symlink():
            continue
        name = skill_md.parent.name
        scripts = {}
        for f in skill_md.parent.rglob("*"):
            if f.is_symlink() or ".git" in f.parts:
                continue
            if f.name == "SKILL.md" or not f.is_file():
                continue
            # skip pycache, dotfiles, hidden dirs, big binaries, symlinks
            rel_parts = f.relative_to(skill_md.parent).parts
            if any(p.startswith(".") or p == "__pycache__" for p in rel_parts):
                continue
            if f.is_symlink() or f.stat().st_size > 512 * 1024:
                continue
            scripts[str(f.relative_to(skill_md.parent)).replace("\\", "/")] = f.read_bytes()
        skills.append(Skill(name=name, skill_md=skill_md.read_text("utf-8", "replace"), scripts=scripts))
    return skills


_WIN_RESERVED = re.compile(
    r"(?:^|[\\/])(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE
)


def is_safe_file(p: Path) -> bool:
    """True if p is a regular file AND not itself a symlink (export readers use this)."""
    try:
        return p.is_file() and not p.is_symlink()
    except OSError:
        return False


def write_nofollow(p: Path, data, mode: int | None = None) -> None:
    """Write text/bytes, refusing to follow a symlink at the final component."""
    if p.is_symlink():
        p.unlink()  # replace the link rather than writing through it (outside the transaction)
    if isinstance(data, str):
        p.write_text(data, "utf-8")
    else:
        p.write_bytes(data)
    if mode is not None:
        p.chmod(mode)


def _safe_relpath(home: Path, rel: str, what: str) -> Path:
    """Reject absolute paths, .., drive letters, UNC, Windows-reserved names,
    scheme-like names, trailing dots/spaces, and anything escaping home."""
    if not rel or "\x00" in rel:
        raise ValueError(f"invalid {what} path: {rel!r}")
    if ":" in rel or "\\" in rel:
        raise ValueError(f"colon/backslash in {what} path rejected: {rel!r}")
    if rel != rel.rstrip(". "):
        raise ValueError(f"trailing dot/space in {what} path: {rel!r}")
    if re.match(r"^[A-Za-z]:", rel) or rel.startswith(("/", "\\", "~")) or "://" in rel or rel.startswith("//") or ":" in rel.split("/")[0].split("\\")[0]:
        raise ValueError(f"absolute/UNC/scheme {what} path rejected: {rel!r}")
    if _WIN_RESERVED.search(rel):
        raise ValueError(f"Windows-reserved {what} path rejected: {rel!r}")
    p = (home / rel).resolve()
    if not str(p).startswith(str(home.resolve()) + os.sep) and p != home.resolve():
        raise ValueError(f"{what} path escapes target home: {rel!r}")
    return p


def write_common_import(state: AgentState, home: Path, persona_rel: str, memory_rel_fn, dry_run: bool) -> list[GapItem]:
    """Write persona+memory+skills into a target home; returns gap items."""
    gaps: list[GapItem] = []
    persona = next((d for d in state.documents if d.kind == "persona"), None)
    if persona:
        if not dry_run:
            p = home / persona_rel
            p.parent.mkdir(parents=True, exist_ok=True)
            write_nofollow(p, persona.content, mode=0o600)
        gaps.append(GapItem(item=f"persona:{persona_rel}", policy="native"))
    for d in state.documents:
        if d.kind.value == "persona":
            continue
        rel = memory_rel_fn(d)
        _low = rel.lower()
        if d.kind != Kind.persona and not (_low.endswith(".md") or _low.endswith(".txt")):
            raise ValueError(f"document path must be .md/.txt (not config): {rel!r}")
        if _low in {"settings.json", "config.toml", "config.yaml", "config.json",
                    ".credentials.yaml", "credentials.json", ".claude.json"} or rel == persona_rel:
            raise ValueError(f"document path clashes with harness config/persona: {rel!r}")
        if not dry_run:
            p = _safe_relpath(home, rel, "document")
            p.parent.mkdir(parents=True, exist_ok=True)
            write_nofollow(p, d.content, mode=0o600)
        gaps.append(GapItem(item=f"{d.kind.value}:{rel}", policy="native"))
    for s in state.skills:
        import re as _re2
        if not _re2.fullmatch(r"[A-Za-z0-9._-]+", s.name) or s.name in (".", ".."):
            raise ValueError(f"invalid skill name rejected: {s.name!r}")
        sdir = _safe_relpath(home / "skills", s.name, "skill name")
        if sdir.parent != (home / "skills").resolve():
            raise ValueError(f"skill name escapes skills/: {s.name!r}")
        if not dry_run:
            sdir.mkdir(parents=True, exist_ok=True)
            write_nofollow(sdir / "SKILL.md", s.skill_md, mode=0o600)
            for rel, blob in s.scripts.items():
                f = _safe_relpath(sdir, rel, "skill script")
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(blob)
                f.chmod(0o700)
        gaps.append(GapItem(item=f"skill:{s.name}", policy="native"))
    for j in state.jobs:
        gaps.append(GapItem(item=f"job:{j.name}", policy="park",
                            detail=f"automation target lacks scheduler support or adapter emulation; stored in unsupported/jobs.json"))
        if not dry_run:
            u = home / "unsupported"
            u.mkdir(parents=True, exist_ok=True)
            import json
            write_nofollow((u / "jobs.json"), json.dumps([j.model_dump() for j in state.jobs], indent=2), mode=0o600)
    return gaps


def base_capabilities(*caps: Capability) -> set[Capability]:
    return set(caps)
