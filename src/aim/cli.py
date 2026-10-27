"""AIM CLI (SPEC §3)."""
from __future__ import annotations

import os
import sys

import click

from aim import bundle as bundle_mod
from aim.adapters.claude_code import adapter as _c  # noqa: F401
from aim.adapters.codex import adapter as _cx  # noqa: F401
from aim.adapters.hermes import adapter as _h  # noqa: F401 register
from aim.adapters.openclaw import adapter as _o  # noqa: F401
from aim.adapters.opencode import adapter as _oc  # noqa: F401
from aim.adapters.buzz import adapter as _bz  # noqa: F401
from aim.adapters.goose import adapter as _gs  # noqa: F401
from aim.adapters.grok import adapter as _gk  # noqa: F401
from aim.adapters.deepseek_harness import adapter as _dsh  # noqa: F401
from aim.adapters.roo import adapter as _roo  # noqa: F401
from aim.adapters.base import all_adapters, autodetect, get as get_adapter
from aim.osadjust.adjust import (
    harness_running,
    path_map,
    remap_text,
    transactional_import,
)
from aim.redact import scan_bytes


@click.group()
def main():
    """AIM — Agent Identity Migration. Move a stateful AI agent between harnesses and OSes."""


@main.command("export")
@click.option("--harness", "harness_name", default="auto", help="Source harness")
@click.option("--home", "home_dir", default=None, type=click.Path(), help="Harness home dir")
@click.option("-o", "--output", default="agent.aim", type=click.Path(), help="Bundle path")
@click.option("--with-secrets", is_flag=True, help="Include age-encrypted secrets vault")
@click.option("--passphrase", default=None, help="Vault passphrase (else $AIM_PASSPHRASE, else prompt)")
@click.option("--allow-unredacted", is_flag=True, help="Proceed despite unclassifiable secret-like spans")
def export(harness_name, home_dir, output, with_secrets, passphrase, allow_unredacted):
    """Export a harness home into a portable .aim bundle."""
    from pathlib import Path

    if harness_name == "auto":
        adapter = autodetect(Path(home_dir) if home_dir else None)
        if adapter is None:
            click.echo("error: could not autodetect harness; pass --harness {hermes|openclaw|claude-code}", err=True)
            sys.exit(2)
    else:
        adapter = get_adapter(harness_name)
    home = Path(home_dir) if home_dir else adapter.default_home()
    if not home.exists():
        click.echo(f"error: harness home not found: {home}", err=True)
        sys.exit(2)
    state = adapter.export(home)
    writer = bundle_mod.BundleWriter(output)
    # scan skill script bytes FIRST (they serialize as base64 inside state.json,
    # which the JSON scan cannot see) — shared namespace avoids placeholder collisions
    from aim.redact import RedactionResult
    redaction = RedactionResult()
    for s in state.skills:
        for rel in list(s.scripts):
            sc, _ = scan_bytes(s.scripts[rel], result=redaction)
            s.scripts[rel] = sc
    raw = state.model_dump_json(indent=2).encode()
    clean, redaction = scan_bytes(raw, result=redaction)
    if redaction.count and not allow_unredacted and not with_secrets:
        click.echo(f"error: {redaction.count} secret-like span(s) found in exported state; "
                   f"re-run with --allow-unredacted or --with-secrets", err=True)
        sys.exit(3)
    writer.add_bytes("state.json", clean)
    if with_secrets and redaction.redacted:
        from aim import secrets as secrets_mod
        import json as _json
        passphrase = passphrase or os.environ.get("AIM_PASSPHRASE")
        if not passphrase:
            passphrase = click.prompt("Vault passphrase", hide_input=True, confirmation_prompt=True)
        import hashlib as _hl
        def _unescape(s: str) -> str:
            try:
                u = _json.loads(f'"{s}"')
                return u if isinstance(u, str) else s
            except Exception:
                return s
        _v = {ph: _unescape(v) for ph, v in redaction.redacted.items()}
        _v["_aim_state_sha256"] = _hl.sha256(clean).hexdigest()
        vault = _json.dumps(_v, indent=1).encode()
        writer.add_bytes("secrets/secrets.age", secrets_mod.encrypt(vault, passphrase), mode=0o600)
        click.echo(f"secrets vault: {len(redaction.redacted)} value(s) encrypted into secrets/secrets.age")
    out = writer.write(state, adapter_meta={"name": adapter.name, "version": "0.1.0"})
    click.echo(f"exported {home} -> {out} (harness={state.source_harness}, docs={len(state.documents)}, "
               f"skills={len(state.skills)}, jobs={len(state.jobs)}, secrets_redacted={redaction.count})")


@main.command("import")
@click.argument("bundle_path", type=click.Path(exists=True))
@click.option("--harness", "harness_name", required=True)
@click.option("--home", "home_dir", default=None, type=click.Path())
@click.option("--map", "maps", multiple=True, help="path mapping src=dst (repeatable)")
@click.option("--passphrase", default=None, help="Secrets vault passphrase (else $AIM_PASSPHRASE, else prompt)")
@click.option("--dry-run", is_flag=True)
@click.option("--force", is_flag=True, help="Proceed even if a harness process appears to be running")
def import_(bundle_path, harness_name, home_dir, maps, passphrase, dry_run, force):
    """Import an .aim bundle into a target harness home."""
    import json as _json
    from pathlib import Path

    reader = bundle_mod.BundleReader(bundle_path)
    failures = reader.verify_hashes()
    if failures:
        click.echo("error: bundle integrity check FAILED:")
        for f in failures:
            click.echo(f"  {f}", err=True)
        sys.exit(4)
    if harness_running(harness_name) and not force:
        click.echo(f"error: a {harness_name} process appears to be running; stop it or use --force", err=True)
        sys.exit(5)
    # restore secrets: decrypt vault, substitute ${secret:NAME} placeholders on the
    # RAW state.json text BEFORE parsing — values keep their JSON-escaped form,
    # so PEM keys / newlines restore exactly and binary scripts stay untouched.
    raw_state: str | None = None
    if "secrets/secrets.age" in reader.manifest().hashes:
        from aim import secrets as secrets_mod
        passphrase = passphrase or os.environ.get("AIM_PASSPHRASE")
        if not passphrase:
            passphrase = click.prompt("Vault passphrase", hide_input=True)
        vault = _json.loads(secrets_mod.decrypt(reader.read("secrets/secrets.age"), passphrase))

        # match placeholder whether it appears raw or JSON-escaped in the state text
        def json_escape(s: str) -> str:
            return _json.dumps(s)[1:-1]

        raw = reader.read("state.json").decode("utf-8", "replace")
        import hashlib as _hl
        state_sha = vault.pop("_aim_state_sha256", None)
        if state_sha is None or _hl.sha256(raw.encode("utf-8", "replace")).hexdigest() != state_sha:
            click.echo("error: vault does not match this bundle's state.json "
                       "(tampered or mismatched bundle?) — refusing to fill secrets", err=True)
            sys.exit(6)
        # fill placeholders by walking the parsed object — raw values, no text splicing
        _obj = _json.loads(raw)
        def _fill(o):
            if isinstance(o, str):
                for _ph, _val in vault.items():
                    o = o.replace(_ph, _val)
                return o
            if isinstance(o, list):
                return [_fill(x) for x in o]
            if isinstance(o, dict):
                return {k: _fill(v) for k, v in o.items()}
            return o
        raw_state = _json.dumps(_fill(_obj))
        click.echo("secrets restored: placeholders filled from vault")
    state = reader.state(text_override=raw_state)
    # scripts are raw bytes (pydantic-decoded), so fill script placeholders directly
    if raw_state is not None and "secrets/secrets.age" in reader.manifest().hashes:
        for _s in state.skills:
            for _rel in list(_s.scripts):
                _b = _s.scripts[_rel]
                for _ph, _val in vault.items():
                    _b = _b.replace(_ph.encode(), _val.encode())
                _s.scripts[_rel] = _b
    mapping = path_map(list(maps))
    if mapping:
        n = 0
        for d in state.documents:
            d.content, k = remap_text(d.content, mapping)
            n += k
        click.echo(f"path remap: {n} rewrites")
    adapter = get_adapter(harness_name)
    home = Path(home_dir) if home_dir else adapter.default_home()

    def stage(target: Path):
        adapter.import_(state, target, dry_run=dry_run)

    bak = transactional_import(home, stage, dry_run=dry_run,
                                externals=getattr(adapter, "EXTERNAL_PATHS", ()))
    reader.close()
    if dry_run:
        click.echo("dry-run ok: no files written")
    else:
        click.echo(f"imported {bundle_path} -> {home}" + (f" (backup: {bak})" if bak else ""))


@main.command("restore-backup")
@click.argument("backup_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--home", "home_dir", default=None, type=click.Path(),
              help="Target home (default: infer from backup dir name '<name>.aimbak.<ts>')")
def restore_backup(backup_dir, home_dir):
    """Restore a home from an .aimbak snapshot made before an import.

    Refuses if the target home is missing (nothing to swap) or a harness
    process appears to be running.
    """
    from pathlib import Path
    import re
    import shutil
    bdir = Path(backup_dir)
    m = re.fullmatch(r"(.+)\.aimbak\.[0-9.]+", bdir.name)
    target = Path(home_dir) if home_dir else (bdir.parent / m.group(1) if m else None)
    if target is None:
        click.echo("error: cannot infer target home from backup name; pass --home", err=True)
        sys.exit(1)
    if harness_name_of_home(target) and harness_running(harness_name_of_home(target)):
        click.echo("error: harness process appears to be running; stop it first", err=True)
        sys.exit(5)
    tmp_old = target.parent / f".{target.name}.aimold.restore.{os.getpid()}"
    tmp_new = target.parent / f".{target.name}.aimnew.restore.{os.getpid()}"
    try:
        if tmp_new.exists():
            shutil.rmtree(tmp_new)
        shutil.copytree(bdir, tmp_new, symlinks=True, ignore_dangling_symlinks=True,
                        ignore=shutil.ignore_patterns("_aim_externals"))
        if target.exists():
            target.rename(tmp_old)
        tmp_new.rename(target)
    except BaseException:
        shutil.rmtree(tmp_new, ignore_errors=True)
        if tmp_old.exists() and not target.exists():
            tmp_old.rename(target)  # original home always goes back on failure
        raise
    if tmp_old.exists():
        shutil.rmtree(tmp_old, ignore_errors=True)
    # external files (e.g. ~/.claude.json, ~/.agents) backed up beside the home
    ext = bdir / "_aim_externals"
    if ext.is_dir():
        for src in ext.iterdir():
            dst = target.parent / src.name
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True) if dst.is_dir() else dst.unlink()
            shutil.copytree(src, dst, symlinks=True) if src.is_dir() else shutil.copy2(src, dst)
    click.echo(f"restored {bdir} -> {target}")


def harness_name_of_home(home: Path):
    from aim.adapters.base import all_adapters
    for adapter in all_adapters():
        try:
            if adapter.default_home().resolve() == home.resolve():
                return adapter.name
        except Exception:
            continue
    return None


@main.command("plan")
@click.argument("bundle_path", type=click.Path(exists=True))
@click.option("--harness", "harness_name", required=True)
def plan(bundle_path, harness_name):
    """Show the capability gap report: what lands native/emulated/parked/lost. Writes nothing."""
    reader = bundle_mod.BundleReader(bundle_path)
    failures = reader.verify_hashes()
    if failures:
        click.echo("error: bundle integrity check FAILED", err=True)
        sys.exit(4)
    state = reader.state()
    adapter = get_adapter(harness_name)
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        gaps = adapter.import_(state, Path(td) / "home", dry_run=True)
    click.echo(f"plan: {bundle_path} -> {harness_name}")
    for g in gaps:
        click.echo(f"  [{g.policy:7s}] {g.item}" + (f" — {g.detail}" if g.detail else ""))
    reader.close()


@main.command("list")
@click.argument("bundle_path", type=click.Path(exists=True))
def list_(bundle_path):
    """List bundle contents."""
    reader = bundle_mod.BundleReader(bundle_path)
    m = reader.manifest()
    state = reader.state()
    click.echo(f"exported_at : {m.exported_at}")
    click.echo(f"source      : {m.source_harness} on {m.source_os}")
    click.echo(f"documents   : {len(state.documents)}")
    click.echo(f"skills      : {len(state.skills)}")
    click.echo(f"jobs        : {len(state.jobs)}")
    click.echo(f"mcp         : {len(state.mcp)}")
    click.echo(f"files       : {len(m.hashes) + 1}")
    reader.close()


@main.command("adapters")
@click.argument("action", default="list")
def adapters(action):
    """List registered adapters."""
    if action == "list":
        for name in all_adapters():
            a = get_adapter(name)
            click.echo(f"{name:12s} caps={','.join(sorted(c.value for c in a.capabilities))}")


if __name__ == "__main__":
    main()
