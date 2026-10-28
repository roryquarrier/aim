"""Roo Code adapter (VS Code extension + `roo` CLI).

Layout (verified from Roo-Code source + DoubleAgent path research 2026-10-16):
  ~/.roo/                       cross-editor global root
  ├── rules/*.md                global rules -> memory docs
  ├── rules-{mode}/*.md         mode-specific rules -> profile docs
  ├── commands/*.md             slash commands
  ├── skills/*/SKILL.md         global skills (also reads ~/.agents/skills)
  └── cli-settings.json         provider/model/mode/permissions (defaultMode!)
  <editor>/globalStorage/rooveterinaryinc.roo-cline/settings/
  ├── custom_modes.yaml         global custom modes (roleDefinition = persona)
  └── mcp_settings.json         MCP servers
Persona = roleDefinition of the mode named by cli-settings defaultMode (fallback:
first custom mode, fallback built-in 'code'). Provider keys -> vault via redaction scan.
"""
from __future__ import annotations

import json
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, source_os, write_common_import
from aim.canonical.models import (AgentState, Capability, ConfigEntry, Document, GapItem, Kind, Scope)


@register
class RooAdapter(Adapter):
    name = "roo"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("ROO_HOME", str(Path.home() / ".roo")))

    def _editor_storage(self) -> Path | None:
        """Probe the three editor globalStorage paths on this OS (ROO_EDITOR_STORAGE overrides)."""
        import os
        override = os.environ.get("ROO_EDITOR_STORAGE")
        if override:
            p = Path(override)
            return p if p.is_dir() else None
        home = Path.home()
        cands = []
        sysname = os.uname().sysname if hasattr(os, "uname") else ""
        if sysname == "Darwin":
            base = home / "Library" / "Application Support"
        elif sysname.startswith("Windows") or "Windows" in sysname:
            base = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        for editor in ("Code", "Cursor", "Windsurf"):
            cands.append(base / editor / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings")
        for c in cands:
            if (c / "custom_modes.yaml").is_file() or (c / "mcp_settings.json").is_file():
                return c
        return None

    def detect(self, home: Path) -> bool:
        return (home / "cli-settings.json").is_file() or (home / "rules").is_dir() \
            or (home / "skills").is_dir() or self._editor_storage() is not None

    def export(self, home: Path) -> AgentState:
        import yaml
        state = AgentState(source_harness=self.name, source_os=source_os())
        docs: list[Document] = []
        idx = 0

        modes: list[dict] = []
        est = self._editor_storage()
        if est and (est / "custom_modes.yaml").is_file():
            try:
                modes = (_safe_yaml_load((est / "custom_modes.yaml").read_text("utf-8")) or {}).get("customModes", [])
            except Exception:
                modes = []
        # persona: defaultMode from cli-settings, else first custom mode, else builtin 'code'
        default_mode = "code"
        cs = home / "cli-settings.json"
        if cs.is_file():
            try:
                default_mode = json.loads(cs.read_text("utf-8")).get("mode", default_mode)
            except Exception:
                pass
        persona_mode = next((m for m in modes if m.get("slug") == default_mode), None)
        if persona_mode is None and modes:
            persona_mode = modes[0]
        if persona_mode:
            docs.append(Document(
                id=f"doc-{idx}", path="personas/default-mode.md", scope=Scope.user,
                kind=Kind.persona,
                content=persona_mode.get("roleDefinition", ""), source_adapter=self.name))
            idx += 1
        # other modes -> profile docs (verbatim yaml block for lossless groups)
        for m in modes:
            if m is persona_mode:
                continue
            docs.append(Document(
                id=f"doc-{idx}", path=f"modes/{m.get('slug', idx)}.md", scope=Scope.user,
                kind=Kind.profile,
                content=f"---\n{yaml.safe_dump(m, sort_keys=False)}---\n{m.get('customInstructions', '')}",
                source_adapter=self.name))
            idx += 1
        # ~/.roo/rules -> memory; rules-{mode} -> profile
        rules = home / "rules"
        if rules.is_dir():
            for f in sorted(rules.glob("*.md")):
                if f.is_symlink():
                    continue
                docs.append(Document(
                    id=f"doc-{idx}", path=f"rules/{f.name}", scope=Scope.user,
                    kind=Kind.memory, content=f.read_text("utf-8", "replace"), source_adapter=self.name))
                idx += 1
        for d in sorted(home.glob("rules-*")):
            if d.is_dir():
                for f in sorted(d.glob("*.md")):
                    if f.is_symlink():
                        continue
                    docs.append(Document(
                        id=f"doc-{idx}", path=(d.name + "/" + f.name), scope=Scope.user,
                        kind=Kind.profile, content=f.read_text("utf-8", "replace"), source_adapter=self.name))
                    idx += 1
        # commands -> raw
        cmds = home / "commands"
        if cmds.is_dir():
            for f in sorted(cmds.glob("*.md")):
                if f.is_symlink():
                    continue
                docs.append(Document(
                    id=f"doc-{idx}", path=f"commands/{f.name}", scope=Scope.user,
                    kind=Kind.raw, content=f.read_text("utf-8", "replace"), source_adapter=self.name))
                idx += 1
        state.documents = docs
        state.skills = load_skills(home, "skills", self.name)
        # config: cli-settings.json + mcp_settings.json (editor storage wins only if ~/.roo lacks it —
        # mcp_settings lives only in editor storage today)
        cfg: list[ConfigEntry] = []
        if cs.is_file():
            try:
                for k, v in json.loads(cs.read_text("utf-8")).items():
                    cfg.append(ConfigEntry(key=f"cli.{k}", value=v))
            except Exception:
                pass
        if est and (est / "mcp_settings.json").is_file():
            try:
                mcp = json.loads((est / "mcp_settings.json").read_text("utf-8"))
                for name, srv in (mcp.get("mcpServers") or {}).items():
                    cfg.append(ConfigEntry(key=f"mcp.{name}", value=srv))
            except Exception:
                pass
        state.config = cfg
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home, persona_rel="rules/imported-persona.md",
            memory_rel_fn=lambda d: d.path, dry_run=dry_run)
        # write modes + persona into ~/.roo/modes/custom_modes.yaml (cross-editor target,
        # per Roo roadmap; harmless today, canonical tomorrow)
        if not dry_run:
            import yaml
            modes_dir = home / "modes"
            modes_dir.mkdir(parents=True, exist_ok=True)
            personas = [d for d in state.documents if d.kind == Kind.persona]
            others = [d for d in state.documents if d.kind == Kind.profile and d.path.startswith("modes/")]
            cm = []
            for p in personas:
                cm.append({"slug": "imported-persona", "name": "Imported Persona",
                           "roleDefinition": p.content, "groups": ["read", "edit"]})
            for o in others:
                try:
                    body = o.content.split("---\n")[1] if o.content.startswith("---\n") else ""
                    parsed = _safe_yaml_load(body) if body else {}
                    if isinstance(parsed, dict):
                        cm.append(parsed)
                except Exception:
                    pass
            (modes_dir / "custom_modes.yaml").write_text(
                yaml.safe_dump({"customModes": cm}, sort_keys=False), "utf-8")
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="roo has no scheduler; stored in unsupported/jobs.json"))
            if not dry_run:
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        gaps.append(GapItem(
            item="roo-editor-storage", policy="warn",
            detail="modes written to ~/.roo/modes/custom_modes.yaml (cross-editor). Extension "
                   "reads editor globalStorage today; copy the file there if the extension "
                   "doesn't pick it up (open issue RooCodeInc#10750)."))
        return gaps

def _safe_yaml_load(text: str):
    """yaml.safe_load with alias-expansion ('billion laughs') guard."""
    import yaml
    from yaml.events import AliasEvent

    class _L(yaml.SafeLoader):
        _alias_n = 0

        def compose_node(self, parent, index):
            if self.check_event(AliasEvent):
                _L._alias_n += 1
                if _L._alias_n > 100:
                    raise ValueError("too many YAML aliases (alias bomb?)")
            return super().compose_node(parent, index)

    return yaml.load(text, Loader=_L)
