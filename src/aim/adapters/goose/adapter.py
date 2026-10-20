"""Goose adapter (Block / Agentic AI Foundation).

Layout: ~/.config/goose/{config.yaml, AGENTS.md, sessions/}
"""
from __future__ import annotations

from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem, Kind


@register
class GooseAdapter(Adapter):
    name = "goose"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(os.environ.get("GOOSE_CONFIG_DIR", str(Path(xdg) / "goose")))

    def detect(self, home: Path) -> bool:
        return (home / "config.yaml").is_file() or (home / "AGENTS.md").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        state.documents = read_docs(home, self.name, persona_paths=["AGENTS.md"], memory_globs=[])
        state.skills = load_skills(home, "skills", self.name)
        cfg = home / "config.yaml"
        if cfg.is_file():
            state.config = _flatten_yaml(cfg.read_text("utf-8"))
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home, persona_rel="AGENTS.md",
            memory_rel_fn=lambda d: d.path, dry_run=dry_run)
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="goose has no scheduler; stored in unsupported/jobs.json"))
            if not dry_run:
                import json
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        return gaps


def _flatten_yaml(text: str):
    from aim.canonical.models import ConfigEntry
    import yaml
    out: list[ConfigEntry] = []

    def walk(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        else:
            out.append(ConfigEntry(key=prefix, value=obj))

    try:
        walk("", yaml.safe_load(text) or {})
    except Exception:
        pass
    return out
