"""Credential detection, run before any text reaches a model.

This is not a sensitivity classifier. It catches credential shapes, not private
material. Personal content is handled by the local_only flag instead.

The source corpus is known to contain a plaintext SFTP password.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REDACTION = "***"


@dataclass
class SecretHit:
    kind: str
    line: int
    excerpt: str  # value already replaced with REDACTION


_ASSIGNMENT_KEYS = r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key)"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "assignment",
        re.compile(rf"""(?ix)
            \b{_ASSIGNMENT_KEYS}\b
            \s*[:=]\s*
            (?P<value>"[^"]{{3,}}"|'[^']{{3,}}'|\S{{3,}})
            """),
    ),
    ("aws_access_key_id", re.compile(r"\b(?P<value>(?:AKIA|ASIA)[0-9A-Z]{16})\b")),
    ("private_key", re.compile(r"(?P<value>-----BEGIN [A-Z ]*PRIVATE KEY-----)")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+(?P<value>[A-Za-z0-9._\-]{20,})")),
    ("slack_token", re.compile(r"\b(?P<value>xox[baprs]-[A-Za-z0-9-]{10,})\b")),
    ("github_token", re.compile(r"\b(?P<value>gh[pousr]_[A-Za-z0-9]{20,})\b")),
]


def scan(text: str) -> list[SecretHit]:
    """Return credential hits. Never returns the secret value itself."""
    hits: list[SecretHit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(line):
                value = match.group("value")
                redacted = line.replace(value, REDACTION)
                if len(redacted) > 160:
                    redacted = redacted[:157] + "..."
                hits.append(SecretHit(kind=kind, line=lineno, excerpt=redacted.strip()))
    return hits
