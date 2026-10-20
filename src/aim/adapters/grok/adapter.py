"""Grok Build adapter (xAI `grok` CLI).

Layout: ~/.grok/ — AGENTS.md/GROK.md persona, settings.json, SKILL.md standard skills.
XAI_API_KEY lives in env/auth file -> vault only. Exact CLI home filenames pinned
against installed CLI at implementation; detect() is tolerant of both.
"""
from __future__ import annotations

import json
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem


@register
class GrokAdapter(Adapter):
    name = "grok"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok")))

    def detect(self, home: Path) -> bool:
        return (home / "AGENTS.md").is_file() or (home / "GROK.md").is_file() or (home / "settings.json").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        persona = "GROK.md" if (home / "GROK.md").is_file() else "AGENTS.md"
        state.documents = read_docs(home, self.name, persona_paths=[persona], memory_globs=[])
        state.skills = load_skills(home, "skills", self.name)
        sj = home / "settings.json"
        if sj.is_file():
            from aim.canonical.models import ConfigEntry
            try:
                data = json.loads(sj.read_text("utf-8"))
                state.config = [ConfigEntry(key=k, value=v) for k, v in data.items()]
            except Exception:
                pass
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        persona = "GROK.md" if (home / "GROK.md").is_file() else "AGENTS.md"
        gaps = write_common_import(
            state, home, persona_rel=persona,
            memory_rel_fn=lambda d: d.path, dry_run=dry_run)
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="grok has no scheduler; stored in unsupported/jobs.json"))
            if not dry_run:
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        return gaps
