"""A note's drafts: what is kept, what each one changed, going back to one, and the
switch that stops them."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from enqueue import config, db, drafts, notes, settings

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _at(**ago) -> str:
    return (NOW - timedelta(**ago)).isoformat()


class TestWhatIsKept:
    def test_the_ladder(self):
        made = [
            ("first", _at(days=400)),
            ("old-a", _at(days=200)),  # same week as old-b: one of them goes
            ("old-b", _at(days=200, hours=1)),
            ("month-a", _at(days=40)),
            ("month-b", _at(days=40, hours=2)),  # same day: one goes
            ("week-a", _at(days=3, minutes=10)),
            ("week-b", _at(days=3, minutes=40)),  # same hour: one goes
            ("today-a", _at(hours=5)),
            ("today-b", _at(hours=5, minutes=5)),  # within a day: both stay
            ("latest", _at(minutes=1)),
        ]
        kept = drafts.keep(made, "thinned", NOW)
        assert {"first", "latest", "today-a", "today-b"} <= kept
        assert len(kept & {"old-a", "old-b"}) == 1
        assert len(kept & {"month-a", "month-b"}) == 1
        assert len(kept & {"week-a", "week-b"}) == 1
        # Of two in one bucket, the later stands.
        assert {"old-a", "month-a", "week-a"} <= kept

    def test_thirty_days_and_off(self):
        made = [("first", _at(days=90)), ("mid", _at(days=40)), ("new", _at(days=2))]
        assert drafts.keep(made, "30d", NOW) == {"first", "new"}
        assert drafts.keep(made, "off", NOW) == {"new"}
        assert drafts.keep(made, "thinned", NOW, keep_all=False) == {"new"}
        assert drafts.keep([], "thinned", NOW) == set()


@pytest.fixture
def note(store, quiet_queue, monkeypatch):
    monkeypatch.setattr(config, "DRAFT_EVERY_S", 300)
    from enqueue.sync import client

    monkeypatch.setattr(client, "push_artifact", lambda *a, **k: None)
    return notes.create(body="# Trip\n\nbook on amex for points")["artifact"]["id"]


def _drafts(aid):
    conn = db.get_conn()
    try:
        return [
            r["body"]
            for r in conn.execute(
                "SELECT body FROM artifact_versions WHERE artifact_id = ? ORDER BY created_at, id",
                (aid,),
            )
        ]
    finally:
        conn.close()


def _age_all(aid, seconds):
    with db.transaction() as conn:
        for r in conn.execute(
            "SELECT id, created_at FROM artifact_versions WHERE artifact_id = ?", (aid,)
        ).fetchall():
            when = datetime.fromisoformat(r["created_at"]) - timedelta(seconds=seconds)
            conn.execute(
                "UPDATE artifact_versions SET created_at = ? WHERE id = ?",
                (when.isoformat(), r["id"]),
            )


class TestTheList:
    def test_each_draft_says_what_it_changed(self, note):
        _age_all(note, 3600)
        notes.edit(note, "# Trip\n\nbook on chase for points\n\nDO NOT BOOK AGODA")
        listed = drafts.listing(note)
        assert listed["keep"] is True
        newest, first = listed["drafts"]
        assert newest["current"] is True
        assert newest["added"] == 5 and newest["removed"] == 1
        assert newest["first"].startswith("chase")
        assert first["first"].startswith("# Trip")

    def test_restoring_keeps_todays_text(self, note):
        _age_all(note, 3600)
        first_id = drafts.listing(note)["drafts"][-1]["id"]
        notes.edit(note, "# Trip\n\nsomething I regret")
        drafts.restore(note, first_id)
        assert notes.get(note)["artifact"]["body"] == "# Trip\n\nbook on amex for points"
        bodies = _drafts(note)
        assert "# Trip\n\nsomething I regret" in bodies, "today's text became a draft"
        assert bodies[-1] == "# Trip\n\nbook on amex for points"


class TestTheSwitch:
    def test_off_keeps_only_the_latest_and_stops_new_ones(self, note):
        for i in range(3):
            _age_all(note, 3600)
            notes.edit(note, f"# Trip\n\nedit {i}")
        assert len(_drafts(note)) == 4
        out = drafts.set_keep(note, False)
        assert out["removed"] == 3 and _drafts(note) == ["# Trip\n\nedit 2"]
        _age_all(note, 3600)
        notes.edit(note, "# Trip\n\nedit 3")
        assert _drafts(note) == ["# Trip\n\nedit 3"], "the latest still follows the writing"
        drafts.set_keep(note, True)
        _age_all(note, 3600)
        notes.edit(note, "# Trip\n\nedit 4")
        assert len(_drafts(note)) == 2

    def test_the_phone_hears_of_it(self, note, monkeypatch):
        """Thinning and the switch push the note, so the phone's copy follows; unpushed,
        its next edit would bring every removed draft back."""
        from enqueue.sync import client

        pushed = []
        monkeypatch.setattr(client, "push_artifact", pushed.append)
        for i in range(2):
            _age_all(note, 3600)
            notes.edit(note, f"# Trip\n\nedit {i}")
        pushed.clear()
        drafts.set_keep(note, False)
        assert pushed == [note], "removing drafts pushed the note once"
        drafts.set_keep(note, True)
        assert pushed == [note, note], "turning it back on pushed the switch"

    def test_the_library_policy(self, note, monkeypatch):
        settings.update({"drafts_keep": "off"})
        _age_all(note, 3600)
        notes.edit(note, "# Trip\n\nlater")
        assert _drafts(note) == ["# Trip\n\nlater"]
        with pytest.raises(ValueError):
            settings.update({"drafts_keep": "forever"})


def test_the_endpoints(note):
    from fastapi.testclient import TestClient

    from enqueue.api.app import create_app

    client = TestClient(create_app())
    listed = client.get(f"/artifacts/{note}/drafts").json()
    vid = listed["drafts"][0]["id"]
    assert client.get(f"/artifacts/{note}/drafts/{vid}").json()["body"].startswith("# Trip")
    assert client.put(f"/artifacts/{note}/drafts/keep", json={"on": False}).json()["keep"] is False
    assert client.get("/drafts").json()["drafts"] == 1
    assert client.post(f"/artifacts/{note}/drafts/{vid}/restore").status_code == 200
    assert client.get("/artifacts/nope/drafts").status_code == 404
