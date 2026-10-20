# SPEC v1.2 — DeepSeek Harness (dsh) + Roo Code adapters

Status: proposed (researched 2026-10-16; sanity-checked by DeepSeek V4 Pro via OpenRouter — 8 findings incorporated)

## Goals
1. Two new adapters: `deepseek-harness` (dsh) and `roo` (Roo Code).
2. Live-harness spot-checks: install each target tool in a disposable container, `aim import`, launch the real binary, verify it boots with the migrated persona/skills.
3. Age-CLI byte-compatible vault (carried over from v1.1 decision).

## Adapter: deepseek-harness ($DSH_HOME, default ~/.dsh)

### Source layout (verified from dsh docs)
```
~/.dsh/
├── AGENTS.md              # fixed user-global persona/instructions
├── settings.yaml          # global settings (model routing, modality)
├── .credentials.yaml      # API keys + session signing key (0600) — secrets, vault-only
├── cordis.patch.yml       # home-level plugin patch layer
├── skills/                # one of six local skill roots (rank 400)
├── profiles/<name>/
│   ├── package.json       # plugin deps + dsh.profile bundles
│   ├── cordis.patch.yml   # profile-level patch layer
│   └── node_modules/      # SKIP (reproducible from package.json)
└── .sessions or persistenceRoot/  # JSONL session logs — export as raw docs, cap size
```

### Mapping
| Canonical | dsh |
|---|---|
| persona | `AGENTS.md` |
| memory | session logs: resolve actual `persistenceRoot` from settings; if Zstandard-compressed/opaque (default) treat as **opaque blobs** — opt-in `--with-sessions` copies them verbatim to `unsupported/sessions/`, NEVER parsed or exported as text docs |
| skills | `skills/*/SKILL.md` (+ scripts) — dsh reads the `.agents/skills` standard too; write BOTH |
| config | `settings.yaml` flattened; profiles' `cordis.patch.yml` → per-profile config namespace `profiles.<name>.*`; profiles' `package.json` exported too (skip only `node_modules/`) — needed for lossless profile rebuild |
| commands | (none native) |
| secrets | `.credentials.yaml` parsed (YAML) → vault entries keyed by credential name; never in state.json. **[DS] `cordis.patch.yml` (home + profile) may ALSO embed credentials in plugin `config:` blocks — run the redaction scan over ALL yaml/toml/json config text before state.json, route `token/apiKey/secret/key`-like values to the vault (same 3-pass scanner as every other adapter).** |
| cron | dsh-schedule plugin config in `cordis.patch.yml` → jobs (if schedule entries present) |
| MCP | plugin mounts in patch layer → mcp bindings where the plugin is an MCP server |

### Risks
- dsh is **developer preview, iterating fast** (shipped 2026-08-13): pin the adapter to the
  documented layering and re-verify each release; `detect()` keys on `$DSH_HOME/settings.yaml`
  + `cordis.patch.yml` presence.
- `node_modules` must be excluded from bundles (huge, reproducible).
- Session logs are Zstandard-compressed JSONL — treat as opaque blobs, don't parse.

## Adapter: roo (Roo Code)

### Source layout (verified from Roo-Code source + DoubleAgent path research)
```
~/.roo/                          # cross-editor global root (CLI + extension)
├── rules/                       # global rules → memory docs
├── rules-{mode}/                # mode-specific global rules
├── commands/                    # slash commands (*.md)
├── skills/                      # global skills (also reads ~/.agents/skills)
├── cli-settings.json            # provider/model/mode/permissions
└── cli-history.json             # raw prompts — SKIP by default (privacy)
<editor> globalStorage/rooveterinaryinc.roo-cline/
├── settings/mcp_settings.json   # MCP servers
├── settings/custom_modes.yaml   # global custom modes (roleDefinition = persona!)
└── tasks/                       # task history + checkpoints (shadow git) — SKIP by default
```

### Mapping
| Canonical | Roo |
|---|---|
| persona | mode named by `defaultMode` in `cli-settings.json` (fallback: first entry of `custom_modes.yaml`, fallback built-in `code` mode) — `roleDefinition` + `~/.roo/rules/` merged |
| memory | `~/.roo/rules/*.md` docs; other modes' rules → profile docs |
| skills | `~/.roo/skills/*/SKILL.md` (standard format) |
| config | `cli-settings.json` keys |
| modes | every custom mode → profile Document (slug, name, roleDefinition, groups) |
| commands | `~/.roo/commands/*.md` → command Documents (round-tripped verbatim) |
| MCP | `mcp_settings.json` mcpServers; `cli-settings.json` provider keys → **vault** (redaction scan over both roots' config files) |
| cron | none — parked to `unsupported/jobs.json` |
| tasks/history | opt-in `--with-history` only; shadow-git checkpoints always skipped |

### Risks
- Two storage roots (`~/.roo` + editor globalStorage). **Per-file key-level merge** (not blanket "~/.roo wins"): for `custom_modes.yaml` merge mode lists by slug with project > `~/.roo` (future) > globalStorage (legacy canonical for extension users); for `mcp_settings.json` union server keys, globalStorage value wins on conflict only if `~/.roo` lacks it. Log every merge decision in the plan output so nothing silently drops.
- `custom_modes.yaml` is YAML with a schema; mode → profile conversion is lossy for
  `groups` (tool permissions) — stored verbatim in the Document for lossless re-import.

## Live-harness spot-check protocol (both + existing 5)
Per harness, in `--network none` container with wheelhouse:
1. install real binary (pre-baked into image — network at build time only)
2. `aim import` a fixture bundle into its home
3. launch binary with a REAL no-op task (never just `--help`): dsh `--dump-config` and
   assert the persona plugin's resolved text contains our migrated persona; roo
   non-interactive print-mode task asserting the resolved `roleDefinition`/rules/skills
   are read from disk; claude/codex/opencode `--print`-style smoke + assert migrated
   files still byte-identical after run
4. snapshot home diff before/after launch — tool must not rewrite our files destructively
5. pass each tool's offline/telemetry-disable env or flags (update checks, telemetry
   phone-home cause false failures under `--network none`)

## Deliverables
- `src/aim/adapters/{deepseek_harness,roo}/adapter.py` + registry wiring
- tests: fixture round-trips + cross-harness (hermes↔dsh, hermes↔roo) + secrets vault E2E
- container spot-check script `tests/e2e/live/<harness>.sh`
- README table rows; CI stays 3-OS
