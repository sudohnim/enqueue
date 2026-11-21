"""Opening and closing the library never freezes the engine."""

from __future__ import annotations

import threading

from enqueue import db


def test_a_finalizer_inside_close_does_not_freeze(store):
    """The garbage collector can drop one connection while another closes on the same
    thread; the second close must not wait on the lock the first one holds."""
    done = threading.Event()

    def run():
        a = db.connect()
        b = db.connect()
        with db._OPEN_CLOSE:
            del b  # the last reference: __del__ closes it here, inside the lock
            a.close()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert done.wait(5), "close deadlocked on its own lock"
    c = db.connect()
    c.close()
