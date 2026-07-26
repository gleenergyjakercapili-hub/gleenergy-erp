"""
Gleenergy backend — PostgreSQL version (for production / multiple users)
=======================================================================

Same four storage methods as app.py, but data is stored in PostgreSQL
instead of a local SQLite file. Use this once more than a couple of people
use the system at the same time, or when you deploy to a server.

Everything that is NOT PostgreSQL-specific (email, SMS, serving the app,
the API-key protection) lives in _gleenergy_common.py and is shared with
the SQLite backend, so there is only one copy to maintain.

SETUP
-----
  1. Install PostgreSQL and create a database, e.g. "gleenergy".
  2. pip install -r requirements.txt   (includes "psycopg[binary,pool]" — driver + connection pool)
  3. Set the connection string in your terminal before running:
         Windows:  set DATABASE_URL=postgresql://user:password@localhost:5432/gleenergy
         Mac/Linux: export DATABASE_URL=postgresql://user:password@localhost:5432/gleenergy
  4. Run:
         uvicorn app_postgres:app --host 0.0.0.0 --port 8000
  5. Open http://localhost:8000

BEFORE exposing this to the internet, also set GLEENERGY_API_KEY
(see _gleenergy_common.py). The table is created automatically on first run.
"""

import os
import threading
import psycopg
from psycopg_pool import ConnectionPool
from fastapi import FastAPI

from _gleenergy_common import (
    install_shared,
    KeyBody,
    SetBody,
    ListBody,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gleenergy")

app = FastAPI(title="Gleenergy API (PostgreSQL)")


# One small shared pool instead of a fresh connection per request. Render's
# smaller Postgres plans allow only a handful of connections, and the app's
# initial load fires ~60 storage reads in a burst — per-request connects
# exhausted the server and every request 500'd until the backends drained.
# The pool caps us at 5 connections total and reuses them.
_POOL = None
_POOL_LOCK = threading.Lock()


def _ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            "  key        TEXT PRIMARY KEY,"
            "  value      TEXT,"
            "  updated_at TIMESTAMPTZ DEFAULT now()"
            ")"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  token_hash TEXT PRIMARY KEY,"
            "  emp_id     TEXT,"
            "  email      TEXT,"
            "  created_at DOUBLE PRECISION,"
            "  expires_at DOUBLE PRECISION"
            ")"
        )
    conn.commit()


def _pool():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                kw = {}
                if hasattr(ConnectionPool, "check_connection"):
                    kw["check"] = ConnectionPool.check_connection   # ping on checkout (pool >= 3.2)
                pool = ConnectionPool(
                    DATABASE_URL, min_size=1, max_size=5, max_idle=300,
                    timeout=15, open=True, kwargs={"connect_timeout": 10}, **kw,
                )
                with pool.connection() as conn:
                    _ensure_tables(conn)                             # DDL once per process
                _POOL = pool
    return _POOL


# --- accessors the shared auth layer needs (see install_shared) ---------

def _kv_get_raw(key):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM kv WHERE key = %s", (key,))
        row = cur.fetchone()
    return row[0] if row else None


def _sess_get(token_hash):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT emp_id, email, expires_at FROM sessions WHERE token_hash = %s",
            (token_hash,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {"emp_id": row[0], "email": row[1], "expires_at": row[2]}


def _sess_put(token_hash, emp_id, email, created_at, expires_at):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions(token_hash, emp_id, email, created_at, expires_at) "
            "VALUES(%s, %s, %s, %s, %s) "
            "ON CONFLICT (token_hash) DO UPDATE SET expires_at = EXCLUDED.expires_at",
            (token_hash, emp_id, email, created_at, expires_at),
        )
        conn.commit()


def _sess_touch(token_hash, expires_at):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE sessions SET expires_at = %s WHERE token_hash = %s", (expires_at, token_hash))
        conn.commit()


def _sess_del(token_hash):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (token_hash,))
        conn.commit()


def _sess_prune(now):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE expires_at < %s", (now,))
        conn.commit()


AUTH_DB = {
    "kv_get": _kv_get_raw,
    "sess_get": _sess_get,
    "sess_put": _sess_put,
    "sess_touch": _sess_touch,
    "sess_del": _sess_del,
    "sess_prune": _sess_prune,
}


# Plain `def` (not `async def`): psycopg blocks, so FastAPI runs these in a
# worker thread and one slow query no longer freezes every other request.

@app.post("/api/storage/get")
def storage_get(body: KeyBody):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM kv WHERE key = %s", (body.key,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"key": body.key, "value": row[0]}


@app.post("/api/storage/set")
def storage_set(body: SetBody):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES(%s, %s, now()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (body.key, body.value),
        )
        conn.commit()
    return {"key": body.key, "ok": True}


@app.post("/api/storage/delete")
def storage_delete(body: KeyBody):
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM kv WHERE key = %s", (body.key,))
        conn.commit()
    return {"key": body.key, "deleted": True}


@app.post("/api/storage/list")
def storage_list(body: ListBody):
    prefix = body.prefix or ""
    with _pool().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT key FROM kv WHERE key LIKE %s", (prefix + "%",))
        rows = cur.fetchall()
    return {"keys": [r[0] for r in rows]}


# Attach the shared routes (email, SMS, health, index, static) LAST.
install_shared(app, auth_db=AUTH_DB)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
