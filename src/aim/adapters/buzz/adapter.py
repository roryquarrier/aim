"""Buzz adapter (Block — relay workspace where humans and agents share channels).

An agent's identity in Buzz = persona pack / managed-agent system-prompt + Nostr keypair
(BUZZ_PRIVATE_KEY — vault only, unrecoverable) + relay membership. Migration moves the
persona/skills/workflows; chat history stays on the relay.

Layout (OSS block/buzz, pinned 2026-10-16):
  $BUZZ_HOME (default ~/.buzz)
  ├── personas/*/persona.md        # agent persona packs
  ├── agents/*.yaml                # managed agents: display-name, system-prompt, runtime, provider, model
  ├── workflows/*.yaml             # buzz-workflow YAML (schedule/message/webhook triggers)
  └── skills/*/SKILL.md            # SKILL.md standard (nest_skill format)
Env secrets: BUZZ_PRIVATE_KEY (Nostr nsec/hex), BUZZ_AUTH_TAG, BUZZ_RELAY_URL
"""
from __future__ import annotations

import re
from pathlib import Path

from aim.adapters.base import Adapter, register
from aim.adapters.common import load_skills, source_os, write_common_import
from aim.canonical.models import (AgentState, Capability, ConfigEntry, Document, GapItem, Kind, Scope)


@register
class BuzzAdapter(Adapter):
    name = "buzz"
    capabilities = {Capability.skills_scripts, Capability.persona_md}

    def default_home(self) -> Path:
        import os
        return Path(os.environ.get("BUZZ_HOME", str(Path.home() / ".buzz")))

    def detect(self, home: Path) -> bool:
        return (home / "agents").is_dir() or (home / "personas").is_dir() or (home / "workflows").is_dir()

    def export(self, home: Path) -> AgentState:
        state = AgentState(source_harness=self.name, source_os=source_os())
        docs: list[Document] = []
        idx = 0
        # persona packs -> persona doc (first) + profile docs (rest)
        personas = home / "personas"
        first_persona = True
        if personas.is_dir():
            for f in sorted(personas.rglob("*.md")):
                if f.is_symlink():
                    continue
                docs.append(Document(
                    id=f"doc-{idx}", path=str(f.relative_to(home)).replace("\\", "/"),
                    scope=Scope.user, kind=Kind.persona if first_persona else Kind.profile,
                    content=f.read_text("utf-8", "replace"), source_adapter=self.name))
                idx += 1
                first_persona = False
        # managed agents -> profile docs
        agents = home / "agents"
        if agents.is_dir():
            for f in sorted(agents.glob("*.yaml")) + sorted(agents.glob("*.yml")):
                if f.is_symlink():
                    continue
                docs.append(Document(
                    id=f"doc-{idx}", path=str(f.relative_to(home)).replace("\\", "/"),
                    scope=Scope.user, kind=Kind.profile,
                    content=f.read_text("utf-8", "replace"), source_adapter=self.name))
                idx += 1
        state.documents = docs
        state.skills = load_skills(home, "skills", self.name)
        # workflows with schedule triggers -> jobs; others -> config entries
        state.jobs, state.config = _load_workflows(home / "workflows")
        return state

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        gaps = write_common_import(
            state, home,
            persona_rel="personas/imported/persona.md",
            memory_rel_fn=lambda d: d.path,
            dry_run=dry_run)
        if not dry_run:
            import json
            # non-persona profile docs land where they came from (agents/, personas/)
            # jobs -> workflows/schedule-*.yaml (buzz-workflow shape)
            wf = home / "workflows"
            wf.mkdir(parents=True, exist_ok=True)
            for i, j in enumerate(state.jobs):
                body = (
                    f"trigger: schedule\nschedule: {json.dumps(j.model_dump().get('schedule', j.model_dump()))}\n"
                    "action: notify\nnote: migrated by aim from "
                    + json.dumps(j.model_dump().get('name', 'job ' + str(i))) + "\n")
                from aim.adapters.common import write_nofollow
                write_nofollow(wf / f"imported-schedule-{i}.yaml", body, mode=0o600)
            u = home / "unsupported"
            u.mkdir(parents=True, exist_ok=True)
            from aim.adapters.common import write_nofollow as _wn
            _wn(u / "jobs.json", json.dumps([j.model_dump() for j in state.jobs], indent=2), mode=0o600)
        gaps.append(GapItem(
            item="buzz-identity", policy="warn",
            detail="Nostr keypair (BUZZ_PRIVATE_KEY) is the agent's identity; vault-only, "
                   "unrecoverable. Without a vault, import creates persona/skills but you must "
                   "run `buzz-admin generate-key` + `add-member` to register a new identity."))
        return gaps


def _load_workflows(wf: Path):
    import json
    import yaml
    from aim.canonical.models import Job
    jobs: list[Job] = []
    cfg: list[ConfigEntry] = []
    if not wf.is_dir():
        return jobs, cfg
    for f in sorted(wf.glob("*.yaml")) + sorted(wf.glob("*.yml")):
        try:
            data = _safe_yaml_load(f.read_text("utf-8")) or {}
        except Exception:
            continue
        trig = str(data.get("trigger", "")).lower()
        name = re.sub(r"\.ya?ml$", "", f.name)
        if "schedule" in trig or data.get("schedule"):
            jobs.append(Job(name=name, schedule=str(data.get("schedule", trig)),
                            command=str(data.get("action", "")), enabled=True))
        else:
            cfg.append(ConfigEntry(key=f"workflows.{name}", value=data))
    return jobs, cfg

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
