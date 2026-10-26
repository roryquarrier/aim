# AIM — launch posts (ready to paste)

## 1. Show HN
**Title:** Show HN: AIM – Move your AI coding agent between Claude Code, Codex, OpenCode and 7 more

I kept rebuilding the same agent by hand every time I switched CLIs — persona prompt, memory files, skills, API keys, all of it. So I built AIM (Agent Identity Migration): a "Smart Switch" for AI agents.

    pipx install aim-migrate
    aim export --harness claude-code -o move.aim
    aim import move.aim --harness codex

What moves: persona/system prompt, memories, skills, settings, scheduled jobs, and secrets.
Secrets go through a redaction scanner (30+ patterns) into a separate encrypted vault — and since v0.6 the vault is byte-compatible with the standard `age` CLI, so you can decrypt your own bundle with stock tooling if AIM vanished tomorrow. `age -d bundle/secrets.age`. No telemetry, no account, no network calls — it's a local CLI.

10 harnesses supported (Claude Code, Codex CLI, OpenCode, Goose, Hermes, OpenClaw, Buzz, Grok Build, DeepSeek Harness, Roo Code), any direction, Linux/macOS/Windows incl. WSL2. 34 tests, 3-OS CI, and live spot-checks where the four highest-adoption CLIs were actually booted in offline containers with migrated state.

MIT, zero cost: https://github.com/roryquarrier/aim

Happy to answer anything about the format (open `.aim` bundle spec) or the redaction design.

## 2. r/LocalLLaMA
**Title:** I open-sourced AIM: migrate your agent's persona/memory/skills/secrets between 10 harnesses (Claude Code, Codex, OpenCode, Goose…) — local CLI, age-encrypted vault

Body: same as Show HN but add: "Works fine with local-model harnesses too — the bundle format is model-agnostic; you're moving state, not weights."

## 3. r/ClaudeAI + r/ChatGPTCoding
**Title:** Moving from Claude Code to Codex (or back)? AIM moves your persona, memories, skills and logins in two commands — free and local

Body: short version of Show HN post + the two commands + note that Claude Code → Codex was one of the live-tested paths (real binaries, offline containers).

## 4. X thread (6 posts)
1. Every time you switch AI coding CLIs you rebuild your agent from scratch. Persona, memory, skills, API keys. I got tired of it, so: AIM — Agent Identity Migration.
2. Two commands: `aim export --harness claude-code` → `aim import --harness codex`. 10 harnesses, any direction, Linux/macOS/Windows. Think Samsung Smart Switch, for agents.
3. Secrets: scanned out of the export with a 30+ pattern redactor, stored in an encrypted vault. And the vault is standard age format — decrypt it with the stock `age` CLI. No lock-in, not even to this tool.
4. Trust: 100% local. No telemetry, no account, no network calls. 34 tests, 3-OS CI, live spot-checks where real CLIs booted offline with migrated state.
5. Free, MIT: github.com/roryquarrier/aim — `pipx install aim-migrate`
6. Try it: which harness are you on, and which one are you eyeing? The 10: Claude Code, Codex, OpenCode, Goose, Hermes, OpenClaw, Buzz, Grok Build, DeepSeek Harness, Roo Code.

## 5. Harness Discords (Claude Code / OpenAI / Goose communities)
One-liner + link, in their #tools channels:
"Built a free CLI that migrates an agent's persona/memories/skills/settings between 10 harnesses (incl. <their harness>) — local, no telemetry, secrets in an age-compatible vault: https://github.com/roryquarrier/aim"
