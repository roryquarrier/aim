"""OpenClaw adapter (v1 layout — fixture-verified, SPEC §2.2)."""
from __future__ import annotations

import json
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem, Job


@register
class OpenClawAdapter(Adapter):
    name = "openclaw"
    capabilities = {
        Capability.cron, Capability.delivery_telegram, Capability.mcp_stdio,
        Capability.skills_scripts, Capability.persona_md,
    }

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))

    def detect(self, home: Path) -> bool:
        return (home / "openclaw.json").is_file() or (home / "workspace" / "SOUL.md").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        ws = home / "workspace" if (home / "workspace").is_dir() else home
        state.documents = read_docs(
            ws, self.name,
            persona_paths=["SOUL.md", "IDENTITY.md"],
            memory_globs=["MEMORY.md", "memory/*.md"],
        )
        state.skills = load_skills(ws, "skills", self.name)
        jobs = []
        cw = home / "cron-wrappers"
        if cw.is_dir():
            for f in sorted(cw.glob("*.json")):
                try:
                    jobs.append(json.loads(f.read_text("utf-8")))
                except Exception:
                    pass
        state.jobs = [
            Job(
                name=j.get("name", f"job-{i}"),
                schedule=j.get("schedule") or j.get("cron", ""),
                command=j.get("command", ""),
                deliver_to=j.get("deliver_to"),
            )
            for i, j in enumerate(jobs)
        ]
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        ws = home / "workspace"
        return write_common_import(
            state, ws,
            persona_rel="SOUL.md",
            memory_rel_fn=lambda d: f"memory/{Path(d.path).name}" if d.kind and d.path.startswith("memories/") else d.path,
            dry_run=dry_run,
        )
