# SPEC v2: AIM — Agent Identity Migration (harness- & OS-agnostic)
<!-- v2 revisions after Opus 5.5 review: secret-redaction layer, scope+path
     model, document-based memory, capability negotiation, transactional
     import, zip-with-modes, v1 scope cut (Hermes↔OpenClaw + Claude Code). -->


**Goal:** A CLI tool + open package format that migrates a full stateful AI agent
(persona, memories, skills, config, cron/scheduled jobs, MCP/tool bindings,
conversation history) between *harnesses* (Hermes, OpenClaw, DeepClaw/"Deepsea
Carnage", Claude Code, Codex, Kilo…) and *operating systems* (Linux, macOS,
Windows 11 + WSL2) — the "Samsung Smart Switch for AI agents."

## 1. Core architecture: Canonical Intermediate Format (CIF)

Point-to-point harness migration is N². AIM converts everything to a **neutral
canonical package**, then to any target. (Same insight as Aplexica's ACF and
`agent-life`'s neutral format.)

```
harness A ──export──▶ ┌──────────────┐ ──import──▶ harness B
 (Linux/WSL2)         │  .aim bundle │            (macOS/Win/Linux)
                      │  CIF (JSON+  │
                      │  markdown +  │
                      │  blobs)      │
                      └──────────────┘
```

### 1.1 Package layout (`.aim` = zip/tar.zst)

```
agent.aim/
├── manifest.json        # schema_version, hashes of EVERY file, source
│                        # harness+version, source OS, export time, adapters used
├── identity/
│   ├── persona.md       # canonical: merged SOUL.md / AGENTS.md / system-prompt persona
│   ├── user_profile.md  # canonical USER.md
│   └── provenance.json  # which source file each section came from (audit trail)
├── memory/
│   ├── facts.jsonl      # canonical atomic facts (source: MEMORY.md entries, letta blocks)
│   └── raw/             # verbatim originals (MEMORY.md, USER.md, memory/*.md, SQLite dumps)
├── skills/
│   └── <skill>/SKILL.md + scripts   # skill.md is already a de-facto standard
│                                    # (Claude Code, Hermes, OpenClaw, Kilo all use it)
├── config/
│   ├── canonical.yaml   # normalized key set (model providers, TTS, platform creds refs)
│   └── native/          # per-harness originals for round-trip fidelity
├── automation/
│   └── jobs.json        # canonical cron schema: schedule, action, delivery target
├── history/             # optional (--with-sessions): sessions in canonical JSONL
├── secrets/             # OPTIONAL: secrets.age (age-encrypted) + manifest of
│                        # ${secret:NAME} references. Redaction scan is mandatory
│                        # on everything else (§4.1). NEVER plaintext.
└── VERIFY.md            # post-import checklist auto-generated for the target
```

## 1.2 Canonical schemas (v2: document-based memory, scope+path everywhere)

- **memory = documents, not atomized facts** (Opus flaw #3 — atomization is
  undefined and non-deterministic). Canonical memory item:
  `{id, path, scope: user|project|workspace, workspace_id, kind: persona|memory|profile|raw, content, source_adapter}`.
  Translation between harnesses is deterministic file placement + format
  wrapping. No LLM, no splitting heuristics in v1.
- **Scope & path model** (Opus flaw #2): every identity/memory/skill/config/MCP
  item carries `scope` + `workspace_id`. Cross-OS moves re-key path-derived
  identifiers via an explicit mapping table: `aim import --map /home/hal=/Users/hal`.
  All rewrites are recorded in VERIFY.md.
- **jobs.json**: `{name, schedule, action: {command, interpreter}, deliver_to, enabled, source_capability}` — harness-neutral; per-item import policy comes from capability negotiation (§2.1), not encoded kinds.
- **canonical.yaml**: OS/harness-independent keys only; OS-specific keys applied via per-target **adjustments overlay** at import.

## 2. Adapters & capability negotiation

### 2.1 Capability model (v2, Opus flaw #4)

Each adapter declares capabilities: `cron`, `delivery:telegram`, `mcp:stdio`,
`skills:scripts`, `persona:md`, etc. At import, AIM computes the source→target
**gap** and applies an explicit per-item policy:
`native | emulate (map to OS scheduler: cron/launchd/Task Scheduler) | park (→ unsupported/, listed in VERIFY.md) | fail`.
`aim plan agent.aim --harness X` prints the full gap report **before anything is
written** — this is the primary UX, not just `--dry-run`. Skills get a
`requires: {os, interpreters, binaries}` preflight so bash-only skills are
parked, not silently broken, on Windows.

### 2.2 Adapter plugins

Each adapter is a small Python plugin: `export(harness_home) -> CIF`,
`import_(CIF) -> harness_home`, `verify() -> report`, plus golden-fixture
contract tests asserting `export(import_(export(fixture))) == export(fixture)`.

| Adapter | persona source | memory | skills | config | automation |
|---|---|---|---|---|---|
| hermes | SOUL.md | memories/*.md, memory tool store | skills/ | config.yaml | cron/ |
| openclaw | SOUL/IDENTITY.md | MEMORY.md + memory/*.md + sqlite | SKILL.md | openclaw.json | cron-wrappers |
| claude-code | CLAUDE.md (user+project scopes) | ~/.claude/projects/<path-keyed>/memory | .claude/skills | .claude.json + .mcp.json | none |

**Layouts are unverified guesses until fixture-verified** — first build step is
writing golden fixtures from each harness's real on-disk layout (Opus flagged
several table entries as guessed). Codex/Kilo adapters: v2, after layouts are
fixture-verified.

## 3. CLI surface

```
aim plan   agent.aim --harness X          # gap report: native/emulate/park/loss per item (PRIMARY UX)
aim export  [--harness auto|hermes|…] [--with-history] [--with-secrets] [-o agent.aim]
aim import  agent.aim --harness openclaw [--mode replace|merge|side-by-side]
            [--map /home/hal=/Users/hal] [--allow-unredacted] [--force]
aim list    agent.aim
aim verify  # post-import: memories load, skills preflight, persona present,
            # cron valid, path references resolve on THIS OS
aim rollback [snapshot-id]
aim adapters list
```

- **Import is transactional** (Opus #6): stage into a temp dir next to the
  target → validate → atomic rename swap. Backup with 0600 perms (owner-only
  ACL on Windows), retention policy, `aim rollback` to undo.
- **Refuse if the target harness/gateway is running** (SQLite locks, daemon
  overwrites). Detect process, abort with instructions.
- `--mode merge` conflict policy for importing into an already-lived-in home,
  with a conflict report.
- History: **export-and-archive only** in v1 (no cross-harness session
  injection — costly, low value, mostly unsupported by targets).

## 4. Security rules (non-negotiable)

1. **Secret-redaction pass over EVERY file** (Opus flaw #1 — secrets leak via
   config/native/, memory prose, history): gitleaks-style scanner + known
   key-paths per adapter runs at export. Hits are replaced with
   `${secret:NAME}` references; values go only into `secrets.age`. Export
   FAILS on unclassifiable findings unless `--allow-unredacted`.
2. Secrets encrypted with **age** (X25519 recipient or passphrase; `pyrage`
   wheel — real dependency, not a hack). Resolved at import to 0600 files or
   OS keychain. Never plaintext anywhere in the bundle.
3. `import` refuses if the manifest hash check fails on ANY file. Hash raw
   bytes; ship `.gitattributes` `* -text` (CRLF via git transport would
   otherwise break every hash).
4. No code in the bundle (no `adapters/` dir — record
   `adapter: {name, version, git_sha}` in manifest instead; bundle-executed
   code = arbitrary code execution).
5. Adapters are pure functions; no network except explicit `verify --ping`.
6. Format versioning: CIF semver, forward-compatible unknown fields,
   `migrations/` chain in the tool. Adapters declare `supports_harness: ">=x,<y"`.

## 4.1 Package format decision

Single choice: **zip with explicit `external_attr` mode bits** (preserves +x on
skill scripts; tar.zstd needs py3.14 or a heavy dep). Extraction must handle
zip-slip, symlinks, case-insensitive collisions, Windows reserved names
(`con`, `aux`) and MAX_PATH.

## 5. Testing strategy (phase 2, per Rory: containers)

- Fixture round-trips run on plain `pytest tmp_path` (fake homes are just dirs).
- **One end-to-end smoke test per harness**: container (or GH runner) boots the
  REAL harness binary against the imported home and confirms persona/skills
  load. This is the only test that proves migration works (Opus #8).
- Matrix (right-sized, not 36 cells): source {hermes, openclaw} × target
  {hermes, openclaw, claude-code} × OS {debian, ubuntu-WSL2 (real WSL2, incl.
  /mnt/c drvfs quirks), macos-14 runner, windows-latest runner}.

## 5.1 v1 scope (cut per Opus verdict)

- Harnesses: **Hermes ↔ OpenClaw full round-trip; Claude Code as persona/
  memory/skills/MCP source+target.** Codex/Kilo in v2.
- OS: Linux, WSL2, macOS. Native Windows in v1.1 (path/script work is real).
- Dropped from v1 as over-engineering: provenance.json, `aim diff --live`,
  manifest signing, session-history translation.

## 6. Repo layout

```
aim/
├── pyproject.toml        # python ≥3.10, zero heavy deps (click, pyyaml, age hack?)
├── src/aim/
│   ├── cli.py
│   ├── bundle.py         # package create/read/verify
│   ├── canonical/        # CIF schemas (pydantic)
│   ├── adapters/{hermes,openclaw,claude_code,codex,kilo}/
│   ├── osadjust/         # per-OS config overlays
│   └── crypto.py         # age encryption wrapper
├── tests/                # unit + fixture homes
├── fixtures/             # fake harness homes per adapter
└── docs/SPEC-CIF.md      # the open format doc (publishable)
```

## 7. Non-goals (v1)

- Live/bidirectional sync between running harnesses (that's Aplexica's lane).
- Translating harness-specific plugin *code* (only configs move).
- GUI.

## 8. Known flaws in prior art we explicitly fix

- hm-portable: broken `local` usage kills restore under `set -e`; plaintext
  secrets; Hermes-only; bash-only (no native Windows); checksums only 2 files.
- SaveState: cloud-gated, not harness-config-aware.
- Letta AgentFile: Letta-centric schema, no cron/config layer.
