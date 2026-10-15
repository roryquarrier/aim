"""AIM bundle: zip package with preserved Unix mode bits + manifest hashes (SPEC §4.1)."""
from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .canonical.models import AgentState, Manifest

BUNDLE_SUFFIX = ".aim"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_member(name: str) -> bool:
    """Reject zip-slip, absolute paths, and Windows-reserved device names."""
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts:
        return False
    reserved = {"con", "prn", "aux", "nul", "com1", "lpt1"}
    return not any(part.split(".")[0].lower() in reserved for part in p.parts)


class BundleWriter:
    def __init__(self, path: Path):
        self.path = Path(path).with_suffix(BUNDLE_SUFFIX)
        self._files: dict[str, bytes] = {}
        self._modes: dict[str, int] = {}

    def add_bytes(self, relpath: str, data: bytes, mode: int = 0o644) -> None:
        self._files[relpath] = data
        self._modes[relpath] = mode

    def add_text(self, relpath: str, text: str, mode: int = 0o644) -> None:
        self.add_bytes(relpath, text.encode("utf-8"), mode)

    def write(self, state: AgentState, adapter_meta: dict) -> Path:
        manifest = Manifest(
            exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source_harness=state.source_harness,
            source_os=state.source_os,
            adapter=adapter_meta,
        )
        self._files.setdefault("state.json", state.model_dump_json(indent=2).encode())  # redacted copy (if added by caller) wins
        for relpath, data in sorted(self._files.items()):
            if relpath != "manifest.json":
                manifest.hashes[relpath] = _sha256(data)
        manifest_data = json.dumps(json.loads(manifest.model_dump_json()), indent=2).encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as zf:
            for relpath, data in sorted(self._files.items()):
                zi = zipfile.ZipInfo(relpath, date_time=(1980, 1, 1, 0, 0, 0))
                # Unix mode bits via external_attr (top 16 bits) — preserves +x.
                zi.external_attr = (stat.S_IFREG | self._modes.get(relpath, 0o644)) << 16
                zf.writestr(zi, data)
            mzi = zipfile.ZipInfo("manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
            mzi.external_attr = (stat.S_IFREG | 0o644) << 16
            zf.writestr(mzi, manifest_data)
        return self.path


class BundleReader:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._zf = zipfile.ZipFile(self.path)

    def manifest(self) -> Manifest:
        return Manifest.model_validate_json(self.read("manifest.json"))

    def read(self, relpath: str) -> bytes:
        return self._zf.read(relpath)

    def mode(self, relpath: str) -> int:
        zi = self._zf.getinfo(relpath)
        return (zi.external_attr >> 16) & 0o777

    def verify_hashes(self) -> list[str]:
        """Return list of failures; empty = intact (SPEC §4 rule 3)."""
        m = self.manifest()
        failures = []
        for relpath in self._zf.namelist():
            if relpath == "manifest.json":
                continue
            expect = m.hashes.get(relpath)
            got = _sha256(self.read(relpath))
            if expect is None:
                failures.append(f"{relpath}: not in manifest")
            elif expect != got:
                failures.append(f"{relpath}: hash mismatch (expected {expect[:12]}…, got {got[:12]}…)")
        for relpath in m.hashes:
            if relpath not in self._zf.namelist():
                failures.append(f"{relpath}: listed in manifest but missing from bundle")
        return failures

    def state(self, text_override: str | None = None) -> AgentState:
        if text_override is not None:
            return AgentState.model_validate_json(text_override)
        self.read("state.json")  # ensure present
        return AgentState.model_validate_json(self.read("state.json"))

    def extract(self, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        for name in self._zf.namelist():
            if not _safe_member(name):
                raise ValueError(f"unsafe bundle member: {name}")
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.read(name))
            target.chmod(self.mode(name) or 0o644)

    def close(self):
        self._zf.close()
