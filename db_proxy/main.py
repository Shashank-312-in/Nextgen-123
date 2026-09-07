"""
db_proxy — thin authenticated HTTP-to-MySQL session relay.

Runs on the campus machine, next to the real MySQL server. Exposes a small
HTTP API so a backend that cannot reach MySQL directly (e.g. Render, which
only has outbound HTTPS) can still run MySQL transactions against campus
MySQL, tunneled through a Cloudflare Quick Tunnel (HTTP-only, free, no
domain needed).

This service has NO knowledge of students/attendance/anything — it only
knows "open a transaction, run a statement, commit or rollback". All
business logic stays in the main app's database.py / routes_*.py.

Run:
    uvicorn main:app --host 0.0.0.0 --port 8010
Then tunnel it:
    python run_cloudflare.py --port 8010
"""

from __future__ import annotations

import hmac
import os
import threading
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

load_dotenv()

try:
    import mysql.connector
    from mysql.connector import Error as DatabaseError
    MYSQL_DRIVER = "mysql.connector"
except ImportError:
    import pymysql
    from pymysql import Error as DatabaseError
    MYSQL_DRIVER = "pymysql"

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 3306))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "student_management")

# — ProxyAuth: shared-secret key, mandatory, no bypass
# ASSUMPTION: PROXY_SHARED_KEY is set in db_proxy/.env before this ever runs
# in a reachable place. There is intentionally no "skip auth" flag anywhere
# in this file — do not add one, even for local testing. A public tunnel
# URL with no auth check is an open MySQL gateway into the campus network.
PROXY_SHARED_KEY = os.environ.get("PROXY_SHARED_KEY", "")
if not PROXY_SHARED_KEY:
    raise RuntimeError(
        "PROXY_SHARED_KEY is not set. Refusing to start — this proxy must "
        "never run without a shared secret. Set it in db_proxy/.env"
    )

SESSION_IDLE_TIMEOUT_SECONDS = 30

app = FastAPI(title="db_proxy", version="1")


# — SessionStore: in-memory session_id -> live MySQL connection
# State ownership: this dict is the ONLY place session connections live.
# Nothing else in this file writes to it directly.
class _Session:
    __slots__ = ("conn", "last_used")

    def __init__(self, conn):
        self.conn = conn
        self.last_used = time.monotonic()


_sessions: dict[str, _Session] = {}
_sessions_lock = threading.Lock()


def _new_raw_connection():
    if MYSQL_DRIVER == "mysql.connector":
        return mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            autocommit=False,
            connection_timeout=10,
        )
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        autocommit=False,
        charset="utf8mb4",
        connect_timeout=10,
    )


def _cursor(conn):
    if MYSQL_DRIVER == "mysql.connector":
        return conn.cursor(dictionary=True, buffered=True)
    return conn.cursor(pymysql.cursors.DictCursor)


# — IdleSweeper: background thread, closes abandoned sessions
# Failure recovery: if the Render-side client crashes mid-transaction and
# never calls commit/rollback, this sweep rolls the open MySQL transaction
# back and frees the connection. Without this, a crashed client leaks an
# open transaction (and a MySQL connection slot) forever.
def _sweep_idle_sessions():
    while True:
        time.sleep(5)
        now = time.monotonic()
        expired: list[str] = []
        with _sessions_lock:
            for sid, sess in _sessions.items():
                if now - sess.last_used > SESSION_IDLE_TIMEOUT_SECONDS:
                    expired.append(sid)
            for sid in expired:
                sess = _sessions.pop(sid)
                try:
                    sess.conn.rollback()
                except Exception:
                    pass
                try:
                    sess.conn.close()
                except Exception:
                    pass
        for sid in expired:
            print(f"[db_proxy] session {sid} expired (idle > {SESSION_IDLE_TIMEOUT_SECONDS}s), rolled back")


threading.Thread(target=_sweep_idle_sessions, daemon=True).start()


def _check_auth(x_proxy_key: str | None):
    if not x_proxy_key or not hmac.compare_digest(x_proxy_key, PROXY_SHARED_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing X-Proxy-Key")


def _get_session(session_id: str) -> _Session:
    with _sessions_lock:
        sess = _sessions.get(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"unknown or expired session {session_id}")
        sess.last_used = time.monotonic()
        return sess


class ExecuteRequest(BaseModel):
    sql: str
    params: list[Any] | None = None


@app.post("/v1/session/begin")
def session_begin(x_proxy_key: str | None = Header(default=None)):
    _check_auth(x_proxy_key)
    conn = _new_raw_connection()
    session_id = str(uuid.uuid4())
    with _sessions_lock:
        _sessions[session_id] = _Session(conn)
    print(f"[db_proxy] session {session_id} begin")
    return {"session_id": session_id}


@app.post("/v1/session/{session_id}/execute")
def session_execute(session_id: str, body: ExecuteRequest, x_proxy_key: str | None = Header(default=None)):
    _check_auth(x_proxy_key)
    sess = _get_session(session_id)
    sql = body.sql
    if MYSQL_DRIVER and isinstance(sql, str):
        sql = sql.replace("?", "%s")
    verb = sql.strip().split(None, 1)[0].upper() if sql.strip() else "?"
    try:
        cur = _cursor(sess.conn)
        if body.params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, body.params)
        rows: list[dict] = []
        if cur.description:
            rows = cur.fetchall()
        result = {
            "rows": rows,
            "lastrowid": cur.lastrowid,
            "rowcount": cur.rowcount,
        }
        cur.close()
        print(f"[db_proxy] session {session_id} execute {verb}")
        return result
    except DatabaseError as e:
        # Error contract: SQL/driver errors surface as HTTP 400 with a
        # type name the client's HTTPCursorWrapper maps back onto the
        # same DatabaseError/OperationalError types routes already expect.
        print(f"[db_proxy] session {session_id} execute {verb} FAILED: {type(e).__name__}")
        raise HTTPException(status_code=400, detail={"error_type": type(e).__name__, "message": str(e)})


@app.post("/v1/session/{session_id}/commit")
def session_commit(session_id: str, x_proxy_key: str | None = Header(default=None)):
    _check_auth(x_proxy_key)
    with _sessions_lock:
        sess = _sessions.pop(session_id, None)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"unknown or expired session {session_id}")
    try:
        sess.conn.commit()
    finally:
        try:
            sess.conn.close()
        except Exception:
            pass
    print(f"[db_proxy] session {session_id} commit")
    return {"ok": True}


@app.post("/v1/session/{session_id}/rollback")
def session_rollback(session_id: str, x_proxy_key: str | None = Header(default=None)):
    _check_auth(x_proxy_key)
    with _sessions_lock:
        sess = _sessions.pop(session_id, None)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"unknown or expired session {session_id}")
    try:
        sess.conn.rollback()
    finally:
        try:
            sess.conn.close()
        except Exception:
            pass
    print(f"[db_proxy] session {session_id} rollback")
    return {"ok": True}


@app.get("/v1/health")
def health():
    return {"status": "ok", "driver": MYSQL_DRIVER, "database": MYSQL_DATABASE}
