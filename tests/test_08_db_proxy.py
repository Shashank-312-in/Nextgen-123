"""
Tests for db_proxy — the campus MySQL relay (db_proxy/main.py).

# — WHY this file is separate from the other test_0N files
Every other test file in this suite talks to api/app.py (the main
backend) through the shared `client` fixture in conftest.py. db_proxy
is a *different*, standalone FastAPI app with no import relationship
to api/app.py — it only knows "open a transaction, run a statement,
commit or rollback" (see db_proxy/main.py's module docstring). It has
its own auth scheme (X-Proxy-Key / PROXY_SHARED_KEY, not JWT), so it
needs its own TestClient and its own fixtures, defined locally in this
file rather than added to the shared conftest.py.

# — WHY this suite is opt-in (skips cleanly if unconfigured)
db_proxy is only in the loop at all when DB_PROXY_URL is set on the
main backend (Render deployment where campus MySQL isn't directly
reachable). Local dev typically never runs db_proxy. Importing
db_proxy/main.py without PROXY_SHARED_KEY set raises RuntimeError by
design (main.py refuses to start unauthenticated — do not weaken
that), so this file must not import it at collection time. Every test
below skips with a clear message if the proxy isn't configured/
running, instead of turning "I don't use db_proxy locally" into a
suite-wide failure.

# — PROTECT: this suite creates and drops its own scratch table
db_proxy has no knowledge of the app schema, so there is no
TEST_RUN_TAG row-tagging story here (contrast conftest.py's PROTECT
note for the main suite). Instead, every test that touches data
creates a dedicated `_dbproxy_test_<runtag>` table via CREATE TABLE
and drops it in a finally block. Never point these tests at a real
app table (students, users, etc.) — db_proxy executes whatever SQL
it's given with no schema awareness, so a typo here is a live DELETE/
DROP against whatever database PROXY points at.
"""
from __future__ import annotations

import os
import uuid

import pytest
import httpx

# — db_proxy listens on its own port (default 8010), separate process
# from the main api/app.py backend. It is NOT mounted inside api/app.py,
# so we cannot import its `app` object the way conftest.py imports
# api.app — the two only ever talk over real HTTP, so tests do too.
DB_PROXY_BASE_URL = os.environ.get("TEST_DB_PROXY_URL", "http://localhost:8010")
PROXY_SHARED_KEY = os.environ.get("PROXY_SHARED_KEY", "")

RUN_TAG = "zzqa" + uuid.uuid4().hex[:8]
SCRATCH_TABLE = f"_dbproxy_test_{RUN_TAG}"


def _proxy_reachable() -> bool:
    try:
        r = httpx.get(f"{DB_PROXY_BASE_URL}/v1/health", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def proxy_available():
    """— Skip the whole file with one clear message instead of every
    test timing out individually, mirroring conftest.py's db_available
    fixture for the main suite."""
    if not PROXY_SHARED_KEY:
        pytest.skip(
            "PROXY_SHARED_KEY not set — db_proxy tests are opt-in. "
            "Set PROXY_SHARED_KEY (and optionally TEST_DB_PROXY_URL, "
            "default http://localhost:8010) in .env.test to run this file."
        )
    if not _proxy_reachable():
        pytest.skip(
            f"db_proxy not reachable at {DB_PROXY_BASE_URL}/v1/health — "
            f"start it first: uvicorn main:app --host 0.0.0.0 --port 8010 "
            f"(run from the db_proxy/ directory)."
        )
    return True


@pytest.fixture(scope="module")
def proxy_client(proxy_available):
    with httpx.Client(base_url=DB_PROXY_BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"X-Proxy-Key": PROXY_SHARED_KEY}


@pytest.fixture
def bad_auth_headers():
    return {"X-Proxy-Key": "definitely-not-the-real-key"}


def _begin(proxy_client, headers):
    r = proxy_client.post("/v1/session/begin", headers=headers)
    assert r.status_code == 200, f"session/begin failed: {r.status_code} {r.text}"
    return r.json()["session_id"]


def _execute(proxy_client, headers, session_id, sql, params=None):
    body = {"sql": sql}
    if params is not None:
        body["params"] = params
    return proxy_client.post(f"/v1/session/{session_id}/execute", json=body, headers=headers)


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------

class TestHealth:
    def test_health_no_auth_required(self, proxy_client):
        # — per main.py's docstring: /v1/health is intentionally
        # unauthenticated so uptime checks don't need the shared key.
        r = proxy_client.get("/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["driver"] in ("mysql.connector", "pymysql")


# ---------------------------------------------------------------------
# Auth — X-Proxy-Key required on every session/execute/commit/rollback route
# ---------------------------------------------------------------------

class TestProxyAuth:
    def test_session_begin_missing_key_rejected(self, proxy_client):
        r = proxy_client.post("/v1/session/begin")
        assert r.status_code == 401

    def test_session_begin_wrong_key_rejected(self, proxy_client, bad_auth_headers):
        r = proxy_client.post("/v1/session/begin", headers=bad_auth_headers)
        assert r.status_code == 401

    def test_execute_missing_key_rejected(self, proxy_client, auth_headers):
        # — a real session must exist first so a 401 here is provably
        # about auth, not a 404 from a bogus session_id.
        session_id = _begin(proxy_client, auth_headers)
        try:
            r = proxy_client.post(
                f"/v1/session/{session_id}/execute",
                json={"sql": "SELECT 1"},
            )
            assert r.status_code == 401
        finally:
            proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

    def test_commit_missing_key_rejected(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        try:
            r = proxy_client.post(f"/v1/session/{session_id}/commit")
            assert r.status_code == 401
        finally:
            proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

    def test_rollback_missing_key_rejected(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        r = proxy_client.post(f"/v1/session/{session_id}/rollback")
        assert r.status_code == 401
        # — clean up for real since the unauthenticated rollback above
        # was correctly rejected and never actually closed the session.
        proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)


# ---------------------------------------------------------------------
# Session lifecycle — begin / execute / commit / rollback
# ---------------------------------------------------------------------

class TestSessionLifecycle:
    def test_begin_returns_session_id(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        assert session_id
        proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

    def test_unknown_session_id_404s_on_execute(self, proxy_client, auth_headers):
        r = _execute(proxy_client, auth_headers, "not-a-real-session-id", "SELECT 1")
        assert r.status_code == 404

    def test_unknown_session_id_404s_on_commit(self, proxy_client, auth_headers):
        r = proxy_client.post("/v1/session/not-a-real-session-id/commit", headers=auth_headers)
        assert r.status_code == 404

    def test_unknown_session_id_404s_on_rollback(self, proxy_client, auth_headers):
        r = proxy_client.post("/v1/session/not-a-real-session-id/rollback", headers=auth_headers)
        assert r.status_code == 404

    def test_commit_consumes_session_second_commit_404s(self, proxy_client, auth_headers):
        # — commit pops the session out of _sessions (see main.py); the
        # session_id must not be reusable afterward.
        session_id = _begin(proxy_client, auth_headers)
        r1 = proxy_client.post(f"/v1/session/{session_id}/commit", headers=auth_headers)
        assert r1.status_code == 200
        r2 = proxy_client.post(f"/v1/session/{session_id}/commit", headers=auth_headers)
        assert r2.status_code == 404

    def test_rollback_consumes_session_second_rollback_404s(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        r1 = proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)
        assert r1.status_code == 200
        r2 = proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)
        assert r2.status_code == 404

    def test_select_returns_rows(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        try:
            r = _execute(proxy_client, auth_headers, session_id, "SELECT 1 AS one")
            assert r.status_code == 200
            body = r.json()
            assert body["rows"] == [{"one": 1}]
            assert body["rowcount"] in (1, -1)  # driver-dependent for SELECT
        finally:
            proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

    def test_param_placeholder_question_mark_translated(self, proxy_client, auth_headers):
        # — main.py rewrites "?" -> "%s" before executing (see
        # session_execute). Confirms that translation actually happens
        # rather than asserting on it indirectly via app-level tests.
        session_id = _begin(proxy_client, auth_headers)
        try:
            r = _execute(proxy_client, auth_headers, session_id, "SELECT ? AS echoed", params=[42])
            assert r.status_code == 200
            assert r.json()["rows"] == [{"echoed": 42}]
        finally:
            proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

    def test_bad_sql_returns_400_with_error_type(self, proxy_client, auth_headers):
        # — error contract per main.py: DatabaseError -> HTTP 400 with
        # {"error_type": ..., "message": ...}, not a 500.
        session_id = _begin(proxy_client, auth_headers)
        try:
            r = _execute(proxy_client, auth_headers, session_id, "SELECT * FROM this_table_does_not_exist_zzqa")
            assert r.status_code == 400
            detail = r.json()["detail"]
            assert "error_type" in detail
            assert "message" in detail
        finally:
            proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

    def test_session_failed_execute_can_still_rollback(self, proxy_client, auth_headers):
        # — a failed statement must not orphan the session; rollback
        # should still succeed afterward (connection stays usable).
        session_id = _begin(proxy_client, auth_headers)
        _execute(proxy_client, auth_headers, session_id, "SELECT * FROM this_table_does_not_exist_zzqa")
        r = proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)
        assert r.status_code == 200


# ---------------------------------------------------------------------
# Transaction semantics — commit persists, rollback discards
# ---------------------------------------------------------------------

class TestTransactionSemantics:
    """Uses a dedicated scratch table (SCRATCH_TABLE), created and
    dropped per test via db_proxy itself so this file has zero
    dependency on the app schema. See module PROTECT note."""

    def _create_scratch_table(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        r = _execute(
            proxy_client, auth_headers, session_id,
            f"CREATE TABLE {SCRATCH_TABLE} (id INT PRIMARY KEY AUTO_INCREMENT, val VARCHAR(64))",
        )
        assert r.status_code == 200, f"scratch table setup failed: {r.text}"
        commit = proxy_client.post(f"/v1/session/{session_id}/commit", headers=auth_headers)
        assert commit.status_code == 200

    def _drop_scratch_table(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        _execute(proxy_client, auth_headers, session_id, f"DROP TABLE IF EXISTS {SCRATCH_TABLE}")
        proxy_client.post(f"/v1/session/{session_id}/commit", headers=auth_headers)

    @pytest.fixture(autouse=True)
    def _scratch_table(self, proxy_client, auth_headers):
        self._create_scratch_table(proxy_client, auth_headers)
        yield
        self._drop_scratch_table(proxy_client, auth_headers)

    def test_commit_persists_insert(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        _execute(proxy_client, auth_headers, session_id,
                 f"INSERT INTO {SCRATCH_TABLE} (val) VALUES (?)", params=["committed-row"])
        proxy_client.post(f"/v1/session/{session_id}/commit", headers=auth_headers)

        verify_session = _begin(proxy_client, auth_headers)
        r = _execute(proxy_client, auth_headers, verify_session, f"SELECT val FROM {SCRATCH_TABLE}")
        proxy_client.post(f"/v1/session/{verify_session}/rollback", headers=auth_headers)

        assert {"val": "committed-row"} in r.json()["rows"]

    def test_rollback_discards_insert(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        _execute(proxy_client, auth_headers, session_id,
                 f"INSERT INTO {SCRATCH_TABLE} (val) VALUES (?)", params=["rolled-back-row"])
        proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)

        verify_session = _begin(proxy_client, auth_headers)
        r = _execute(proxy_client, auth_headers, verify_session, f"SELECT val FROM {SCRATCH_TABLE}")
        proxy_client.post(f"/v1/session/{verify_session}/rollback", headers=auth_headers)

        assert {"val": "rolled-back-row"} not in r.json()["rows"]

    def test_lastrowid_and_rowcount_on_insert(self, proxy_client, auth_headers):
        session_id = _begin(proxy_client, auth_headers)
        r = _execute(proxy_client, auth_headers, session_id,
                      f"INSERT INTO {SCRATCH_TABLE} (val) VALUES (?)", params=["row-for-id-check"])
        body = r.json()
        assert body["lastrowid"] > 0
        assert body["rowcount"] == 1
        proxy_client.post(f"/v1/session/{session_id}/rollback", headers=auth_headers)


# ---------------------------------------------------------------------
# Idle sweeper — abandoned sessions get rolled back automatically
# ---------------------------------------------------------------------

class TestIdleSweep:
    @pytest.mark.slow
    def test_idle_session_expires_and_is_unusable(self, proxy_client, auth_headers):
        # — main.py's SESSION_IDLE_TIMEOUT_SECONDS is 30s and the
        # sweeper polls every 5s, so this test takes up to ~35s. Marked
        # slow; run explicitly with `-m slow` rather than by default,
        # matching how the rest of this suite treats expensive tests.
        import time
        session_id = _begin(proxy_client, auth_headers)
        time.sleep(36)
        r = _execute(proxy_client, auth_headers, session_id, "SELECT 1")
        assert r.status_code == 404
