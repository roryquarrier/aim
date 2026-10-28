"""Claude Code adapter (v1: persona/memory/skills/MCP source + target, SPEC §5.1)."""
from __future__ import annotations

import json
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, read_docs, source_os, write_common_import
from aim.canonical.models import (
    AgentState, Capability, ConfigEntry, GapItem, Kind, MCPBinding, Scope, Document,
)


@register
class ClaudeCodeAdapter(Adapter):
    EXTERNAL_PATHS = (".claude.json",)  # files written in home.parent during import
    name = "claude-code"
    capabilities = {Capability.mcp_stdio, Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        return Path.home() / ".claude"

    def detect(self, home: Path) -> bool:
        return (home.parent / ".claude.json").is_file() or (home / "CLAUDE.md").is_file()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        # user scope
        docs = read_docs(home, self.name, persona_paths=["CLAUDE.md"], memory_globs=[])
        # project-scope auto memory: ~/.claude/projects/<path-encoded-cwd>/memory/*.md
        projects = home / "projects"
        idx = len(docs)
        if projects.is_dir():
            for memdir in sorted(projects.glob("*/memory")):
                workspace_id = memdir.parent.name  # path-encoded cwd — re-keyed on import via --map
                for f in sorted(memdir.glob("*.md")):
                    if f.is_symlink():
                        continue
                    docs.append(Document(
                        id=f"doc-{idx}", path=str(f.relative_to(home)).replace("\\", "/"),
                        scope=Scope.workspace, workspace_id=workspace_id,
                        kind=Kind.memory, content=f.read_text("utf-8", "replace"),
                        source_adapter=self.name,
                    ))
                    idx += 1
        state.documents = docs
        state.skills = load_skills(home, "skills", self.name)
        # MCP from .claude.json (user scope) — mcpServers blocks
        cj = home.parent / ".claude.json"  # real location: ~/.claude.json (sibling of ~/.claude)
        if cj.is_file():
            try:
                data = json.loads(cj.read_text("utf-8"))
                servers = data.get("mcpServers", {}) or {}
                state.mcp = [
                    MCPBinding(
                        name=n,
                        transport="stdio",
                        command=s.get("command"),
                        args=s.get("args", []),
                        env_refs=s.get("env", {}),
                    )
                    for n, s in servers.items()
                ]
            except Exception:
                pass
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home,
            persona_rel="CLAUDE.md",
            memory_rel_fn=lambda d: d.path,
            dry_run=dry_run,
        )
        # merge MCP into .claude.json (preserve existing); always ensure the file exists
        cj = home.parent / ".claude.json"  # real location: ~/.claude.json (sibling of ~/.claude)
        data = {}
        if cj.is_file():
            try:
                data = json.loads(cj.read_text("utf-8"))
            except Exception:
                data = {}
        servers = data.setdefault("mcpServers", {})
        for b in state.mcp:
            servers[b.name] = {"command": b.command, "args": b.args, "env": b.env_refs}
            gaps.append(GapItem(item=f"mcp:{b.name}", policy="native"))
        if not dry_run:
            cj.write_text(json.dumps(data, indent=2), "utf-8")
        if state.jobs:
            gaps.append(GapItem(item="jobs", policy="park",
                                detail="claude-code has no scheduler; stored in unsupported/jobs.json"))
            if not dry_run:
                u = home / "unsupported"
                u.mkdir(parents=True, exist_ok=True)
                (u / "jobs.json").write_text(json.dumps([j.model_dump() for j in state.jobs], indent=2), "utf-8")
        return gaps
