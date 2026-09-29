"""Map-reduce for long documents: section summaries instead of a truncated opening."""

from __future__ import annotations

import uuid

from enqueue import config, db
from enqueue.ingest import source


class _Provider:
    name = "fake"

    def __init__(self, model="ingest-model", fail=False):
        self.model = model
        self.fail = fail
        self.users: list[str] = []

    def complete(self, system, user, response_model, context=None, max_retries=None):
        self.users.append(user)
        if self.fail:
            raise RuntimeError("model down")
        section = user.split("\n")[1]  # "Section i of n"
        return response_model(summary=f"Summary of {section.lower()}.")


def _patch(monkeypatch, provider):
    import enqueue.providers.base as base_mod

    monkeypatch.setattr(base_mod, "get_provider", lambda **kw: provider)
    return provider


def _doc(body: str, status: str = "ok") -> str:
    aid = str(uuid.uuid4())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, kind, title, body, content_hash, status, created_at,"
            " updated_at) VALUES (?, 'note', 'A long read', ?, ?, ?, ?, ?)",
            (aid, body, aid, status, db.now(), db.now()),
        )
    return aid


def _text(aid):
    conn = db.get_conn()
    try:
        return source.ingest_text(conn, aid)
    finally:
        conn.commit()
        conn.close()


def _long_body(n_paras: int = 30) -> str:
    return "\n\n".join(f"Paragraph {i}. " + ("filler " * 150) for i in range(n_paras))


def test_sections_split_on_paragraphs_and_keep_everything():
    body = _long_body()
    parts = source.sections(body)
    assert len(parts) > 1
    assert all(len(p) <= source.SECTION_CHARS for p in parts)
    assert "\n\n".join(parts) == body


def test_one_enormous_paragraph_is_hard_split():
    parts = source.sections("x" * (source.SECTION_CHARS * 2 + 5))
    assert [len(p) for p in parts] == [source.SECTION_CHARS, source.SECTION_CHARS, 5]


def test_a_short_document_is_read_whole_without_a_model_call(store, monkeypatch):
    provider = _patch(monkeypatch, _Provider())
    assert _text(_doc("A short note.")) == "A short note."
    assert provider.users == []


def test_a_long_document_is_read_as_ordered_section_summaries(store, monkeypatch):
    provider = _patch(monkeypatch, _Provider())
    body = _long_body()
    n = len(source.sections(body))
    aid = _doc(body)

    text = _text(aid)

    assert len(body) > config.FACET_INPUT_CHARS
    assert len(provider.users) == n
    assert text.startswith("(A long document, read as summaries of its sections in order.)")
    assert f"Section {n} of {n}: Summary of section {n} of {n}." in text
    # The tail of the document reaches the model, which truncation never allowed.
    assert "Paragraph 29." in provider.users[-1]


def test_summaries_are_cached_per_section_and_model(store, monkeypatch):
    first = _patch(monkeypatch, _Provider())
    aid = _doc(_long_body())
    _text(aid)
    calls = len(first.users)

    again = _patch(monkeypatch, _Provider())
    _text(aid)
    assert again.users == []

    other_model = _patch(monkeypatch, _Provider(model="another-model"))
    _text(aid)
    assert len(other_model.users) == calls


def test_a_failed_section_falls_back_to_the_capped_opening(store, monkeypatch):
    _patch(monkeypatch, _Provider(fail=True))
    body = _long_body()
    assert _text(_doc(body)) == body[: config.FACET_INPUT_CHARS]


def test_secret_flagged_text_is_never_mapped(store, monkeypatch):
    provider = _patch(monkeypatch, _Provider())
    body = _long_body()
    assert _text(_doc(body, status="text_only")) == body[: config.FACET_INPUT_CHARS]
    assert provider.users == []


def test_sections_past_the_cap_are_dropped(store, monkeypatch):
    provider = _patch(monkeypatch, _Provider())
    monkeypatch.setattr(source, "MAX_SECTIONS", 2)
    _text(_doc(_long_body()))
    assert len(provider.users) == 2
