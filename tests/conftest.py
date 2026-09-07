"""
Shared pytest fixtures for the NextGen SMS API test suite.

# — WHY this file exists
Every test file needs: (1) a TestClient wired to the real api/app.py,
(2) logged-in tokens for each role so RBAC tests don't each hand-roll
login calls, (3) a guaranteed-safe way to create/destroy throwaway test
data so this suite never pollutes real student/faculty records.

# — PROTECT: TEST_RUN_TAG isolation
Every row this suite creates is tagged with TEST_RUN_TAG in a
recognizable field (roll_no prefix, username prefix, subject code
prefix). The teardown fixture deletes ONLY rows matching that tag.
Do not loosen this to a broad DELETE — this suite runs against real
data, not a disposable test DB.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import pytest

# — Make the real project importable (api/app.py, database.py, etc.)
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.environ.get("SMS_PROJECT_ROOT") or DEFAULT_ROOT
if not os.path.exists(os.path.join(PROJECT_ROOT, "api", "app.py")):
    raise RuntimeError(
        f"SMS_PROJECT_ROOT ({PROJECT_ROOT}) does not contain api/app.py. "
        "Point SMS_PROJECT_ROOT at the folder containing api/app.py before running pytest.\n"
        "Example: SMS_PROJECT_ROOT=/path/to/NextGen_SMS_live_cleaned pytest"
    )
sys.path.insert(0, PROJECT_ROOT)

# — Auto-load .env.test so TEST_HOD_USERNAME etc. are available without a
# manual shell export step. Checked in two places since either is a
# reasonable place to have saved it: next to conftest.py (tests/.env.test)
# and at the project root (SMS_PROJECT_ROOT/.env.test). First one found
# wins. Only sets vars not already in the environment, so a real shell
# export still takes priority if present.
_ENV_TEST_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), ".env.test"),
    os.path.join(PROJECT_ROOT, ".env.test"),
]
for _env_path in _ENV_TEST_CANDIDATES:
    if os.path.exists(_env_path):
        try:
            from dotenv import load_dotenv
            load_dotenv(_env_path, override=False)
        except ModuleNotFoundError:
            # Minimal fallback parser if python-dotenv isn't installed —
            # avoids adding a hard new dependency just for this.
            with open(_env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value
        break

# — Unique tag per test run so parallel/repeat runs never collide and
# teardown never touches real data (see module docstring PROTECT note).
TEST_RUN_TAG = "zzqa" + uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def run_tag() -> str:
    return TEST_RUN_TAG


# — reset_rate_limits
# WHY this must hit the real table: rate_limit.py and firewall.py are both
# MySQL-backed (rate_limit_buckets), not in-memory dicts — there is no
# _attempts or auth_requests_log/general_requests_log to clear anymore. The
# old version of this fixture referenced those stale names inside a bare
# `except Exception: pass`, so it silently did nothing every single run
# while looking like real cleanup.
#
# Two different key shapes need two different clearing strategies:
#   1. login-limiter keys ("{ip}:{username}" from api/rate_limit.py) are
#      tagged with TEST_RUN_TAG in the username portion (see conftest's own
#      account-creation helpers), so PROTECT still applies: never a broad,
#      untagged DELETE against those.
#   2. api/firewall.py's middleware keys ("firewall:auth:{ip}" /
#      "firewall:general:{ip}") are keyed purely by client IP and can never
#      contain TEST_RUN_TAG — they're not test data, they're infra. Against
#      real traffic this is correctly IP-scoped and must stay untouched by
#      any test cleanup. But TestClient's fixed synthetic IP is literally
#      the string "testclient" (starlette's default test client host) —
#      only this test suite can ever produce that exact key, and a full
#      session's worth of login fixtures across ~200 tests legitimately
#      exhausts firewall.py's 15/min auth cap on it, causing spurious 429s
#      in unrelated later tests. Clearing rows keyed to that exact literal
#      is safe and does not touch any real IP's data.
@pytest.fixture(autouse=True)
def reset_rate_limits():
    import database

    def _clear():
        try:
            with database.connect() as c:
                c.execute(
                    "DELETE FROM rate_limit_buckets WHERE bucket_key LIKE %s",
                    (f"%{TEST_RUN_TAG}%",),
                )
                c.execute(
                    "DELETE FROM rate_limit_buckets WHERE bucket_key IN "
                    "('firewall:auth:testclient', 'firewall:general:testclient')",
                )
        except Exception:
            pass

    _clear()
    yield
    _clear()


# — reset_client_cookies
# WHY this is separate from reset_rate_limits: `client` is a session-scoped
# TestClient (see below), so its cookie jar persists across the entire test
# session — not just within one file or class. api/deps.py's
# get_current_user legitimately accepts the sms_refresh httpOnly cookie as a
# fallback auth path (correct behavior for a real browser), which means any
# earlier test that logged in via client.post("/api/auth/login") — and the
# session-scoped hod_headers/faculty_headers/student_headers fixtures all do
# exactly that once per session — leaves a valid sms_refresh cookie sitting
# in the shared jar. Every subsequent "no credentials" test in the same
# session is then silently NOT actually unauthenticated. This bit real
# tests (test_01_auth.py's TestMeAndUnauthenticated, and ~18 *_requires_auth
# tests across other files) the moment tests ran in full-file/full-suite
# order instead of in isolation. Clearing cookies before every test removes
# the ordering dependency entirely rather than requiring every "requires
# auth" test to remember to clear cookies itself.
@pytest.fixture(autouse=True)
def reset_client_cookies(request):
    if "client" in request.fixturenames:
        client = request.getfixturevalue("client")
        client.cookies.clear()
    yield


@pytest.fixture(scope="session")
def db_available():
    """— Fail fast with a clear message if MySQL isn't reachable, instead
    of letting every single test time out individually."""
    import database
    try:
        with database.connect() as c:
            c.execute("SELECT 1")
    except Exception as exc:
        pytest.exit(
            f"\n\nCannot reach MySQL ({exc}).\n"
            f"Check MYSQL_HOST / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE "
            f"env vars (or your .env file) before running this suite.\n",
            returncode=2,
        )
    return True


@pytest.fixture(scope="session")
def client(db_available):
    from fastapi.testclient import TestClient
    from api.app import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------
# Role-based auth fixtures
# ---------------------------------------------------------------------
# — WHY env-var-driven credentials, not hardcoded: this suite runs
# against Boss's real MySQL with real accounts. Hardcoding a guessed
# HOD password here would either fail (wrong password) or be a
# checked-in credential (worse). Set these once in a .env.test file.

def _login(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    return resp


@pytest.fixture(scope="session")
def hod_creds():
    user = os.environ.get("TEST_HOD_USERNAME")
    pw = os.environ.get("TEST_HOD_PASSWORD")
    if not user or not pw:
        pytest.skip("TEST_HOD_USERNAME / TEST_HOD_PASSWORD not set — skipping HOD-authenticated tests")
    return user, pw


@pytest.fixture(scope="session")
def faculty_creds():
    user = os.environ.get("TEST_FACULTY_USERNAME")
    pw = os.environ.get("TEST_FACULTY_PASSWORD")
    if not user or not pw:
        pytest.skip("TEST_FACULTY_USERNAME / TEST_FACULTY_PASSWORD not set — skipping faculty-authenticated tests")
    return user, pw


@pytest.fixture(scope="session")
def student_creds():
    user = os.environ.get("TEST_STUDENT_USERNAME")
    pw = os.environ.get("TEST_STUDENT_PASSWORD")
    if not user or not pw:
        pytest.skip("TEST_STUDENT_USERNAME / TEST_STUDENT_PASSWORD not set — skipping student-authenticated tests")
    return user, pw


def _auth_headers(client, creds):
    username, password = creds
    resp = _login(client, username, password)
    assert resp.status_code == 200, (
        f"Fixture login failed for {username!r} (status {resp.status_code}): {resp.text}\n"
        f"Check TEST_*_USERNAME / TEST_*_PASSWORD point at real, active, "
        f"non-must-change-password accounts."
    )
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def hod_headers(client, hod_creds):
    return _auth_headers(client, hod_creds)


@pytest.fixture(scope="session")
def faculty_headers(client, faculty_creds):
    return _auth_headers(client, faculty_creds)


@pytest.fixture(scope="session")
def student_headers(client, student_creds):
    return _auth_headers(client, student_creds)


# ---------------------------------------------------------------------
# Test-data teardown registry
# ---------------------------------------------------------------------

@pytest.fixture(scope="session")
def cleanup_registry():
    """Collects (table, column, value) rows created during the run so
    they can be deleted afterward, tag-scoped only. See PROTECT note
    at top of file."""
    created = []
    yield created
    if not created:
        return
    import database
    with database.connect() as c:
        for table, column, value in reversed(created):
            try:
                c.execute(f"DELETE FROM {table} WHERE {column}=?", (value,))
            except Exception as exc:
                print(f"[cleanup] could not delete {table}.{column}={value}: {exc}")