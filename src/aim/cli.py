"""AIM CLI (SPEC §3)."""
from __future__ import annotations

import sys

import click

from aim import bundle as bundle_mod
from aim.adapters.claude_code import adapter as _c  # noqa: F401
from aim.adapters.hermes import adapter as _h  # noqa: F401 register
from aim.adapters.openclaw import adapter as _o  # noqa: F401
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


@main.command()
@click.option("--harness", "harness_name", default="auto", help="Source harness")
@click.option("--home", "home_dir", default=None, type=click.Path(), help="Harness home dir")
@click.option("-o", "--output", default="agent.aim", type=click.Path(), help="Bundle path")
@click.option("--with-secrets", is_flag=True, help="Include age-encrypted secrets vault (v1.1)")
@click.option("--allow-unredacted", is_flag=True, help="Proceed despite unclassifiable secret-like spans")
def export(harness_name, home_dir, output, with_secrets, allow_unredacted):
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
    raw = state.model_dump_json(indent=2).encode()
    clean, redaction = scan_bytes(raw)
    if redaction.count and not allow_unredacted and not with_secrets:
        click.echo(f"error: {redaction.count} secret-like span(s) found in exported state; "
                   f"re-run with --allow-unredacted or --with-secrets (v1.1)", err=True)
        sys.exit(3)
    writer.add_bytes("state.json", clean)
    # also redact skill scripts / docs payloads already serialized in state.json — scan covers it
    out = writer.write(state, adapter_meta={"name": adapter.name, "version": "0.1.0"})
    click.echo(f"exported {home} -> {out} (harness={state.source_harness}, docs={len(state.documents)}, "
               f"skills={len(state.skills)}, jobs={len(state.jobs)}, secrets_redacted={redaction.count})")


@main.command("import")
@click.argument("bundle_path", type=click.Path(exists=True))
@click.option("--harness", "harness_name", required=True)
@click.option("--home", "home_dir", default=None, type=click.Path())
@click.option("--map", "maps", multiple=True, help="path mapping src=dst (repeatable)")
@click.option("--dry-run", is_flag=True)
@click.option("--force", is_flag=True, help="Proceed even if a harness process appears to be running")
def import_(bundle_path, harness_name, home_dir, maps, dry_run, force):
    """Import an .aim bundle into a target harness home."""
    from pathlib import Path

    reader = bundle_mod.BundleReader(bundle_path)
    failures = reader.verify_hashes()
    if failures:
        click.echo("error: bundle integrity check FAILED:", err=True)
        for f in failures:
            click.echo(f"  {f}", err=True)
        sys.exit(4)
    if harness_running(harness_name) and not force:
        click.echo(f"error: a {harness_name} process appears to be running; stop it or use --force", err=True)
        sys.exit(5)
    state = reader.state()
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

    bak = transactional_import(home, stage, dry_run=dry_run)
    reader.close()
    if dry_run:
        click.echo("dry-run ok: no files written")
    else:
        click.echo(f"imported {bundle_path} -> {home}" + (f" (backup: {bak})" if bak else ""))


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
