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
    home.parent.mkdir(parents=True, exist_ok=True)
    (home.parent / ".claude.json").write_text(json.dumps({"mcpServers": {"ctx": {"command": "npx", "args": ["-y", "ctx"], "env": {}}}}))
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
        assert (target.parent / ".claude.json").exists()

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


class TestSecretsVault:
    def test_age_roundtrip(self):
        from aim.secrets import encrypt, decrypt
        for data in (b"hi", b"", b"x" * 65536, b"x" * 65537, bytes(range(256)) * 300):
            assert decrypt(encrypt(data, "pw"), "pw") == data
        with pytest.raises(ValueError):
            decrypt(encrypt(b"x", "p"), "wrong")

    def test_export_with_secrets_e2e(self, tmp_path, monkeypatch):
        """Secret in memory -> redacted state + encrypted vault -> import restores it."""
        from aim.adapters.hermes.adapter import HermesAdapter
        from click.testing import CliRunner
        from aim import cli

        home = make_hermes_home(tmp_path)
        (home / "memories" / "MEMORY.md").write_text(
            "NOTE token: 123456789:AAFfKxhV0lz6mR8jPw3nQ4eS5tUvWxYz2Ab in use")
        pkg = tmp_path / "s.aim"
        runner = CliRunner()
        r = runner.invoke(cli.main, [
            "export", "--harness", "hermes", "--home", str(home),
            "-o", str(pkg), "--with-secrets", "--passphrase", "pw9",
        ])
        assert r.exit_code == 0, r.output
        assert "secrets vault:" in r.output

        import zipfile
        with zipfile.ZipFile(pkg) as z:
            names = z.namelist()
            state_txt = z.read("state.json")
        assert "secrets/secrets.age" in names
        assert b"AAFfKxhV" not in state_txt  # plaintext secret never in state
        assert b"${secret:" in state_txt

        # import with passphrase restores the secret
        target = tmp_path / "oc"
        target.mkdir()
        r2 = runner.invoke(cli.main, [
            "import", str(pkg), "--harness", "openclaw", "--home", str(target),
            "--force", "--passphrase", "pw9",
        ])
        assert r2.exit_code == 0, r2.output
        assert "secrets restored:" in r2.output
        restored = (target / "workspace" / "memory" / "MEMORY.md").read_text()
        assert "AAFfKxhV0lz6mR8jPw3nQ4eS5tUvWxYz2Ab" in restored


    def test_pem_roundtrip(self, tmp_path):
        """Regression: PEM private keys must restore with REAL newlines (no double-escape)."""
        from click.testing import CliRunner
        from aim import cli

        home = make_hermes_home(tmp_path)
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAtest\n-----END RSA PRIVATE KEY-----\n"
        (home / "memories" / "MEMORY.md").write_text(f"backup key:\n{pem}\nend")
        pkg = tmp_path / "pem.aim"
        r = CliRunner().invoke(cli.main, [
            "export", "--harness", "hermes", "--home", str(home),
            "-o", str(pkg), "--with-secrets", "--passphrase", "pw",
        ])
        assert r.exit_code == 0, r.output
        tgt = tmp_path / "oc2"
        tgt.mkdir()
        r2 = CliRunner().invoke(cli.main, [
            "import", str(pkg), "--harness", "openclaw", "--home", str(tgt),
            "--force", "--passphrase", "pw",
        ])
        assert r2.exit_code == 0, r2.output
        restored = (tgt / "workspace" / "memory" / "MEMORY.md").read_text()
        assert "-----BEGIN RSA PRIVATE KEY-----" in restored
        assert "\nMIIEowIBAAKCAQEAtest\n" in restored  # real newlines, not \\n
        assert restored == f"backup key:\n{pem}\nend"

    def test_prose_passwords_not_flagged(self):
        """Regression: 'password regularly. classified' prose must NOT trip the gate."""
        from aim.redact import scan_bytes
        _, r = scan_bytes(b"The password is regularly. classified as secret.")
        assert r.count == 0
        clean2, r2 = scan_bytes(b'"password": "s3cr3t!x"')
        assert r2.count >= 1
        assert b'"password"' in clean2  # key name preserved, JSON intact


    def test_malicious_bundle_paths_rejected(self, tmp_path):
        """Regression: crafted bundle paths must not escape the target home."""
        import pytest as _pytest
        from aim.adapters.common import _safe_relpath
        home = tmp_path / "h"
        home.mkdir()
        for bad in ("/etc/passwd", "../../escape", "C:\\Windows\\evil", "~/.ssh/authorized_keys", "a/../../b"):
            with _pytest.raises(ValueError):
                _safe_relpath(home, bad, "test")
        # good path still passes
        _safe_relpath(home, "memories/x.md", "test")

    def test_malicious_skill_name_rejected(self, tmp_path):
        from aim.canonical.models import AgentState, Skill, Document, Kind
        from aim.adapters.common import write_common_import
        state = AgentState(source_harness="hermes", source_os="linux", documents=[], skills=[
            Skill(name="../evil", skill_md="x"),
        ])
        import pytest as _pytest
        with _pytest.raises(ValueError):
            write_common_import(state, tmp_path / "t", "SOUL.md", lambda d: d.path, dry_run=False)


def make_codex_home(root: Path) -> Path:
    home = root / ".codex"
    (home / "skills" / "deploy").mkdir(parents=True)
    (home / "AGENTS.md").write_text("# Codex persona\nShip carefully.")
    (home / "config.toml").write_text('model = "gpt-6"\nsandbox_mode = "workspace-write"\n\n[features]\nskills = true\n')
    (home / "skills" / "deploy" / "SKILL.md").write_text("# deploy\nUse blue-green deploys")
    return home


def make_opencode_home(root: Path) -> Path:
    home = root / ".config" / "opencode"
    (home / "skills" / "review").mkdir(parents=True)
    (home / "agents").mkdir(parents=True)
    (home / "command").mkdir(parents=True)
    (home / "AGENTS.md").write_text("# OpenCode persona\nConcise answers.")
    (home / "opencode.json").write_text('{"theme": "dark", "model": "anthropic/opus"}')
    (home / "skills" / "review" / "SKILL.md").write_text("# review\nCheck tests first")
    (home / "agents" / "reviewer.md").write_text("# reviewer\nStrict reviewer agent")
    (home / "command" / "ship.md").write_text("/ship — release checklist")
    return home


@pytest.fixture
def codex_home(tmp_path):
    return make_codex_home(tmp_path)


@pytest.fixture
def opencode_home(tmp_path):
    return make_opencode_home(tmp_path)


class TestNewAdapters:
    def test_codex_export(self, codex_home):
        from aim.adapters.codex.adapter import CodexAdapter
        state = CodexAdapter().export(codex_home)
        assert any(d.kind == "persona" and "Ship carefully" in d.content for d in state.documents)
        assert [s.name for s in state.skills] == ["deploy"]
        keys = {c.key: c.value for c in state.config}
        assert keys.get("model") == "gpt-6"
        assert keys.get("features.skills") is True

    def test_hermes_to_codex_and_opencode(self, tmp_path):
        from click.testing import CliRunner
        from aim import cli
        home = make_hermes_home(tmp_path)
        pkg = tmp_path / "mig.aim"
        r = CliRunner().invoke(cli.main, ["export", "--harness", "hermes", "--home", str(home), "-o", str(pkg)])
        assert r.exit_code == 0, r.output
        for tgt_name, harness in (("cxhome", "codex"), ("ochome", "opencode")):
            tgt = tmp_path / tgt_name / "h"  # adapter home inside a sandbox dir
            r2 = CliRunner().invoke(cli.main, [
                "import", str(pkg), "--harness", harness, "--home", str(tgt), "--force"])
            assert r2.exit_code == 0, (harness, r2.output)
        # codex: persona + skills + .agents standard copy
        cx = tmp_path / "cxhome"
        assert (cx / "h" / "AGENTS.md").is_file()
        assert (cx / "h" / "skills" / "trading" / "SKILL.md").is_file() or any(
            (cx / "h" / "skills").glob("*/SKILL.md"))
        assert (cx / ".agents" / "skills").is_dir()  # standard dir too
        # opencode: persona + skills + jobs parked
        oc = tmp_path / "ochome"
        assert (oc / "h" / "AGENTS.md").is_file()
        assert (oc / "h" / "unsupported" / "jobs.json").is_file()
        assert any((oc / "h" / "skills").glob("*/SKILL.md"))

    def test_codex_to_hermes(self, tmp_path):
        from click.testing import CliRunner
        from aim import cli
        cx = make_codex_home(tmp_path)
        pkg = tmp_path / "c2h.aim"
        r = CliRunner().invoke(cli.main, ["export", "--harness", "codex", "--home", str(cx), "-o", str(pkg)])
        assert r.exit_code == 0, r.output
        tgt = tmp_path / "hermes-in"
        r2 = CliRunner().invoke(cli.main, [
            "import", str(pkg), "--harness", "hermes", "--home", str(tgt), "--force"])
        assert r2.exit_code == 0, r2.output
        assert (tgt / "SOUL.md").is_file()
        assert (tgt / "skills" / "deploy" / "SKILL.md").is_file()


class TestAdjust:
    def test_path_remap(self):
        from aim.osadjust.adjust import remap_text
        out, n = remap_text("logs at /home/hal/x and /home/hal/y", {"/home/hal": "/Users/hal"})
        assert out == "logs at /Users/hal/x and /Users/hal/y" and n == 2
