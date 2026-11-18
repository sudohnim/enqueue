from datetime import datetime, timedelta, timezone

from enqueue import db, searches


def test_record(store):
    searches.record("hello", [{"artifact_id": "a"}, {"artifact_id": "b"}], "search")
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT query, hits, loose, source FROM searches").fetchone()
    finally:
        conn.close()
    assert row["query"] == "hello"
    assert row["hits"] == '["a", "b"]'
    assert row["loose"] == 0
    assert row["source"] == "search"


def test_record_does_not_raise(store, monkeypatch):
    # broken hit list
    searches.record("x", [{"no_id": 1}], "search")


def test_prune(store):
    conn = db.get_conn()
    try:
        old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        conn.execute(
            "INSERT INTO searches (query, hits, loose, source, created_at) VALUES (?,?,?,?,?)",
            ("old", "[]", 0, "search", old),
        )
        conn.execute(
            "INSERT INTO searches (query, hits, loose, source, created_at) VALUES (?,?,?,?,?)",
            ("new", "[]", 0, "search", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    searches.prune()
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT query FROM searches").fetchall()
    finally:
        conn.close()
    assert [r["query"] for r in rows] == ["new"]
