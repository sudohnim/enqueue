"""The SQLite driver the engine runs on: SQLCipher's build (`sqlcipher3`).

It reads a plain SQLite file exactly as the standard library's `sqlite3` does, and an
encrypted one once it is given the key, so one driver serves a library before and after
it is encrypted (db.connect decides which). Everything that opens the library imports
this module, never the standard library's, so its errors are the ones caught: a
`sqlite3.OperationalError` from the standard library is a different class.
"""

from __future__ import annotations

from sqlcipher3.dbapi2 import (  # noqa: F401 - re-exported as this module's API
    Connection,
    DatabaseError,
    Error,
    IntegrityError,
    OperationalError,
    Row,
    connect,
    sqlite_version,
)
