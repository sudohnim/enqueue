"""Credential detection, run before any text reaches a model.

`scan` records what a note holds (the Settings list of secret hits); `redact` blanks
the same shapes out of every prompt a remote model is sent (providers/ollama.py), so
a credential in a note, a PDF or a page never leaves the machine while the rest of
the text still gets its summary.

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


# A whole PEM private key, header to footer: the header alone is what `scan` reports,
# but the base64 body between is the secret itself.
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S
)


def redact(text: str) -> str:
    """`text` with every credential value replaced by REDACTION."""
    if not text:
        return text
    text = _PRIVATE_KEY_BLOCK.sub(REDACTION, text)
    for _kind, pattern in _PATTERNS:
        text = pattern.sub(lambda m: m.group(0).replace(m.group("value"), REDACTION), text)
    return text


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
