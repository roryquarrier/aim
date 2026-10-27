1. **CRITICAL** — `src/aim/adapters/common.py:write_common_import` (and `src/aim/adapters/codex/adapter.py:CodexAdapter.import_`, `src/aim/adapters/deepseek_harness/adapter.py:DeepseekHarnessAdapter.import_`)  
   **Description:** Skill name validation uses `re.fullmatch(r"[A-Za-z0-9._-]+", s.name)`, which accepts `..` as a valid skill name. In `write_common_import`, `sdir = home / "skills" / s.name` with `s.name = ".."` resolves to `home`. The subsequent `(sdir / "SKILL.md").write_text(...)` and script writes (via `_safe_relpath(sdir, rel, ...)`) then write to the root of the target home. An attacker can set a script `rel = "AGENTS.md"` to overwrite the persona file, or any other file inside the target home. In Codex/Deepseek, the same `s.name` is used to compute `d = home.parent / ".agents" / "skills" / s.name`, so `s.name = ".."` makes `d = home.parent / ".agents"`, allowing arbitrary file writes into the real `~/.agents` directory outside the target home.  
   **Fix:** Reject `.` and `..` as skill names. Use `_safe_relpath(home / "skills", s.name, "skill name")` and verify `sdir.parent == home / "skills"`. In Codex/Deepseek, re-validate or reuse the already-safe skill directory.

2. **CRITICAL** — `src/aim/osadjust/adjust.py:transactional_import` (with `src/aim/adapters/claude_code/adapter.py:ClaudeCodeAdapter.import_`, `src/aim/adapters/codex/adapter.py:CodexAdapter.import_`, `src/aim/adapters/deepseek_harness/adapter.py:DeepseekHarnessAdapter.import_`)  
   **Description:** `transactional_import` stages into `staging = home.parent / f".{home.name}.aimstage.{os.getpid()}"` and calls `stage_fn(staging)`. Adapters that write outside the home (Claude Code writes `home.parent / ".claude.json"`; Codex/Deepseek write `home.parent / ".agents" / "skills"`) compute these paths from `staging.parent`, which is the **real** parent directory, not the staging directory. These writes happen directly to the user's live filesystem before the atomic swap, are not backed up by `snapshot_home`, and are not rolled back if a later step fails. This can silently overwrite `~/.claude.json` or `~/.agents` and lose data on failure.  
   **Fix:** Have adapters write all external files into the staging home (e.g., stage a modified `.claude.json` inside staging) and extend `transactional_import` to atomically move those into place. Alternatively, back up and restore every external file touched during staging.

3. **CRITICAL** — `src/aim/cli.py:export` / `src/aim/redact.py:scan_bytes` / `src/aim/bundle.py:BundleWriter.write`  
   **Description:** `state.model_dump_json()` serializes `Skill.scripts` (`dict[str, bytes]`) as base64 strings inside `state.json`. `scan_bytes` is run on the resulting JSON text, so it sees base64-encoded data, not the original secret strings. Any API key, token, or private key embedded in a skill script is therefore **not redacted**, remains in plain base64 in `state.json`, and is **not** encrypted even when `--with-secrets` is used.  
   **Fix:** Before serialization, iterate over `state.skills`, run `scan_bytes` on each script’s raw bytes, replace secret spans with placeholders, and merge the captured values into the vault. Update the import side to restore placeholders inside decoded script bytes.

4. **CRITICAL** — `src/aim/cli.py:restore_backup`  
   **Description:** The function renames the target home to `tmp_old`, then calls `shutil.copytree(bdir, target, ...)`. If `copytree` fails (disk full, permission error, interrupted), the exception propagates, `target` may be partially written or missing, and `tmp_old` is never restored. The user’s original home is left stranded at `tmp_old`, and the target path is corrupted.  
   **Fix:** Wrap the `copytree` in `try/except`; on failure, if `tmp_old` exists, rename it back to `target` and remove any partial target before re-raising.

5. **HIGH** — `src/aim/adapters/buzz/adapter.py:BuzzAdapter.import_`  
   **Description:** The workflow YAML is built with an f-string: `note: migrated by aim from {j.model_dump().get('name', ...)}`. `j.name` comes from the untrusted bundle and is not YAML-escaped. An attacker can set a job name containing newlines and YAML keys (e.g., `foo\naction: exec`) to inject arbitrary YAML into `imported-schedule-*.yaml`. When Buzz parses the workflow, the injected `action` can override the intended `notify` action, potentially leading to command execution.  
   **Fix:** Build a Python dict and serialize it with `yaml.safe_dump`, or at minimum apply `json.dumps` to the name when embedding it in the scalar.

6. **HIGH** — `src/aim/adapters/common.py:_safe_relpath` (used by `write_common_import`)  
   **Description:** `_safe_relpath` resolves the full path (`(home / rel).resolve()`) and returns it. The caller then writes to that resolved absolute path. If a local attacker can modify the staging directory between the check and the write, they can replace the resolved path with a symlink pointing outside the home. The subsequent `write_text`/`write_bytes` will follow the symlink and write outside the intended directory (TOCTOU). This is exploitable when the staging parent is in a shared writable location (e.g., `/tmp`).  
   **Fix:** Use `os.open` with `O_CREAT | O_WRONLY | O_NOFOLLOW` relative to a directory file descriptor, or re-check with `os.path.realpath` immediately before writing and reject symlinks.

7. **HIGH** — `src/aim/bundle.py:BundleReader.verify_hashes`, `BundleReader.state`, and `src/aim/secrets.py:decrypt`  
   **Description:** `verify_hashes` iterates over all zip members and calls `self.read(relpath)`, which decompresses the entire member into memory. `state()` reads `state.json` into memory. `decrypt()` reads the entire `secrets.age` into memory and decrypts all chunks into a `BytesIO`. There are no size limits. A hostile bundle containing a highly compressed 10 GB file (zip bomb) or a huge `state.json`/`secrets.age` will cause memory exhaustion and crash the process.  
   **Fix:** Enforce maximum uncompressed sizes per member and in total (e.g., using `ZipInfo.file_size` before reading). Cap `state.json` and `secrets.age` sizes (e.g., 50 MB). Stream decryption instead of accumulating plaintext in memory.

8. **HIGH** — `src/aim/adapters/roo/adapter.py:RooAdapter.import_`  
   **Description:** On import, the adapter parses attacker-controlled document content with `yaml.safe_load(body)`. PyYAML’s `safe_load` is vulnerable to YAML alias expansion (“billion laughs” style) DoS attacks. A crafted bundle can contain a document with `kind: profile`, path starting with `modes/`, and a YAML bomb that causes exponential memory/CPU consumption during import.  
   **Fix:** Avoid parsing untrusted YAML, or use a YAML loader with strict alias and depth limits (e.g., `yaml.safe_load` with a custom `Loader` that sets `max_aliases`). Better: store mode data in JSON instead of parsing YAML from document content.

9. **MEDIUM** — `src/aim/adapters/codex/adapter.py:_load_one_skill` and `src/aim/adapters/common.py:read_docs`  
   **Description:** `_load_one_skill` iterates `d.rglob("*")` and reads any file that is not `SKILL.md`, not in `__pycache__`, and not hidden. It does **not** check `f.is_symlink()`. `read_docs` uses `p.is_file()`, which follows symlinks. If a skill directory or persona/memory file is a symlink to a sensitive file (e.g., `~/.ssh/id_rsa`), the export will follow it and include the content in the bundle, leaking secrets.  
   **Fix:** Add `if f.is_symlink(): continue` in `_load_one_skill`, and in `read_docs` check `p.is_symlink()` and skip or raise before reading.

10. **MEDIUM** — `src/aim/bundle.py:_safe_member` and `BundleReader.extract`  
    **Description:** `_safe_member` uses `PurePosixPath(name)` and rejects `..` parts, but does not reject backslashes. On Windows, a member name like `..\\evil.txt` is treated as a single POSIX part, passes the check, but `dest / "..\\evil.txt"` resolves to a parent directory, enabling zip-slip. The reserved-name set is also incomplete (`com2`–`com9`, `lpt2`–`lpt9` missing).  
    **Fix:** Reject any name containing backslashes, drive letters, or UNC paths. Normalize with `os.path.normpath` and verify the resolved path is within `dest`. Use `zipfile.Path` or `extractall(filter='data')` on Python 3.12+.

11. **MEDIUM** — `src/aim/adapters/common.py:_safe_relpath`  
    **Description:** The check `":" in rel.split("/")[0].split("\\")[0]` only rejects a colon in the first path component. On Windows, a later component like `foo/bar:stream` creates an alternate data stream (ADS). The resolved path still appears inside `home`, so the check passes, and `write_text` writes to the ADS. This bypasses the intended path sanitization and can hide malicious data.  
    **Fix:** Reject any colon anywhere in `rel` (or specifically in any component before resolution).

12. **MEDIUM** — `src/aim/bundle.py:BundleWriter.write`  
    **Description:** `Manifest.has_secrets` is declared but never set to `True`. Even when `secrets/secrets.age` is written, the manifest reports `has_secrets: false`. This is misleading and could cause downstream tooling to assume the bundle contains no secrets.  
    **Fix:** Set `manifest.has_secrets = "secrets/secrets.age" in self._files` before writing the manifest.

13. **LOW** — `src/aim/osadjust/adjust.py:harness_running`  
    **Description:** The `probes` dictionary maps `"claude-code": []`. Therefore, `harness_running("claude-code")` always returns `False`, providing no protection against importing while Claude Code is running. This can lead to file corruption or races.  
    **Fix:** Add `"claude"` (or appropriate process names) to the probe list for `claude-code`.

14. **LOW** — `src/aim/secrets.py:_stream_encrypt`  
    **Description:** For a plaintext whose length is an exact multiple of `CHUNK_SIZE`, the code marks the last full chunk as final (`last=True`) instead of writing it with `last=False` followed by an empty final chunk. This violates the age v1 STREAM specification. The produced file is not byte-compatible with the official `age` CLI (though the tool’s own decryptor handles it).  
    **Fix:** Remove the peek logic. Always write full chunks with `last=False`, and after the loop, if the plaintext ended on a chunk boundary, write an empty final chunk with `last=True`.

15. **LOW** — `src/aim/adapters/base.py:autodetect`  
    **Description:** `autodetect` calls `default_homes(cls)`, but `default_homes` is defined as `return []` and no adapter overrides it. Adapters only define `default_home` (singular). As a result, autodetection never checks the default harness homes and fails unless an environment variable or explicit `--home` is provided.  
    **Fix:** Replace `default_homes(cls)` with `[str(cls().default_home())]`, or implement `default_homes` properly in each adapter.

16. **LOW** — `src/aim/secrets.py:_scrypt` / `decrypt`  
    **Description:** In `decrypt`, `work = int(stanza[3])` is taken from the untrusted header. If `work` is negative, `_scrypt` executes `1 << work`, which raises an unhandled `ValueError: negative shift count`. This crashes with a traceback instead of a clean error.  
    **Fix:** Validate `0 <= work <= 18` before calling `_scrypt` and raise a clear `ValueError` for invalid work factors.

**Overall verdict:** The codebase contains multiple critical vulnerabilities—most notably an arbitrary file write via `..` skill names, a broken transactional model that writes outside the staging area, and secret leakage in skill scripts—making it unsafe to run on untrusted bundles without significant remediation.