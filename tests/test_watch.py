from __future__ import annotations

import os
import time

from enqueue import capture, watch


def _ready(store, monkeypatch):
    folder = store / "watched"
    folder.mkdir()
    monkeypatch.setenv("ENQ_WATCH_DIRS", str(folder))
    calls = []

    def fake_upload(data, filename, **kwargs):
        calls.append((filename, kwargs))
        return {"id": "x", "created": True}

    monkeypatch.setattr(capture, "upload", fake_upload)
    return folder, calls


def test_files_present_before_watching_are_left(store, monkeypatch):
    folder, calls = _ready(store, monkeypatch)
    old = folder / "old.txt"
    old.write_text("old", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 120, now - 120))

    assert watch.scan(now=now) == {"taken": 0}
    assert calls == []


def test_a_settled_pdf_written_after_the_first_scan_is_taken(store, monkeypatch):
    folder, calls = _ready(store, monkeypatch)
    first = time.time() - 300
    assert watch.scan(now=first) == {"taken": 0}

    pdf = folder / "new.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    now = time.time()
    os.utime(pdf, (now - 120, now - 120))

    assert watch.scan(now=now) == {"taken": 1}
    assert [name for name, _ in calls] == ["new.pdf"]
    assert calls[0][1] == {"background": True}


def test_the_same_file_is_not_taken_twice(store, monkeypatch):
    folder, calls = _ready(store, monkeypatch)
    first = time.time() - 300
    assert watch.scan(now=first) == {"taken": 0}

    pdf = folder / "same.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    now = time.time()
    os.utime(pdf, (now - 120, now - 120))

    assert watch.scan(now=now) == {"taken": 1}
    assert watch.scan(now=now) == {"taken": 0}
    assert len(calls) == 1


def test_files_that_do_not_qualify_are_skipped(store, monkeypatch):
    folder, calls = _ready(store, monkeypatch)
    assert watch.scan(now=time.time() - 300) == {"taken": 0}

    (folder / "skip.zip").write_bytes(b"zip")
    (folder / ".hidden.txt").write_bytes(b"hidden")
    (folder / "empty.pdf").write_bytes(b"")
    recent = folder / "recent.png"
    recent.write_bytes(b"png")
    now = time.time()
    os.utime(recent, (now - 5, now - 5))

    assert watch.scan(now=now) == {"taken": 0}
    assert calls == []


def test_one_scan_takes_at_most_twenty_five(store, monkeypatch):
    folder, calls = _ready(store, monkeypatch)
    assert watch.scan(now=time.time() - 300) == {"taken": 0}

    now = time.time()
    for i in range(30):
        path = folder / f"new-{i}.txt"
        path.write_bytes(b"text")
        os.utime(path, (now - 120, now - 120))

    assert watch.scan(now=now) == {"taken": 25}
    assert len(calls) == 25
