# Security Policy

## TL;DR for the paranoid (good — stay that way)
- **Everything runs locally.** AIM has no network code, no telemetry, no accounts, no phone-home. The only network access in the entire project is `pip install` fetching it from PyPI.
- **Secrets never leave your machine unencrypted.** API keys are scanned out of exports with a pattern library (30+ patterns) and stored in a separate vault that is encrypted with your passphrase.
- **The vault is standard `age`.** Since v0.6.0 the vault is byte-compatible with the [age](https://age-encryption.org) v1 format — you can decrypt `secrets.age` in your bundle with the stock `age` CLI: `age -d bundle/secrets.age`. If AIM disappeared tomorrow, your secrets are still yours.
- **Plaintext secrets are never written into the migration bundle.** CI enforces this: the E2E container test fails the build if any known secret pattern appears in the bundle.

## Vault details
- Format: age v1 (scrypt work factor 18 ≈ 256 MiB RAM, ChaCha20-Poly1305, STREAM chunking)
- File keys: 16-byte CSPRNG, unique per bundle
- Passphrase: never stored, never logged; wrong passphrase fails closed

## Reporting a vulnerability
Open a [GitHub security advisory](https://github.com/roryquarrier/aim/security/advisories/new)
or email the maintainer. Please do not open public issues for vulnerabilities.
We aim to respond within 72 hours.

## Scope
- The `aim` CLI, adapters, redaction scanner, and vault format
- Out of scope: the target harnesses' own security (report to them)

## Hardening notes
- scrypt work factor is capped at 18 on decrypt (DoS protection from hostile files)
- All file writes respect the target paths you pass; nothing touches `~` unless you point it there
- `--dry-run` shows every write before it happens
