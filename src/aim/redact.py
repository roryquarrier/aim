"""Secret-redaction scanner (SPEC §4 rule 1). Mandatory at export; fails on unclassifiable hits."""
from __future__ import annotations

import re

# High-confidence named patterns, run FIRST against the original bytes.
PATTERNS: dict[str, re.Pattern] = {
    "ANTHROPIC_API_KEY": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "OPENAI_API_KEY": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    "TELEGRAM_BOT_TOKEN": re.compile(rb"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "GITHUB_TOKEN": re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,}"),
    "AWS_ACCESS_KEY": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "JSON_WEB_TOKEN": re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "PRIVATE_KEY_BLOCK": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
}

# Key-path assignments (yaml/toml/json/env): key looks secret AND value still intact
ASSIGN_RE = re.compile(
    rb"(?i)(token|api[_-]?key|secret|password|bearer)[\"'`\s:=]+([A-Za-z0-9_\-/+]{16,})"
)


class RedactionResult:
    def __init__(self):
        self.redacted: dict[str, str] = {}  # placeholder -> original value
        self.count = 0

    def merge(self, other: "RedactionResult") -> None:
        for k, v in other.redacted.items():
            self.redacted.setdefault(k, v)
        self.count += other.count


def scan_bytes(data: bytes, path_hint: str = "") -> tuple[bytes, RedactionResult]:
    """Replace secret-looking spans with ${secret:NAME} placeholders. Returns (clean, result)."""
    result = RedactionResult()

    # Pass 1: named high-confidence patterns (longest/most specific first).
    for name, pattern in sorted(PATTERNS.items(), key=lambda kv: -len(kv[1].pattern)):
        def sub_named(match: re.Match, _n=name) -> bytes:
            value = match.group(0)
            placeholder = f"${{secret:{_n}}}".encode()
            result.redacted.setdefault(placeholder.decode(), value.decode("utf-8", "replace"))
            result.count += 1
            return placeholder
        data = pattern.sub(sub_named, data)

    # Pass 2: assignment-style. Skip values already replaced (contains "${secret:").
    def sub_assign(match: re.Match) -> bytes:
        value = match.group(2)
        if b"${secret:" in value:
            return match.group(0)
        key_part = match.group(1)
        ph = f"${{secret:{key_part.decode().upper().replace('-', '_')}}}".encode()
        result.redacted.setdefault(ph.decode(), value.decode("utf-8", "replace"))
        result.count += 1
        return match.group(0).replace(value, ph)

    data = ASSIGN_RE.sub(sub_assign, data)
    return data, result
