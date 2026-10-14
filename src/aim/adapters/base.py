"""Adapter base class + registry."""
from __future__ import annotations

from pathlib import Path

from aim.canonical.models import AgentState, Capability, GapItem


class Adapter:
    name: str = "?"
    capabilities: set[Capability] = set()
    home_env: str = ""  # env var for harness home, e.g. HERMES_HOME

    def default_home(self) -> Path:
        raise NotImplementedError

    def export(self, home: Path) -> AgentState:
        raise NotImplementedError

    def import_(self, state: AgentState, home: Path, dry_run: bool = False) -> list[GapItem]:
        raise NotImplementedError

    def detect(self, home: Path) -> bool:
        raise NotImplementedError


_REGISTRY: dict[str, type[Adapter]] = {}


def register(cls: type[Adapter]) -> type[Adapter]:
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> Adapter:
    return _REGISTRY[name]()


def all_adapters() -> list[str]:
    return sorted(_REGISTRY)


def autodetect(home: Path | None = None) -> Adapter | None:
    import os

    candidates = []
    if home:
        candidates.append(home)
    base = Path(os.path.expanduser("~"))
    for cls in _REGISTRY.values():
        h = home or os.environ.get(cls.home_env) or default_homes(cls)
        for cand in ([h] if not isinstance(h, list) else h):
            p = Path(cand) if cand else None
            if p and p != base and cls.detect(p):
                return cls()
    return None


def default_homes(cls: type[Adapter]) -> list[str]:
    return []
