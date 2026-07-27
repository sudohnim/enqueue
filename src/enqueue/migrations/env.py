"""Alembic environment.

The database URL comes from `enqueue.config`, never from alembic.ini. That way a
migration runs identically from the `alembic` CLI, from the engine at startup, and
from a test that has pointed DATA_DIR at a temporary directory.

Autogenerate is deliberately unavailable. The runtime talks to SQLite through
`sqlite3` and there are no ORM models to diff against, so every revision is written
by hand. SQLAlchemy is here to drive Alembic and for nothing else.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from enqueue import config

target_metadata = None


def _url() -> str:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{config.DB_PATH}"


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,  # SQLite cannot ALTER in place
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
