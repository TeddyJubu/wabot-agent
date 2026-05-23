"""Confirm that `get_thread_connection` enables SQLite FK enforcement.

SQLite ships with `pragma foreign_keys` defaulted to OFF, so `on delete
cascade` clauses on table definitions are silently no-ops unless the
connection explicitly opts in. The memory package depends on cascade
behaviour for the dynamic-subagent join tables (e.g. `subagent_tools`),
so this guarantee must hold for every connection the helper hands out.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from wabot_agent.memory._db import get_thread_connection


@pytest.fixture(autouse=True)
def _reset_thread_local():
    """Clear the module-level thread_local before each test so each test
    gets a fresh connection (the helper caches per-thread by path)."""
    from wabot_agent.memory import _db as db_module

    # Best-effort cleanup of any cached connection so this fixture is safe
    # even when other tests in the same worker have populated the thread-local.
    if hasattr(db_module._thread_local, "conn"):
        try:
            db_module._thread_local.conn.close()
        except Exception:  # pragma: no cover — defensive
            pass
        del db_module._thread_local.conn
    if hasattr(db_module._thread_local, "path"):
        del db_module._thread_local.path
    yield
    if hasattr(db_module._thread_local, "conn"):
        try:
            db_module._thread_local.conn.close()
        except Exception:  # pragma: no cover — defensive
            pass
        del db_module._thread_local.conn
    if hasattr(db_module._thread_local, "path"):
        del db_module._thread_local.path


def test_get_thread_connection_enables_foreign_keys(tmp_path: Path) -> None:
    conn = get_thread_connection(tmp_path / "fk.db", threading.RLock())
    fk_state = conn.execute("pragma foreign_keys").fetchone()[0]
    assert fk_state == 1, "PRAGMA foreign_keys should be ON on every new connection"


def test_on_delete_cascade_actually_fires(tmp_path: Path) -> None:
    """Round-trip proof: a CASCADE FK silently no-ops without the pragma;
    with it on, the child row vanishes when the parent is deleted."""
    conn = get_thread_connection(tmp_path / "cascade.db", threading.RLock())
    conn.executescript(
        """
        create table parent (
            id integer primary key autoincrement,
            name text not null
        );
        create table child (
            id integer primary key autoincrement,
            parent_id integer not null references parent(id) on delete cascade,
            payload text
        );
        """
    )
    conn.execute("insert into parent(name) values('p1')")
    parent_id = conn.execute("select id from parent where name='p1'").fetchone()[0]
    conn.execute(
        "insert into child(parent_id, payload) values(?, ?)", (parent_id, "c1")
    )
    conn.commit()

    assert conn.execute("select count(*) from child").fetchone()[0] == 1

    conn.execute("delete from parent where id=?", (parent_id,))
    conn.commit()

    # Without the pragma this would still be 1 — the cascade would be ignored.
    assert (
        conn.execute("select count(*) from child").fetchone()[0] == 0
    ), "CASCADE FK did not fire — `PRAGMA foreign_keys=ON` is missing"


def test_foreign_key_violation_raises(tmp_path: Path) -> None:
    """Inserting a child row that references a non-existent parent must
    raise IntegrityError, which only happens with FK enforcement on."""
    conn = get_thread_connection(tmp_path / "violation.db", threading.RLock())
    conn.executescript(
        """
        create table parent (id integer primary key);
        create table child (
            id integer primary key,
            parent_id integer not null references parent(id)
        );
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("insert into child(id, parent_id) values(1, 999)")
        conn.commit()
