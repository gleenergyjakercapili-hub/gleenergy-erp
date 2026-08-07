"""
Gleenergy Renewables Company System — Python backend (SQLite)
============================================================

This is a tiny web server that does two things:

  1. Serves your HTML app at  http://localhost:8000
  2. Stores all of the app's data in a real database file (gleenergy.db),
     instead of the browser's temporary memory.

It works because your app saves everything through two helpers
(saveKey / loadKey), which call a "window.storage" object with four
methods: get, set, delete, list. This server implements those same four
methods over HTTP, so NOTHING in the app itself has to change.

Everything that is NOT SQLite-specific (email, serving the app, the
API-key protection) lives in _gleenergy_common.py and is shared with the
PostgreSQL backend so there is only one copy to maintain.

-----------------------------------------------------------------------
HOW TO RUN (first time)
-----------------------------------------------------------------------
  1. Install Python 3.10+  ->  https://www.python.org/downloads/
  2. Open a terminal in this folder and run:
         pip install -r requirements.txt
  3. Start the server:
         uvicorn app:app --host 0.0.0.0 --port 8000
  4. Open your browser at:
         http://localhost:8000
  5. Use the app normally. Data is saved to gleenergy.db in this folder.

Other devices on the same Wi-Fi can use it too: find this computer's IP
address (e.g. 192.168.1.10) and open  http://192.168.1.10:8000

To BACK UP your data, just copy the file  gleenergy.db  somewhere safe.

BEFORE exposing this to the internet (e.g. through ngrok), set a secret:
    Windows:   set GLEENERGY_API_KEY=some-long-random-secret
See _gleenergy_common.py for what that turns on.
-----------------------------------------------------------------------
"""

import os
import sqlite3
import contextlib
from fastapi import FastAPI

from _gleenergy_common import (
    install_shared,
    KeyBody,
    SetBody,
    ListBody,
    ChangesBody,
    parse_marker,
    feed_exclude_sql,
    changes_reply,
    FEED_MAX_KEYS,
    FEED_LOOKBACK,
    PRESENCE_KEY,
)

# Where the database file lives (override with the GLEENERGY_DB env var if you like)
DB_PATH = os.environ.get("GLEENERGY_DB", os.path.join(os.path.dirname(__file__), "data", "gleenergy.db"))

# docs_url/redoc_url/openapi_url are disabled: the auto-generated schema pages
# sat OUTSIDE the /api/* session guard and listed every endpoint name to
# anyone. No data was exposed (all routes need a session), but the route
# catalog is nobody's business.
app = FastAPI(title="Gleenergy Renewables Company System API", docs_url=None, redoc_url=None, openapi_url=None)


def _conn():
    """Open the database and make sure the storage + session tables exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kv ("
        "  key        TEXT PRIMARY KEY,"
        "  value      TEXT,"
        "  updated_at TEXT DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        "  token_hash TEXT PRIMARY KEY,"
        "  emp_id     TEXT,"
        "  email      TEXT,"
        "  created_at REAL,"
        "  expires_at REAL"
        ")"
    )
    # Composite (updated_at, key): the change feed's ORDER BY updated_at, key
    # becomes a pure index range scan instead of a sort.
    conn.execute("CREATE INDEX IF NOT EXISTS kv_updated_at ON kv(updated_at, key)")
    return conn


# --- accessors the shared auth layer needs (see install_shared) ---------

def _kv_get_raw(key):
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _kv_set_raw(key, val):
    """Server-side write (same upsert as /api/storage/set) — used by the
    inbound-leads webhook to create client records without a browser."""
    with contextlib.closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP "
            "WHERE kv.value IS NOT excluded.value",
            (key, val),
        )
        conn.commit()


def _sess_get(token_hash):
    with contextlib.closing(_conn()) as conn:
        row = conn.execute(
            "SELECT emp_id, email, expires_at FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    return {"emp_id": row[0], "email": row[1], "expires_at": row[2]}


def _sess_put(token_hash, emp_id, email, created_at, expires_at):
    with contextlib.closing(_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions(token_hash, emp_id, email, created_at, expires_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (token_hash, emp_id, email, created_at, expires_at),
        )
        conn.commit()


def _sess_touch(token_hash, expires_at):
    with contextlib.closing(_conn()) as conn:
        conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (expires_at, token_hash))
        conn.commit()


def _sess_del(token_hash):
    with contextlib.closing(_conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        conn.commit()


def _sess_prune(now):
    with contextlib.closing(_conn()) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.commit()


AUTH_DB = {
    "kv_get": _kv_get_raw,
    "kv_set": _kv_set_raw,
    "sess_get": _sess_get,
    "sess_put": _sess_put,
    "sess_touch": _sess_touch,
    "sess_del": _sess_del,
    "sess_prune": _sess_prune,
}


# ----------------------------------------------------------------------
# The four storage methods the app expects (get / set / delete / list).
# Each saves or reads one "key" (for example "p2:clients") whose value is
# a JSON string the app produced.
#
# These are plain `def` (not `async def`) on purpose: sqlite3 blocks, so
# FastAPI runs them in a worker thread and one slow query no longer freezes
# every other user's request.
# ----------------------------------------------------------------------

@app.post("/api/storage/get")
def storage_get(body: KeyBody):
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (body.key,)).fetchone()
    if row is None:
        return None                        # app reads this as "nothing saved yet"
    return {"key": body.key, "value": row[0]}


@app.post("/api/storage/set")
def storage_set(body: SetBody):
    with contextlib.closing(_conn()) as conn:
        conn.execute(
            # The WHERE keeps no-op re-saves from bumping updated_at — without it,
            # half the change-feed events would carry no actual change.
            # IS NOT (null-safe), not <>.
            "INSERT INTO kv(key, value, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP "
            "WHERE kv.value IS NOT excluded.value",
            (body.key, body.value),
        )
        conn.commit()
    return {"key": body.key, "ok": True}


@app.post("/api/storage/delete")
def storage_delete(body: KeyBody):
    with contextlib.closing(_conn()) as conn:
        conn.execute("DELETE FROM kv WHERE key = ?", (body.key,))
        conn.commit()
    return {"key": body.key, "deleted": True}


@app.post("/api/storage/list")
def storage_list(body: ListBody):
    prefix = body.prefix or ""
    with contextlib.closing(_conn()) as conn:
        rows = conn.execute("SELECT key FROM kv WHERE key LIKE ?", (prefix + "%",)).fetchall()
    return {"keys": [r[0] for r in rows]}


@app.post("/api/storage/changes")
def storage_changes(body: ChangesBody):
    """Which keys changed since the caller's marker — keys only, never values,
    plus the current presence map (one PK lookup).

    The marker is server-issued and OPAQUE: clients echo back whatever the last
    reply gave them. It is always a timestamp taken off a real row, never the
    clock, and the comparison is >= : SQLite's CURRENT_TIMESTAMP has one-second
    resolution and this database routinely writes many keys in the same second,
    so > would silently drop every same-second sibling of the marker row.
    Clients de-dup on (key, at)."""
    since = parse_marker(body.since)
    where, params = ["key LIKE ?"], [(body.prefix or "") + "%"]
    if since is not None:
        # Floor to SQLite's stored format. Flooring (never rounding up) is what
        # makes a microsecond marker minted by the Postgres backend safe here:
        # worst case we replay a second, we never skip one.
        where.append("updated_at >= ?")
        params.append((since - FEED_LOOKBACK).strftime("%Y-%m-%d %H:%M:%S"))
    frag, xparams = feed_exclude_sql("?")
    sql = ("SELECT key, updated_at FROM kv WHERE " + " AND ".join(where) + frag
           + " ORDER BY updated_at, key LIMIT ?")
    with contextlib.closing(_conn()) as conn:
        rows = conn.execute(sql, params + xparams + [FEED_MAX_KEYS + 1]).fetchall()
        prow = conn.execute("SELECT value FROM kv WHERE key = ?", (PRESENCE_KEY,)).fetchone()
    return changes_reply(rows, body.since, prow[0] if prow else "")


@app.get("/api/export")
def export_all():
    """Download every key/value as one JSON object (handy for backups/migration).

    Protected by the API key when GLEENERGY_API_KEY is set — this dumps the
    ENTIRE database, so don't expose it without a key.
    """
    with contextlib.closing(_conn()) as conn:
        rows = conn.execute("SELECT key, value FROM kv").fetchall()
    return {k: v for k, v in rows}


# Attach the shared routes LAST so /api/export is matched before the
# catch-all static-file route in install_shared().
install_shared(app, auth_db=AUTH_DB)


if __name__ == "__main__":
    # Lets you also start it with:  python app.py
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
