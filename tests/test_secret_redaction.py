"""A credential never reaches a remote model (ingest/secrets.py `redact`).

Before, a note flagged for holding a secret was still sent whole to the ingest model
for its facets and entities, and chat could quote it; PDFs were never scanned at all.
Every structured call now blanks credential shapes on its way out.
"""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from enqueue.ingest.secrets import REDACTION, redact
from enqueue.providers.ollama import OpenAICompatibleProvider

KEY = "AKIAIOSFODNN7EXAMPLE"
PEM = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def test_redact_blanks_each_credential_shape_and_keeps_the_rest():
    text = (
        "Server notes for the kiln controller.\n"
        f"aws id {KEY}\n"
        "sftp password = hunter2hunter2\n"
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n"
        "slack xoxb-1234567890-abcdefghij\n"
        "gh ghp_abcdefghijklmnopqrstuvwxyz0123\n" + PEM + "\nThe controller runs cone six."
    )
    out = redact(text)
    for secret in (
        KEY,
        "hunter2hunter2",
        "abcdefghijklmnopqrstuvwxyz123456",
        "xoxb-1234567890",
        "ghp_abcdefghij",
        "b3BlbnNzaC1rZXkt",
        "BEGIN OPENSSH",
    ):
        assert secret not in out
    assert "Server notes for the kiln controller." in out
    assert "The controller runs cone six." in out
    assert "sftp password = " + REDACTION in out


def test_redact_leaves_ordinary_prose_alone():
    prose = "A token of thanks for the potter who taught me to center clay."
    assert redact(prose) == prose


class _Reply(BaseModel):
    ok: bool = True


def _capturing(provider):
    sent = []

    def create(**kwargs):
        sent.append(kwargs["messages"])
        return _Reply()

    provider._instructor = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return sent


def test_a_remote_model_is_sent_the_note_with_its_key_blanked():
    remote = OpenAICompatibleProvider(model="m", base_url="https://models.example/v1")
    sent = _capturing(remote)

    remote.complete(system="Summarize.", user=f"Deploy notes. Key {KEY}.", response_model=_Reply)

    prompt = str(sent[0])
    assert KEY not in prompt
    assert "Deploy notes." in prompt


def test_a_local_model_reads_the_note_as_written():
    local = OpenAICompatibleProvider(model="m", base_url="http://127.0.0.1:11434/v1")
    sent = _capturing(local)

    local.complete(system="Summarize.", user=f"Deploy notes. Key {KEY}.", response_model=_Reply)

    assert KEY in str(sent[0])
