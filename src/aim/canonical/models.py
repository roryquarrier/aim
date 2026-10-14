"""AIM canonical intermediate format (CIF) schemas."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

CIF_SCHEMA_VERSION = 1


class Scope(str, Enum):
    user = "user"
    project = "project"
    workspace = "workspace"


class Kind(str, Enum):
    persona = "persona"
    memory = "memory"
    profile = "profile"
    raw = "raw"


class Document(BaseModel):
    """Canonical memory/identity unit — document-based (SPEC §1.2), NOT atomized facts."""

    id: str
    path: str
    scope: Scope = Scope.user
    workspace_id: Optional[str] = None
    kind: Kind = Kind.memory
    content: str
    source_adapter: str


class Skill(BaseModel):
    name: str
    skill_md: str  # verbatim SKILL.md content
    scripts: dict[str, bytes] = Field(default_factory=dict)  # relpath -> bytes
    requires: dict = Field(default_factory=dict)  # {os, interpreters, binaries}


class Job(BaseModel):
    name: str
    schedule: str  # cron expression or ISO duration
    command: str
    interpreter: str = "bash"
    deliver_to: Optional[str] = None
    enabled: bool = True
    source_capability: str = "cron"


class ConfigEntry(BaseModel):
    key: str
    value: object
    os_specific: bool = False
    source: str = "canonical"


class MCPBinding(BaseModel):
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: list[str] = Field(default_factory=list)
    env_refs: dict[str, str] = Field(default_factory=dict)  # var -> ${secret:NAME} or literal


class Capability(str, Enum):
    cron = "cron"
    delivery_telegram = "delivery:telegram"
    mcp_stdio = "mcp:stdio"
    skills_scripts = "skills:scripts"
    persona_md = "persona:md"


class AgentState(BaseModel):
    """The whole canonical agent."""

    schema_version: int = CIF_SCHEMA_VERSION
    agent_name: str = "agent"
    source_harness: str
    source_harness_version: Optional[str] = None
    source_os: str
    documents: list[Document] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    config: list[ConfigEntry] = Field(default_factory=list)
    mcp: list[MCPBinding] = Field(default_factory=list)


class GapItem(BaseModel):
    item: str
    policy: str  # native | emulate | park | fail
    detail: str = ""


class Manifest(BaseModel):
    format: str = "aim"
    format_version: int = 1
    cif_schema_version: int = CIF_SCHEMA_VERSION
    exported_at: str
    source_harness: str
    source_os: str
    adapter: dict = Field(default_factory=dict)
    hashes: dict[str, str] = Field(default_factory=dict)  # relpath -> sha256
    has_secrets: bool = False
