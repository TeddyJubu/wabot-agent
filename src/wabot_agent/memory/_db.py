"""Thread-local SQLite connection management for the memory package."""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_thread_local = threading.local()


def get_thread_connection(path: Path, lock: threading.RLock) -> sqlite3.Connection:
    """Return the per-thread connection for *path*, opening one if needed."""
    conn = getattr(_thread_local, "conn", None)
    conn_path = getattr(_thread_local, "path", None)
    if conn is None or conn_path != path:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma synchronous=NORMAL")
        conn.execute("pragma busy_timeout=5000")
        _thread_local.conn = conn
        _thread_local.path = path
    return conn


@contextmanager
def open_connection(
    path: Path, lock: threading.RLock
) -> Iterator[sqlite3.Connection]:
    """Yield a committed (or rolled-back) thread-local connection."""
    with lock:
        conn = get_thread_connection(path, lock)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
