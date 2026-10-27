"""DeepSeek Harness (dsh) adapter.

Layout ($DSH_HOME, default ~/.dsh) — verified from dsh docs 2026-10-16:
  AGENTS.md              user-global persona (fixed path)
  settings.yaml          global settings
  .credentials.yaml      API keys — VAULT ONLY, never state.json
  cordis.patch.yml       home-level plugin patch layer
  skills/*/SKILL.md      local skill root (rank 400); also ~/.agents/skills
  profiles/<name>/       package.json + cordis.patch.yml (skip node_modules)
  session logs           opaque (Zstd JSONL) — opt-in blobs only
"""
from __future__ import annotations

from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem, Kind, Scope, Document


@register
class DeepseekHarnessAdapter(Adapter):
    EXTERNAL_PATHS = (".agents",)  # ~/.agents standard dir written during import
    name = "deepseek-harness"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh")))

    def detect(self, home: Path) -> bool:
        return ((home / "settings.yaml").is_file() or (home / "cordis.patch.yml").is_file()
                or (home / "AGENTS.md").is_file())

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        state.documents = read_docs(home, self.name, persona_paths=["AGENTS.md"], memory_globs=[])
        # profiles: package.json + cordis.patch.yml as raw docs (reproducible profile rebuild)
        idx = len(state.documents)
        prof_root = home / "profiles"
        if prof_root.is_dir():
            for p in sorted(prof_root.iterdir()):
                if not p.is_dir():
                    continue
                for fname in ("package.json", "cordis.patch.yml"):
                    f = p / fname
                    if f.is_file():
                        state.documents.append(Document(
                            id=f"doc-{idx}", path=f"profiles/{p.name}/{fname}",
                            scope=Scope.user, kind=Kind.raw,
                            content=f.read_text("utf-8", "replace"), source_adapter=self.name))
                        idx += 1
        state.skills = load_skills(home, "skills", self.name)
        # settings.yaml + home cordis.patch.yml -> config
        cfg = []
        for fname in ("settings.yaml", "cordis.patch.yml"):
            f = home / fname
            if f.is_file():
                cfg.append((fname, f.read_text("utf-8")))
        state.config = _parse_multi(cfg)
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home, persona_rel="AGENTS.md",
            memory_rel_fn=lambda d: d.path, dry_run=dry_run)
        # skills also to ~/.agents/skills standard
        if not dry_run:
            from aim.adapters.common import _safe_relpath
            agents_skills = home.parent / ".agents" / "skills"
            agents_skills.mkdir(parents=True, exist_ok=True)
            for s in state.skills:
                if s.name in (".", ".."):
                    raise ValueError(f"invalid skill name rejected: {s.name!r}")
                d = _safe_relpath(agents_skills, s.name, "skill name")
                d.mkdir(parents=True, exist_ok=True)
                (d / "SKILL.md").write_text(s.skill_md, "utf-8")
                for rel, blob in s.scripts.items():
                    f = _safe_relpath(d, rel, "skill script")
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(blob)
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="dsh schedule plugin config not auto-written; jobs in unsupported/jobs.json"))
            if not dry_run:
                import json
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        return gaps


def _parse_multi(items):
    from aim.canonical.models import ConfigEntry
    import yaml
    out: list[ConfigEntry] = []

    def walk(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(obj, list):
            out.append(ConfigEntry(key=prefix, value=obj))
        else:
            out.append(ConfigEntry(key=prefix, value=obj))

    for fname, text in items:
        try:
            data = yaml.safe_load(text)
        except Exception:
            continue
        ns = "patch" if fname.startswith("cordis") else ""
        if isinstance(data, list):  # patch layers are lists of inserts/overrides
            out.append(ConfigEntry(key="cordis.patch" if ns else fname, value=data))
        else:
            walk(ns, data or {})
    return out
