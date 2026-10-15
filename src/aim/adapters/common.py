"""Common helpers for adapters."""
from __future__ import annotations

import platform
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
        if p.is_file():
            docs.append(Document(
                id=f"doc-{idx}", path=rel, scope=Scope.user,
                kind=Kind.persona, content=p.read_text("utf-8", "replace"),
                source_adapter=harness,
            ))
            idx += 1
    for pattern in memory_globs:
        for p in sorted(home.glob(pattern)):
            rel = str(p.relative_to(home))
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
        name = skill_md.parent.name
        scripts = {}
        for f in skill_md.parent.rglob("*"):
            if f.name == "SKILL.md" or not f.is_file():
                continue
            # skip pycache, dotfiles, hidden dirs, big binaries, symlinks
            rel_parts = f.relative_to(skill_md.parent).parts
            if any(p.startswith(".") or p == "__pycache__" for p in rel_parts):
                continue
            if f.is_symlink() or f.stat().st_size > 512 * 1024:
                continue
            scripts[str(f.relative_to(skill_md.parent))] = f.read_bytes()
        skills.append(Skill(name=name, skill_md=skill_md.read_text("utf-8", "replace"), scripts=scripts))
    return skills


def write_common_import(state: AgentState, home: Path, persona_rel: str, memory_rel_fn, dry_run: bool) -> list[GapItem]:
    """Write persona+memory+skills into a target home; returns gap items."""
    gaps: list[GapItem] = []
    persona = next((d for d in state.documents if d.kind == "persona"), None)
    if persona:
        if not dry_run:
            p = home / persona_rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(persona.content, "utf-8")
        gaps.append(GapItem(item=f"persona:{persona_rel}", policy="native"))
    for d in state.documents:
        if d.kind.value == "persona":
            continue
        rel = memory_rel_fn(d)
        if not dry_run:
            p = home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(d.content, "utf-8")
        gaps.append(GapItem(item=f"{d.kind.value}:{rel}", policy="native"))
    for s in state.skills:
        sdir = home / "skills" / s.name
        if not dry_run:
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "SKILL.md").write_text(s.skill_md, "utf-8")
            for rel, blob in s.scripts.items():
                f = sdir / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(blob)
                f.chmod(0o755)
        gaps.append(GapItem(item=f"skill:{s.name}", policy="native"))
    for j in state.jobs:
        gaps.append(GapItem(item=f"job:{j.name}", policy="park",
                            detail=f"automation target lacks scheduler support or adapter emulation; stored in unsupported/jobs.json"))
        if not dry_run:
            u = home / "unsupported"
            u.mkdir(parents=True, exist_ok=True)
            import json
            (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
    return gaps


def base_capabilities(*caps: Capability) -> set[Capability]:
    return set(caps)
