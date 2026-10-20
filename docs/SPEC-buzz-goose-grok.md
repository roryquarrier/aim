# SPEC v1.2b — Buzz, Goose, Grok Build adapters

Status: proposed (researched 2026-10-16 from block/buzz repo, x.ai docs, goose docs)
Parent: SPEC-dsh-roo.md (v1.2)

Note: Buzz is Block's (Jack Dorsey's) self-hosted agent workspace — relay + desktop +
agent harness; Goose is Block's open agent (now Agentic AI Foundation). Grok Build is
xAI's coding agent CLI (`grok`, install via x.ai/cli).

## Adapter: buzz (Block)

Buzz is messaging-driven: humans and agents share relay channels. An agent's identity =
persona pack + relay membership (Nostr keypair). Migration target = agent persona/behavior,
not chat history.

### Source layout (block/buzz, OSS)
```
<buzz config root>            # BUZZ_* env-driven; ACP harness spawns managed agents
├── buzz-persona packs        # agent persona packs (persona markdown per agent)
├── managed agent defs        # display-name, system-prompt, runtime, provider, model, access
├── workflows/*.yaml          # buzz-workflow YAML automation (message/reaction/schedule/webhook triggers)
└── skills (nest_skill.md)    # SKILL.md standard
Env: BUZZ_RELAY_URL, BUZZ_PRIVATE_KEY (Nostr secret — VAULT ONLY), BUZZ_AUTH_TAG
```

### Mapping
| Canonical | Buzz |
|---|---|
| persona | managed agent `system-prompt` / persona pack |
| memory | agent memory via buzz-cli (export opt-in `--with-memory`) |
| skills | SKILL.md packs (`buzz-persona`, managed-agents skills) |
| config | runtime/provider/model per managed agent |
| jobs | `buzz-workflow` YAML schedules → jobs (trigger: schedule) |
| MCP | buzz-dev-mcp binding |
| secrets | `BUZZ_PRIVATE_KEY` (Nostr nsec/hex — the agent's very identity), `BUZZ_AUTH_TAG`, relay signing key → vault. Never in state.json. |

### Risks
- OSS "use the internal build" guidance: layout may drift between OSS and Block-signed builds — pin adapter to OSS repo structure, re-verify per release.
- Nostr private key IS the agent identity: losing it = losing the agent. Import must offer generating a NEW keypair when the bundle carries no vault, and Buzz's key cannot be recovered once lost — surface this in `aim plan` output.

## Adapter: goose (Block / Agentic AI Foundation)

### Source layout
```
~/.config/goose/
├── config.yaml           # provider, model, extensions (incl. MCP servers), permissions
├── AGENTS.md             # global user instructions/persona (also .goosehints per project)
└── sessions/             # JSONL session history — opt-in export, opaque
```

### Mapping
| Canonical | Goose |
|---|---|
| persona | `AGENTS.md` |
| memory | sessions opt-in (`--with-sessions`, opaque JSONL) |
| skills | goose extensions as skills where a directory w/ manifest; else parked |
| config | `config.yaml` flattened (GOOSE_* env overlay noted) |
| MCP | `config.yaml` extensions entries (stdio servers) |
| cron | none — parked |

## Adapter: grok (Grok Build, xAI)

### Source layout
```
~/.grok/
├── GROK.md or AGENTS.md      # persona/instructions (AGENTS.md standard support)
├── settings.json / config    # model selection (grok-4.7 default), custom model defs
└── (API key via XAI_API_KEY env / auth file → vault only)
```
(Exact filenames to be pinned against the installed CLI during implementation — docs at
docs.x.ai/build show install + `-p` print mode + `grok inspect`; home layout confirmed at build time. Adapter `detect()` probes `~/.grok` + settings; spot-check uses `grok -p` offline smoke.)

### Mapping
| Canonical | Grok |
|---|---|
| persona | `GROK.md`/`AGENTS.md` |
| skills | SKILL.md standard dirs if present; else parked |
| config | settings keys |
| secrets | `XAI_API_KEY` → vault |
| cron/MCP | parked unless present in settings |

## Implementation order (v1.2 total)
1. goose (simplest, one root, AGENTS.md standard) — also closes the loop: Buzz's own
   harness runs goose via ACP, so hermes→goose covers the most common real Buzz hop
2. buzz (persona/workflow/jobs + Nostr-key vault handling)
3. grok (layout pin from installed CLI first)
4. dsh + roo (parent spec)
Each: fixture tests + cross-harness + secrets E2E + live spot-check in offline container.

## Deliverables
- `src/aim/adapters/{goose,buzz,grok}/adapter.py` + registry wiring + README rows
- `docs/SPEC-dsh-roo.md` items unchanged; this doc extends scope
