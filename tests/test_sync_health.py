"""Sync that goes wrong quietly must say so: changes sealed under another device's key, a
push the relay never took, a pull stuck for minutes, and a joined key left unused."""

from __future__ import annotations


import httpx
import nacl.utils
import pytest

from enqueue import config, crypto, keyring, keyring_file, notes, setup, telemetry
from enqueue.relay.app import create_relay
from enqueue.sync import client, worker
from enqueue.sync.snapshot import serialize
from tests.test_sync_regressions import _configure, _foreign_note_snapshot, _put, _serve


@pytest.fixture(autouse=True)
def _reset_dek():
    keyring_file._dek = None
    yield
    keyring_file._dek = None


@pytest.fixture
def reports(monkeypatch):
    out: list[tuple] = []
    monkeypatch.setattr(telemetry, "report", lambda *a, **k: out.append(a))
    return out


@pytest.fixture
def relay(store, monkeypatch):
    base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
    dek = _configure(base, monkeypatch)
    yield base, dek
    server.should_exit = True
    thread.join(timeout=5)


def _note(aid: str, body: str) -> bytes:
    return serialize(
        _foreign_note_snapshot(
            aid=aid, body=body, content_hash=f"h-{aid}", updated_at="2099-01-01T00:00:00+00:00"
        )
    )


def test_changes_sealed_under_another_key_are_flagged(relay, reports):
    base, dek = relay
    other_key = nacl.utils.random(32)
    _put(base, "dev/work-mac/artifacts/a.enc", crypto.encrypt(_note("a", "x"), other_key))
    _put(base, "dev/work-mac/artifacts/b.enc", crypto.encrypt(_note("b", "y"), other_key))

    result = client.pull()

    assert result["unreadable"] == 2
    assert client.unreadable_devices()["work-mac"]["count"] == 2
    assert reports and reports[0][:2] == ("sync", "KeyMismatch")
    alerts = {a["id"] for a in setup.status()["alerts"]}
    assert "sync-key-mismatch" in alerts

    # Once that device seals under the shared key again, the warning goes.
    _put(base, "dev/work-mac/artifacts/c.enc", crypto.encrypt(_note("c", "z"), dek))
    client.pull()
    assert client.unreadable_devices() == {}


def test_a_push_the_relay_never_took_is_sent_again(store, monkeypatch, reports):
    monkeypatch.setattr(client, "_relay_url", lambda: "http://127.0.0.1:9")
    keyring_file.initialize()
    note = notes.create(body="written while the relay was down")
    aid = note["artifact"]["id"]
    client.push_artifact(aid)
    assert aid in client._unpushed()

    sent: list[str] = []
    monkeypatch.setattr(client, "push_artifact", sent.append)
    assert client.retry_unpushed() == 1 and sent == [aid]


def test_a_pushed_note_is_no_longer_owed(relay):
    note = notes.create(body="reaches the relay")
    aid = note["artifact"]["id"]
    client._owe_push(aid)
    client.push_artifact(aid)
    assert aid not in client._unpushed()


def test_a_pull_failing_for_ten_minutes_is_reported_once(monkeypatch, reports):
    clock = [1000.0]
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker, "_fail_streak", 0)

    def down():
        raise httpx.ConnectError("relay down")

    monkeypatch.setattr(worker, "pull", down)
    for step in (0, 300, 601, 900):
        clock[0] = 1000.0 + step
        worker._pull_handler(None)
    stuck = [r for r in reports if r[1] == "PullStuck"]
    assert len(stuck) == 1 and "10 min" in stuck[0][2]
    worker._fail_streak = 0
    worker._backoff_until = 0.0


def test_a_joined_key_is_used_at_once(store, monkeypatch):
    keyring_file.initialize()
    old = keyring_file.dek()
    shared = nacl.utils.random(32)
    keyring.dek_store(shared)
    keyring_file.use(shared)
    assert keyring_file.dek() == shared != old


def test_joining_the_accounts_key_sets_this_macs_aside(store, monkeypatch):
    from enqueue import account

    monkeypatch.setattr(account, "sign_out", lambda: None)
    keyring_file.initialize()
    account.join_account_key()
    assert not keyring_file.is_initialized() and keyring_file.dek() is None
    assert list(config.DATA_DIR.glob("keyring.before-join-*.json"))


def test_a_join_pulls_everything_again(store, monkeypatch):
    from enqueue.sync import join

    client._write_cursor(1996)
    keyring_file.initialize()
    from enqueue.sync import enable as enable_mod

    monkeypatch.setattr(enable_mod, "enable", lambda *a, **k: None)
    monkeypatch.setattr(join, "_token", lambda: "t")
    monkeypatch.setattr(join, "_relay", lambda: "http://127.0.0.1:9")
    monkeypatch.setattr(client, "pull", lambda: {"pulled": 0})
    shared = nacl.utils.random(32)
    monkeypatch.setattr(
        crypto, "open_sealed", lambda _p, _s: ('{"dek": "%s"}' % shared.hex()).encode()
    )
    join._receive(None, b"sealed")
    assert client._read_cursor() == 0
    assert keyring_file.dek() == shared
