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

Everything that is NOT SQLite-specific (email, SMS, serving the app, the
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
)

# Where the database file lives (override with the GLEENERGY_DB env var if you like)
DB_PATH = os.environ.get("GLEENERGY_DB", os.path.join(os.path.dirname(__file__), "data", "gleenergy.db"))

app = FastAPI(title="Gleenergy Renewables Company System API")


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
    return conn


# --- accessors the shared auth layer needs (see install_shared) ---------

def _kv_get_raw(key):
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


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
            "INSERT INTO kv(key, value, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
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
