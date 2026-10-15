"""Hermes Agent adapter (v1 layout — fixture-verified, SPEC §2.2)."""
from __future__ import annotations

import json
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem


@register
class HermesAdapter(Adapter):
    name = "hermes"
    capabilities = {
        Capability.cron, Capability.delivery_telegram, Capability.mcp_stdio,
        Capability.skills_scripts, Capability.persona_md,
    }

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

    def detect(self, home: Path) -> bool:
        return (home / "config.yaml").is_file() or (home / "SOUL.md").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(
            source_harness=self.name,
            source_os=source_os(),
        )
        state.documents = read_docs(
            home, self.name,
            persona_paths=["SOUL.md", "memories/USER.md"],
            memory_globs=["memories/MEMORY.md", "memories/*.md"],
        )
        # USER.md is profile, not persona — fix kinds; dedupe glob overlap
        from aim.canonical.models import Kind
        seen: dict[str, int] = {}
        deduped = []
        for d in state.documents:
            if d.path in seen:
                deduped[seen[d.path]] = d  # later (typed) copy wins
                continue
            seen[d.path] = len(deduped)
            deduped.append(d)
        for d in deduped:
            if d.path.endswith("USER.md"):
                d.kind = Kind.profile
        state.documents = deduped
        state.skills = load_skills(home, "skills", self.name)
        # cron jobs: single cron/jobs.json {"jobs":[...]} (verified live layout 2026-10-14)
        jobs = []
        jobs_file = home / "cron" / "jobs.json"
        if jobs_file.is_file():
            try:
                jobs = json.loads(jobs_file.read_text("utf-8")).get("jobs", [])
            except Exception:
                jobs = []
        from aim.canonical.models import Job

        def _sched(j: dict) -> str:
            s = j.get("schedule") or j.get("cron", "")
            if isinstance(s, dict):
                # live layout: {"kind": "cron", "expr": "0 3 * * 1", "display": ...}
                return s.get("expr") or s.get("display") or json.dumps(s)
            return str(s)

        state.jobs = [
            Job(
                name=j.get("name", f"job-{i}"),
                schedule=_sched(j),
                command=j.get("command") or j.get("prompt", ""),
                interpreter=j.get("interpreter", "hermes-cron"),
                deliver_to=j.get("deliver_to"),
                enabled=j.get("enabled", True),
            )
            for i, j in enumerate(jobs)
        ]
        # config: copy os-specific keys verbatim as entries
        cfg = home / "config.yaml"
        if cfg.is_file():
            import yaml
            try:
                data = yaml.safe_load(cfg.read_text("utf-8")) or {}
            except Exception:
                data = {}
            flat = []
            def walk(prefix, obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        walk(f"{prefix}.{k}" if prefix else str(k), v)
                else:
                    flat.append((prefix, obj))
            walk("", data)
            from aim.canonical.models import ConfigEntry
            state.config = [ConfigEntry(key=k, value=v, source="config.yaml") for k, v in flat]
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home,
            persona_rel="SOUL.md",
            memory_rel_fn=lambda d: d.path if not d.path.startswith("memories/") else d.path,
            dry_run=dry_run,
        )
        return gaps
