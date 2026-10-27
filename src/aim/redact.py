"""Secret-redaction scanner (SPEC §4 rule 1). Mandatory at export; fails on unclassifiable hits.

Every distinct secret VALUE gets its own uniquely-numbered placeholder
(${secret:NAME}, ${secret:NAME_2}, ...), so multiple keys of the same type
never collide in the vault.
"""
from __future__ import annotations

import re

# High-confidence named patterns, run FIRST against the original bytes.
# PATTERNS with a capture group: ONLY the group is redacted (key name kept).
PATTERNS: dict[str, re.Pattern] = {
    "ANTHROPIC_API_KEY": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "OPENAI_API_KEY": re.compile(rb"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}"),
    "TELEGRAM_BOT_TOKEN": re.compile(rb"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "GITHUB_TOKEN": re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,}"),
    "AWS_ACCESS_KEY": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "STRIPE_KEY": re.compile(rb"\b[sr]k_(?:live|test)_[A-Za-z0-9]{20,}\b"),
    "SLACK_TOKEN": re.compile(rb"\bxox[abeps]-[A-Za-z0-9-]{10,}\b"),
    "GOOGLE_KEY": re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "AWS_SECRET_KEY": re.compile(rb"""(?i)(aws_secret_access_key)[\"'`\s:=]+([A-Za-z0-9/+=]{30,})"""),
    "JSON_WEB_TOKEN": re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "PRIVATE_KEY_BLOCK": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
}

# Key-path assignments (yaml/toml/json/env): key looks secret AND value still intact.
# Value class extended: specials + short passwords allowed (min 8) when key says password/secret.
ASSIGN_RE = re.compile(
    rb"""(?i)(?<![$:{])(token|api[_-]?key|secret|password|bearer)[\"'`\s:=]+([A-Za-z0-9_\-/+=!@#$%^&*.,;:]{16,})"""
)
PASSWORD_RE = re.compile(
    rb"""(?i)(?<![$:{])(password|passwd)[\\"'`\s:=]+\\?["']?([^\s"'\\{}[\](),;]{8,64})(?=\s|$|["'})\],])"""
)
# value must contain a digit or symbol to count as a credential (kills prose words)


class RedactionResult:
    def __init__(self):
        self.redacted: dict[str, str] = {}  # placeholder -> original value
        self.count = 0

    def merge(self, other: "RedactionResult") -> None:
        for k, v in other.redacted.items():
            self.redacted.setdefault(k, v)
        self.count += other.count


class _Namer:
    """Assigns unique numbered placeholders per value; same value reuses its placeholder."""

    def __init__(self, result: RedactionResult):
        self.result = result
        self.by_value: dict[str, str] = {}
        self.base_count: dict[str, int] = {}

    def ph_for(self, base: str, value: bytes) -> bytes:
        v = value.decode("utf-8", "replace")
        if v in self.by_value:
            return self.by_value[v].encode()
        n = self.base_count.get(base, 0)
        name = base if n == 0 else f"{base}_{n + 1}"
        self.base_count[base] = n + 1
        ph = f"${{secret:{name}}}"
        self.by_value[v] = ph
        self.result.redacted[ph] = v
        self.result.count += 1
        return ph.encode()


def scan_bytes(data: bytes, path_hint: str = "", result: "RedactionResult | None" = None) -> tuple[bytes, RedactionResult]:
    """Replace secret-looking spans with ${secret:NAME} placeholders. Returns (clean, result).

    Pass `result` to share a placeholder namespace across multiple calls (e.g. per-file
    scans whose values must not collide) — placeholders are added to it in place."""
    if result is None:
        result = RedactionResult()
    namer = _Namer(result)
    for ph, v in result.redacted.items():  # seed namer so identical values reuse placeholders
        namer.by_value[v] = ph
        base = ph[len("${secret:"):-1]
        m = re.match(r"^(.*)_(\d+)$", base)
        stem, n = (m.group(1), int(m.group(2))) if m else (base, 0)
        namer.base_count[stem] = max(namer.base_count.get(stem, 0), n + 1)

    # Pass 1: named high-confidence patterns. Patterns WITH a capture group keep
    # the preceding key-name text; only the LAST group is redacted.
    for name, pattern in PATTERNS.items():
        def sub_named(match: re.Match, _n=name) -> bytes:
            ng = match.re.groups  # number of groups in this pattern
            if ng:
                value = match.group(ng)  # last group = the secret value
                prefix = match.group(0).rsplit(value, 1)[0]  # text before value
                return prefix + namer.ph_for(_n, value)
            return namer.ph_for(_n, match.group(0))
        data = pattern.sub(sub_named, data)

    # Pass 2: assignment-style. Skip if the overall match already contains a placeholder
    def sub_assign(match: re.Match) -> bytes:
        whole = match.group(0)
        if b"${secret:" in whole:
            return whole
        value = match.group(2)
        key_part = match.group(1)
        base = key_part.decode().upper().replace("-", "_")
        ph = namer.ph_for(base, value)
        return match.group(0).replace(value, ph)

    data = ASSIGN_RE.sub(sub_assign, data)

    # Pass 3: short passwords (min 8) after key names — runs last, skips placeholders.
    # Requires at least one digit/symbol in the value so prose never matches.
    def sub_pw(match: re.Match) -> bytes:
        whole = match.group(0)
        if b"${secret:" in whole:
            return whole
        value = match.group(2)
        if not re.search(rb"[0-9!@#$%^&*+=._,\-/~?<>|:;]", value):
            return whole  # plain word — not a credential
        return whole.replace(value, namer.ph_for("PASSWORD", value))

    data = PASSWORD_RE.sub(sub_pw, data)
    return data, result
