"""OpenCode adapter (v1.1: persona/skills, AGENTS.md standard).

Layout (researched 2026-10-15, opencode.ai docs v2):
  ~/.config/opencode/AGENTS.md          global instructions
  ~/.config/opencode/opencode.json(c)   global config
  ~/.config/opencode/skills/*/SKILL.md  global skills
  ~/.config/opencode/agents/*.md        agent definitions
  ~/.config/opencode/command/*.md       commands
"""
from __future__ import annotations

import json
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem, Kind


@register
class OpenCodeAdapter(Adapter):
    name = "opencode"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(os.environ.get("OPENCODE_CONFIG_DIR", str(Path(xdg) / "opencode")))

    def detect(self, home: Path) -> bool:
        return (home / "opencode.json").is_file() or (home / "opencode.jsonc").is_file() or (home / "AGENTS.md").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        docs = read_docs(home, self.name, persona_paths=["AGENTS.md"], memory_globs=[])
        # agent definitions + commands as docs
        for sub, kind in (("agents", Kind.profile), ("command", Kind.raw)):
            d = home / sub
            if d.is_dir():
                for f in sorted(d.glob("*.md")):
                    docs.append(_mk_doc(len(docs), str(f.relative_to(home)), kind,
                                        f.read_text("utf-8", "replace"), self.name))
        state.documents = docs
        state.skills = load_skills(home, "skills", self.name)
        # opencode.json config keys
        for name in ("opencode.json", "opencode.jsonc"):
            cj = home / name
            if cj.is_file():
                try:
                    data = json.loads(cj.read_text("utf-8"))
                    from aim.canonical.models import ConfigEntry
                    state.config = [ConfigEntry(key=k, value=v) for k, v in data.items()]
                except Exception:
                    pass
                break
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home,
            persona_rel="AGENTS.md",
            memory_rel_fn=lambda d: d.path,
            dry_run=dry_run,
        )
        # subagents -> agents/*.md (filename = agent name)
        if not dry_run:
            ad = home / "agents"
            ad.mkdir(parents=True, exist_ok=True)
            for d in state.documents:
                if d.kind == Kind.profile and not d.path.endswith("AGENTS.md"):
                    p = home / d.path
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(d.content, "utf-8")
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="opencode has no scheduler; stored in unsupported/jobs.json"))
            if not dry_run:
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        return gaps


def _mk_doc(idx: int, path: str, kind, content: str, harness: str):
    from aim.canonical.models import Document, Scope
    return Document(id=f"doc-{idx}", path=path, scope=Scope.user,
                    kind=kind, content=content, source_adapter=harness)
