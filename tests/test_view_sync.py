"""Saved views sync between computers, and the phone's list holds every computer's views.

Each computer used to write only its own views over the one list the phone reads, so a
view made on one Mac vanished from the phone when the other Mac wrote its list."""

from __future__ import annotations

import json

import httpx
import pytest

from enqueue import crypto, keyring_file, pivots_saved
from enqueue.relay.app import create_relay
from enqueue.sync import client
from enqueue.sync.snapshot import serialize
from tests.test_sync_regressions import _configure, _put, _serve

SPEC = {"subset": {"kind": "everything"}, "steps": []}


@pytest.fixture
def relay(store, monkeypatch):
    keyring_file._dek = None
    monkeypatch.setattr(pivots_saved, "_send", lambda pivot_id: None)
    base, server, thread = _serve(create_relay(store / "relay", secret="test-secret"))
    dek = _configure(base, monkeypatch)
    yield base, dek
    server.should_exit = True
    thread.join(timeout=5)
    keyring_file._dek = None


def _get(base, name, dek):
    r = httpx.get(f"{base}/sync/object/{name}", headers={"Authorization": "Bearer test-secret"})
    assert r.status_code == 200
    return json.loads(crypto.open_payload(r.content, dek))


def _from_other_mac(base, dek, view: dict):
    view = {"_device_id": "other-mac", **view}
    name = f"dev/other-mac/views/{crypto.object_name(view['id'], dek)}.view"
    _put(base, name, crypto.seal_payload(serialize({"view": view}), dek))


def _phone_list(base, dek) -> list[str]:
    return [v["name"] for v in _get(base, "lib/pivots.enc", dek)["views"]]


def _view(pivot_id, name, updated_at, **more):
    groups = {"groups": [{"key": "", "artifact_ids": ["a1"]}]}
    return {
        "id": pivot_id,
        "name": name,
        "spec_json": json.dumps(SPEC),
        "created_at": "2026-01-01T00:00:00+00:00",
        "result_json": json.dumps(groups),
        "result_at": updated_at,
        "updated_at": updated_at,
        **more,
    }


def test_a_view_from_another_mac_arrives_and_reaches_the_phone(relay):
    base, dek = relay
    mine = pivots_saved.save("Mine", SPEC)
    pivots_saved.set_result(mine, {"groups": [{"key": "", "artifact_ids": ["a2"]}]})
    _from_other_mac(base, dek, _view("v-other", "From work", "2099-01-01T00:00:00+00:00"))

    client.pull()

    assert {v["name"] for v in pivots_saved.listing()} == {"Mine", "From work"}
    assert sorted(_phone_list(base, dek)) == ["From work", "Mine"]


def test_a_view_this_mac_saves_goes_up_for_the_others(relay):
    base, dek = relay
    pivot_id = pivots_saved.save("Mine", SPEC)

    client.push_view(pivot_id)

    name = f"dev/{client.device_id()}/views/{crypto.object_name(pivot_id, dek)}.view"
    assert _get(base, name, dek)["view"]["name"] == "Mine"


def test_a_view_deleted_on_another_mac_goes_here_and_stays_gone(relay):
    base, dek = relay
    _from_other_mac(base, dek, _view("v1", "Old", "2099-01-01T00:00:00+00:00"))
    client.pull()
    _from_other_mac(
        base,
        dek,
        {
            "id": "v1",
            "deleted_at": "2099-01-02T00:00:00+00:00",
            "updated_at": "2099-01-02T00:00:00+00:00",
        },
    )
    client.pull()
    assert pivots_saved.listing() == []

    _from_other_mac(base, dek, _view("v1", "Old", "2099-01-03T00:00:00+00:00"))
    client.pull()
    assert pivots_saved.listing() == []


def test_an_older_copy_does_not_undo_a_rename_here(relay):
    base, dek = relay
    pivot_id = pivots_saved.save("Mine", SPEC)
    pivots_saved.rename(pivot_id, "Renamed")
    _from_other_mac(base, dek, _view(pivot_id, "Mine", "2000-01-01T00:00:00+00:00"))

    client.pull()

    assert [v["name"] for v in pivots_saved.listing()] == ["Renamed"]
