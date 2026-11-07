"""The model bake-off: which OpenRouter models the included assistant starts on.

`enq eval-bakeoff ingest <model>` reads the cross-domain eval's notes with one ingestion
model (summary lines, names, long-document sections) and scores what it wrote: the
real cost (OpenRouter's own count for the key, reprompts included), the notes whose
every line failed the quality gate, the calls that failed, and the cross-domain eval
with its lines in place of the fixture's.
`enq eval-bakeoff chat <model>` answers the eval's questions from the fixture's library
with one chat model: whether the answer cites the note that answers it, the replies that
failed the answer schema, the cost and the time.
One model per process, so a run never holds two models' state; it never touches the
committed fixture. Uses the OpenRouter key in the Keychain.
"""

from __future__ import annotations

import json
import os
import time

import httpx

from . import eval_cross as xd

OPENROUTER = "https://openrouter.ai/api/v1"


def _key() -> str:
    from . import keyring

    key = keyring.get("openrouter")
    if not key:
        raise RuntimeError("no OpenRouter key in the Keychain (Settings > Assistant)")
    return key


def _spent() -> float:
    """What the key has cost so far, in US dollars, as OpenRouter counts it."""
    r = httpx.get(f"{OPENROUTER}/key", headers={"Authorization": f"Bearer {_key()}"}, timeout=30)
    r.raise_for_status()
    return float(r.json()["data"]["usage"])


def _use(model: str, role: str) -> None:
    os.environ["ENQ_LLM_BACKEND"] = "openrouter"
    os.environ["ENQ_LLM_MODEL"] = model if role == "chat" else "google/gemini-3.8-flash"
    os.environ["ENQ_SUMMARIZE_MODEL"] = model if role == "ingest" else ""
    os.environ["ENQ_SEARCH_MODEL"] = ""


def _cost_since(before: float) -> float:
    time.sleep(15)  # OpenRouter's count trails the calls by a few seconds
    return round(_spent() - before, 4)


def ingest(model: str) -> dict:
    from . import db
    from .index.store import get_store
    from .ingest import entities as entities_mod
    from .ingest import facets as facets_mod
    from .retrieve import candidates as cand

    _use(model, "ingest")
    suite = xd.load_suite()
    before = _spent()
    started = time.monotonic()
    gate, failed, lines = 0, [], 0
    real_judge = cand.judge_gray_zone
    cand.judge_gray_zone = lambda query, hits: {h["artifact_id"] for h in hits}
    try:
        with xd.pointed_at_test_dir():
            xd.build(suite)
            for n in suite["notes"] + suite["decoys"]:
                with db.transaction() as conn:
                    made, error = facets_mod.generate_for_artifact(conn, n["id"])
                lines += made or 0
                if error and "quality gate" in error:
                    gate += 1
                elif error:
                    failed.append(f"{n['id']}: {error}"[:160])
                with db.transaction() as conn:
                    _, error = entities_mod.generate_for_artifact(conn, n["id"])
                if error and "quality gate" not in error:
                    failed.append(f"{n['id']} names: {error}"[:160])
            store = get_store()
            store.upsert_facets()
            store.upsert_entities()
            store.upsert_sections()
            results = xd.run_queries(suite)
    finally:
        cand.judge_gray_zone = real_judge
    notes = len(suite["notes"]) + len(suite["decoys"])
    return {
        "role": "ingest",
        "model": model,
        "cost_usd": _cost_since(before),
        "seconds": round(time.monotonic() - started),
        "notes": notes,
        "summary_lines": lines,
        "notes_failing_the_gate": gate,
        "failed_calls": failed,
        "cross_domain": {k: v for k, v in xd.score(results).items()},
        "ranks": {r["id"]: r["rank"] for r in results},
    }


def chat(model: str) -> dict:
    from . import chats
    from .providers.base import get_provider
    from .retrieve import candidates as cand
    from .retrieve import lift

    _use(model, "chat")
    suite = xd.load_suite()
    fixture = json.loads(xd.FACETS_PATH.read_text(encoding="utf-8"))
    by_query = {q["query"]: fixture.get("lifts", {}).get(q["id"], []) for q in suite["queries"]}
    real_lift, real_judge = lift.lift, cand.judge_gray_zone
    lift.lift = lambda query: by_query.get(query, [])
    cand.judge_gray_zone = lambda query, hits: {h["artifact_id"] for h in hits}
    before = _spent()
    started = time.monotonic()
    answers, failed = [], []
    try:
        with xd.pointed_at_test_dir():
            xd.build(suite)
            xd.load_facets(fixture.get("facets", {}))
            xd.load_entities(fixture.get("entities", {}))
            xd.load_sections(fixture.get("sections", {}))
            provider = get_provider(role="chat")
            for q in suite["queries"]:
                found = chats._library_passages(q["query"])
                t0 = time.monotonic()
                try:
                    a = chats._ask_model(q["query"], "", found, provider=provider)
                except Exception as exc:  # noqa: BLE001 - a failed reply is a result
                    failed.append(f"{q['id']}: {exc}"[:160])
                    continue
                answers.append(
                    {
                        "id": q["id"],
                        "offered": any(p["artifact_id"] in q["expect"] for p in found),
                        "cites_it": any(c in q["expect"] for c in a.cited),
                        "grounded": a.grounded,
                        "seconds": round(time.monotonic() - t0, 1),
                    }
                )
    finally:
        lift.lift, cand.judge_gray_zone = real_lift, real_judge
    offered = [a for a in answers if a["offered"]]
    return {
        "role": "chat",
        "model": model,
        "cost_usd": _cost_since(before),
        "seconds": round(time.monotonic() - started),
        "questions": len(suite["queries"]),
        "cited_when_offered": f"{sum(a['cites_it'] for a in offered)}/{len(offered)}",
        "grounded": sum(a["grounded"] for a in answers),
        "failed_replies": failed,
        "median_answer_seconds": (
            sorted(a["seconds"] for a in answers)[len(answers) // 2] if answers else None
        ),
        "answers": answers,
    }
