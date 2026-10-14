"""Golden fixtures: fake harness homes (hermes, openclaw, claude-code) + round-trip tests."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


def make_hermes_home(root: Path) -> Path:
    home = root / ".hermes"
    (home / "memories").mkdir(parents=True)
    (home / "skills" / "stitch-frontend").mkdir(parents=True)
    (home / "cron").mkdir(parents=True)
    (home / "SOUL.md").write_text("# Persona\nYou are Jarvis, concise technical expert.")
    (home / "memories" / "MEMORY.md").write_text("VAULT=halHermes;index.md 1st\nUSER: ESL teacher ages 5-12")
    (home / "memories" / "USER.md").write_text("USER: Rory, HK children market, sans-only design")
    (home / "config.yaml").write_text("agent:\n  name: jarvis\nauto_source_bashrc: true\n")
    (home / "skills" / "stitch-frontend" / "SKILL.md").write_text("# stitch-frontend\nUse Stitch CLI for designs.")
    (home / "skills" / "stitch-frontend" / "run.sh").write_bytes(b"#!/bin/bash\necho stitch\n")
    (home / "cron" / "jobs.json").write_text(json.dumps({
        "jobs": [{"name": "Weekly memory prune", "schedule": "0 4 * * 0", "prompt": "prune memories", "enabled": True}]
    }))
    return home


def make_openclaw_home(root: Path) -> Path:
    home = root / ".openclaw"
    ws = home / "workspace"
    (ws / "memory").mkdir(parents=True)
    (ws / "skills" / "spirit").mkdir(parents=True)
    (ws / "SOUL.md").write_text("# OpenClaw persona\nLobster mode.")
    (ws / "MEMORY.md").write_text("FACT: user likes backups")
    (ws / "memory" / "2026-10-14.md").write_text("daily note")
    (ws / "skills" / "spirit" / "SKILL.md").write_text("# spirit\ngit-based state preservation")
    (home / "openclaw.json").write_text(json.dumps({"models": {"default": "x"}}))
    return home


def make_claude_home(root: Path) -> Path:
    home = root / ".claude"
    proj = home / "projects" / "-home-user-repo" / "memory"
    proj.mkdir(parents=True)
    (home / "skills" / "review").mkdir(parents=True)
    (home / "CLAUDE.md").write_text("# Claude persona\nCareful reviewer.")
    proj.joinpath("note.md").write_text("project fact: build passes on py3.10")
    (home / "skills" / "review" / "SKILL.md").write_text("# review\nAlways run tests")
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"ctx": {"command": "npx", "args": ["-y", "ctx"], "env": {}}}}))
    return home


@pytest.fixture
def hermes_home(tmp_path):
    return make_hermes_home(tmp_path)


@pytest.fixture
def openclaw_home(tmp_path):
    return make_openclaw_home(tmp_path)


@pytest.fixture
def claude_home(tmp_path):
    return make_claude_home(tmp_path)


def _export(home: Path, harness: str, out: Path):
    from aim.adapters.hermes import adapter as _h  # noqa
    from aim.adapters.openclaw import adapter as _o  # noqa
    from aim.adapters.claude_code import adapter as _c  # noqa
    from aim.adapters.base import get
    from aim.bundle import BundleWriter
    adapter = get(harness)
    state = adapter.export(home)
    w = BundleWriter(out)
    w.add_text("state.json", state.model_dump_json())
    return w.write(state, {"name": harness, "version": "0.1.0"}), state


class TestBundle:
    def test_roundtrip_with_modes(self, tmp_path):
        from aim.bundle import BundleWriter, BundleReader
        from aim.canonical.models import AgentState
        state = AgentState(source_harness="hermes", source_os="linux")
        w = BundleWriter(tmp_path / "t")
        w.add_text("skills/x/run.sh", "#!/bin/bash\n", mode=0o755)
        p = w.write(state, {})
        r = BundleReader(p)
        assert r.verify_hashes() == []
        assert r.mode("skills/x/run.sh") == 0o755
        r.extract(tmp_path / "out")
        assert (tmp_path / "out" / "skills" / "x" / "run.sh").read_text() == "#!/bin/bash\n"

    def test_zip_slip_rejected(self, tmp_path):
        from aim.bundle import BundleReader
        p = tmp_path / "evil.aim"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("../evil.txt", "x")
        r = BundleReader(p)
        with pytest.raises(ValueError):
            r.extract(tmp_path / "out")

    def test_hash_failure_detected(self, tmp_path):
        from aim.bundle import BundleWriter, BundleReader
        from aim.canonical.models import AgentState
        import io
        w = BundleWriter(tmp_path / "t")
        w.add_text("a.txt", "original")
        p = w.write(AgentState(source_harness="hermes", source_os="linux"), {})
        # tamper: rebuild zip with modified a.txt (valid zip, wrong content)
        tampered = tmp_path / "tampered.aim"
        with zipfile.ZipFile(p) as zin, zipfile.ZipFile(tampered, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "a.txt":
                    data = b"tampered!"
                zout.writestr(item, data)
        r = BundleReader(tampered)
        assert r.verify_hashes() != []


class TestRedact:
    def test_telegram_token_redacted(self):
        from aim.redact import scan_bytes
        dirty = b'{"token": "123456789:AAFfKxhV0lz6mR8jPw3nQ4eS5tUvWxYz2Ab"}'
        clean, res = scan_bytes(dirty)
        assert b"123456789:" not in clean
        assert b"${secret:" in clean
        assert res.count >= 1

    def test_openai_key_redacted(self):
        from aim.redact import scan_bytes
        clean, res = scan_bytes(b"api_key=sk-abcdefghij1234567890abcdefghij")
        assert b"sk-abc" not in clean
        assert res.count >= 1

    def test_clean_text_untouched(self):
        from aim.redact import scan_bytes
        clean, res = scan_bytes(b"# Persona\nYou are helpful. Vault=halHermes; paths in /home/x")
        assert clean == b"# Persona\nYou are helpful. Vault=halHermes; paths in /home/x"
        assert res.count == 0


class TestHermesAdapter:
    def test_export(self, hermes_home):
        from aim.adapters.hermes.adapter import HermesAdapter
        state = HermesAdapter().export(hermes_home)
        kinds = [d.kind.value for d in state.documents]
        assert "persona" in kinds and "profile" in kinds and "memory" in kinds
        assert any(s.name == "stitch-frontend" for s in state.skills)
        assert len(state.jobs) == 1 and state.jobs[0].name == "Weekly memory prune"

    def test_import_creates_home(self, hermes_home, tmp_path):
        from aim.adapters.hermes.adapter import HermesAdapter
        state = HermesAdapter().export(hermes_home)
        target = tmp_path / "newhome"
        gaps = HermesAdapter().import_(state, target)
        assert (target / "SOUL.md").read_text().startswith("# Persona")
        assert (target / "skills" / "stitch-frontend" / "run.sh").exists()
        assert any(g.item.startswith("job:") for g in gaps)


class TestOpenClawAdapter:
    def test_export(self, openclaw_home):
        from aim.adapters.openclaw.adapter import OpenClawAdapter
        state = OpenClawAdapter().export(openclaw_home)
        assert any(d.path == "memory/2026-10-14.md" for d in state.documents)
        assert state.skills[0].name == "spirit"


class TestClaudeAdapter:
    def test_export_scopes_and_mcp(self, claude_home):
        from aim.adapters.claude_code.adapter import ClaudeCodeAdapter
        state = ClaudeCodeAdapter().export(claude_home)
        ws = [d for d in state.documents if d.scope.value == "workspace"]
        assert ws and ws[0].workspace_id == "-home-user-repo"
        assert state.mcp and state.mcp[0].command == "npx"


class TestCrossHarness:
    def test_hermes_to_openclaw(self, hermes_home, tmp_path):
        from aim.adapters.hermes.adapter import HermesAdapter
        from aim.adapters.openclaw.adapter import OpenClawAdapter
        state = HermesAdapter().export(hermes_home)
        target = tmp_path / ".openclaw"
        OpenClawAdapter().import_(state, target)
        ws = target / "workspace"
        assert (ws / "SOUL.md").read_text().startswith("# Persona")
        assert (ws / "skills" / "stitch-frontend" / "SKILL.md").exists()
        # jobs parked
        assert (ws / "unsupported" / "jobs.json").exists()

    def test_hermes_to_claude_code(self, hermes_home, tmp_path):
        from aim.adapters.hermes.adapter import HermesAdapter
        from aim.adapters.claude_code.adapter import ClaudeCodeAdapter
        state = HermesAdapter().export(hermes_home)
        target = tmp_path / ".claude"
        ClaudeCodeAdapter().import_(state, target)
        assert (target / "CLAUDE.md").read_text().startswith("# Persona")
        assert (target / ".claude.json").exists()

    def test_bundle_idempotent_export(self, hermes_home, tmp_path):
        """export(bundle(extract(export))) == export at CIF level (SPEC §2.2)."""
        from aim.adapters.hermes.adapter import HermesAdapter
        a1 = HermesAdapter().export(hermes_home)
        tmp = tmp_path / "h2"
        tmp.mkdir()
        from aim.adapters.base import get
        get("hermes").import_(a1, tmp)
        a2 = HermesAdapter().export(tmp)
        assert sorted(d.content for d in a1.documents) == sorted(d.content for d in a2.documents)
        assert sorted(s.name for s in a1.skills) == sorted(s.name for s in a2.skills)


class TestCLI:
    def test_import_with_map_regression(self, hermes_home, tmp_path):
        """Regression: `def list()` used to shadow builtin list, so list(maps) ran
        the `aim list` click command with the map value as BUNDLE_PATH (Opus, 2026-10-14)."""
        from click.testing import CliRunner
        from aim import cli
        from aim.bundle import BundleWriter
        from aim.adapters.hermes.adapter import HermesAdapter

        state = HermesAdapter().export(hermes_home)
        w = BundleWriter(tmp_path / "b")
        w.add_text("state.json", state.model_dump_json())
        pkg = w.write(state, {})

        target = tmp_path / "oc-home"
        target.mkdir()
        res = CliRunner().invoke(cli.main, [
            "import", str(pkg), "--harness", "openclaw",
            "--home", str(target), "--force", "--map", "/home/hal=/Users/rory",
        ])
        assert res.exit_code == 0, res.output
        assert (target / "workspace" / "SOUL.md").exists()


class TestAdjust:
    def test_path_remap(self):
        from aim.osadjust.adjust import remap_text
        out, n = remap_text("logs at /home/hal/x and /home/hal/y", {"/home/hal": "/Users/hal"})
        assert out == "logs at /Users/hal/x and /Users/hal/y" and n == 2
