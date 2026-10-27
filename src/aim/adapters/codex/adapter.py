"""Codex CLI adapter (v1.1: persona/skills/config, AGENTS.md standard).

Layout (researched 2026-10-15, learn.chatgpt.com + marginal.md):
  ~/.codex/AGENTS.md            global persona/instructions
  ~/.codex/config.toml          user config
  ~/.codex/skills/*/SKILL.md    skills (older location, still read)
  ~/.agents/skills/*/SKILL.md   skills (new .agents standard)
  ~/.codex/prompts/*.md         saved prompts (commands)
"""
from __future__ import annotations

import re
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import AgentState, Capability, GapItem, Kind


@register
class CodexAdapter(Adapter):
    EXTERNAL_PATHS = (".agents",)  # ~/.agents standard dir written during import
    name = "codex"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))

    def detect(self, home: Path) -> bool:
        return (home / "config.toml").is_file() or (home / "AGENTS.md").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        docs = read_docs(home, self.name, persona_paths=["AGENTS.md"], memory_globs=[])
        state.documents = docs
        skills = load_skills(home, "skills", self.name)
        # also pick up ~/.agents/skills (the .agents standard; lives OUTSIDE ~/.codex)
        agents_dir = home.parent / ".agents" / "skills"
        if agents_dir.is_dir():
            for d in sorted(agents_dir.iterdir()):
                if d.is_dir() and (d / "SKILL.md").is_file():
                    docs_paths = {s.name for s in skills}
                    if d.name not in docs_paths:
                        skills.append(_load_one_skill(d, self.name))
        state.skills = skills
        # config.toml -> flattened config entries (toml parsing best-effort)
        cfg = home / "config.toml"
        if cfg.is_file():
            state.config = _flatten_toml(cfg.read_text("utf-8"))
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home,
            persona_rel="AGENTS.md",
            memory_rel_fn=lambda d: d.path if d.kind == Kind.memory else d.path,
            dry_run=dry_run,
        )
        # skills also go to the .agents standard dir so Codex finds them either way
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
                import os as _os
                import re as _re
                for rel, blob in s.scripts.items():
                    f = _safe_relpath(d, rel, "skill script")
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(blob)
                    f.chmod(0o755)
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="codex has no scheduler; stored in unsupported/jobs.json"))
            if not dry_run:
                import json
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        return gaps


def _load_one_skill(d: Path, harness: str):
    from aim.canonical.models import Skill
    scripts: dict[str, bytes] = {}
    for f in sorted(d.rglob("*")):
        if f.is_file() and not f.is_symlink() and f.name != "SKILL.md" and "__pycache__" not in f.parts and not f.name.startswith("."):
            if f.stat().st_size < 512 * 1024:
                scripts[str(f.relative_to(d))] = f.read_bytes()
    return Skill(name=d.name, skill_md=(d / "SKILL.md").read_text("utf-8", "replace"), scripts=scripts)


def _flatten_toml(text: str) -> list:
    """Minimal TOML flattener for config capture: dotted keys for simple values."""
    from aim.canonical.models import ConfigEntry
    out: list[ConfigEntry] = []
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            section = m.group(1)
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+)$", line)
        if m:
            out.append(ConfigEntry(key=f"{section}.{m.group(1)}" if section else m.group(1),
                                   value=_toml_value(m.group(2))))
    return out


def _toml_value(raw: str):
    raw = raw.split(" #")[0].strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw
