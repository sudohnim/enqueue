"""Shared notes: sealed on the Mac, stored on the relay, readable only with the link."""

from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from enqueue import db, notes, share, trash
from enqueue.relay.app import create_relay
from tests.test_sync_regressions import _configure, _serve

from .test_relay_plans import _device, _hook, _event, _relay
from .test_relay_accounts import _sign_in


@pytest.fixture
def relay(store, monkeypatch):
    share._bases.clear()
    base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
    _configure(base, monkeypatch)
    yield base
    server.should_exit = True
    thread.join(timeout=5)


def _fetch(base: str, url: str) -> tuple[int, bytes]:
    sid = url.split("/s/")[1].split("#")[0]
    r = httpx.get(f"{base}/share/{sid}", timeout=5)
    return r.status_code, r.content


def _open(base: str, url: str, passphrase: str | None = None) -> dict:
    status, data = _fetch(base, url)
    assert status == 200
    link_key = share._unb64(url.split("#")[1])
    return share.open_sealed(share.seal_key(link_key, passphrase), data)


def test_a_shared_note_opens_with_its_link_and_nothing_else(relay):
    aid = notes.create(body="# Trip\n\nPack the blue tent.")["artifact"]["id"]

    got = share.create(aid)

    assert got["shared"] and got["url"].startswith(f"{relay}/s/")
    assert _open(relay, got["url"])["body"] == "# Trip\n\nPack the blue tent."
    _, data = _fetch(relay, got["url"])
    assert b"blue tent" not in data
    with pytest.raises(Exception):
        share.open_sealed(b"\0" * 32, data)


def test_a_passphrase_is_needed_besides_the_link(relay):
    aid = notes.create(body="Locker code ideas.")["artifact"]["id"]

    url = share.create(aid, passphrase="correct horse")["url"]

    assert _open(relay, url, "correct horse")["body"] == "Locker code ideas."
    with pytest.raises(Exception):
        _open(relay, url)


def test_an_update_replaces_the_copy_and_keeps_the_link(relay):
    aid = notes.create(body="First draft.")["artifact"]["id"]
    url = share.create(aid)["url"]
    notes.edit(aid, "Second draft.")

    assert share.info(aid)["changed"] is True
    assert _open(relay, url)["body"] == "First draft."

    after = share.update(aid)

    assert after["url"] == url and after["changed"] is False
    assert _open(relay, url)["body"] == "Second draft."


def test_stopping_makes_the_link_open_nothing(relay):
    aid = notes.create(body="Short-lived.")["artifact"]["id"]
    url = share.create(aid)["url"]

    share.stop(aid)

    assert _fetch(relay, url)[0] == 404
    assert share.info(aid) == {"shared": False}


def test_a_trashed_note_stops_being_shared(relay):
    aid = notes.create(body="Going to the trash.")["artifact"]["id"]
    url = share.create(aid)["url"]
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET deleted_at = ? WHERE id = ?", (db.now(), aid))

    assert share.retry_stops() == 1
    assert _fetch(relay, url)[0] == 404


def test_trash_delete_stops_sharing_in_the_background(relay):
    aid = notes.create(body="Binned.")["artifact"]["id"]
    url = share.create(aid)["url"]

    trash.delete(aid)

    for _ in range(50):
        if _fetch(relay, url)[0] == 404:
            break
        time.sleep(0.05)
    assert _fetch(relay, url)[0] == 404


def test_only_live_notes_kept_off_this_mac_can_be_shared(relay):
    aid = notes.create(body="Private to this Mac.")["artifact"]["id"]
    with db.transaction() as conn:
        conn.execute("UPDATE artifacts SET local_only = 1 WHERE id = ?", (aid,))

    with pytest.raises(share.ShareError):
        share.create(aid)


def test_sharing_needs_sync(store):
    aid = notes.create(body="No relay here.")["artifact"]["id"]

    with pytest.raises(share.ShareError) as exc:
        share.create(aid)
    assert exc.value.code == "sync"


def test_shares_never_reach_the_sync_feed(relay):
    aid = notes.create(body="Shared, not synced.")["artifact"]["id"]
    share.create(aid)

    names = httpx.get(
        f"{relay}/sync/objects", headers={"Authorization": "Bearer test-secret"}, timeout=5
    ).json()["objects"]

    assert not [o for o in names if o["name"].startswith("share/")]


def test_an_expired_share_is_gone(tmp_path):
    relay = TestClient(create_relay(tmp_path / "relay", secret="test-secret"))
    sid = "A" * 22
    put = relay.put(
        f"/share/{sid}",
        content=b"sealed",
        params={"expires_at": time.time() + 0.2},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert put.status_code == 201
    assert relay.get(f"/share/{sid}").content == b"sealed"
    time.sleep(0.3)
    assert relay.get(f"/share/{sid}").status_code == 404


def test_another_library_cannot_take_or_stop_a_share(tmp_path):
    relay = TestClient(
        create_relay(tmp_path / "relay", secret="test-secret", admin_secret="admin-secret")
    )
    other = relay.post(
        "/admin/libraries",
        json={"label": "other"},
        headers={"Authorization": "Bearer admin-secret"},
    ).json()["secret"]
    sid = "B" * 22
    relay.put(f"/share/{sid}", content=b"mine", headers={"Authorization": "Bearer test-secret"})

    taken = relay.put(
        f"/share/{sid}", content=b"theirs", headers={"Authorization": f"Bearer {other}"}
    )
    relay.delete(f"/share/{sid}", headers={"Authorization": f"Bearer {other}"})

    assert taken.status_code == 409
    assert relay.get(f"/share/{sid}").content == b"mine"


def test_sharing_is_pro_on_the_hosted_relay(tmp_path, monkeypatch):
    relay = _relay(tmp_path, monkeypatch)
    pair = _sign_in(relay)
    token = _device(relay, pair, "Mac", "computer").json()["relay_token"]
    sid = "C" * 22
    auth = {"Authorization": f"Bearer {token}"}

    assert relay.put(f"/share/{sid}", content=b"x", headers=auth).status_code == 402

    account_id = relay.get(
        "/account/plan", headers={"Authorization": f"Bearer {pair['access_token']}"}
    ).json()["account_id"]
    _hook(relay, _event(account_id))
    assert relay.put(f"/share/{sid}", content=b"x", headers=auth).status_code == 201


def test_the_viewer_is_served_with_a_strict_policy(tmp_path):
    relay = TestClient(create_relay(tmp_path / "relay", secret="test-secret"))

    page = relay.get("/s/" + "D" * 22)
    script = relay.get("/s/static/share.js")

    assert page.status_code == 200 and "share.js" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert script.status_code == 200
    assert relay.get("/s/static/../app.py").status_code == 404
    assert relay.get("/s/fonts/HankenGrotesk-latin.woff2").status_code == 200
