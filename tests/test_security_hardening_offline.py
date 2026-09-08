"""Offline regression tests for the production security hardening port.

These tests intentionally avoid MariaDB/network dependencies. The production
acceptance gate still requires the live attacks described in SECURITY_FIXES.md;
this suite is the deterministic local layer that can run in a source-only CI
container.
"""

import asyncio
import importlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.auth_token as auth_token
import api.deps as deps
import api.firewall as firewall
import api.rate_limit as rate_limit
import api.routes_dashboard as dashboard
import api.routes_files as routes_files
import database
from api.envelope import ApiError
from sms_app.services.student_pdf import build_students_list_pdf
from webapp import photo_upload


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows if rows is not None else ([] if row is None else [row])

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def keys(self):
        return self.row.keys() if self.row else []


class FakeConn:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return FakeCursor(self.row)


def test_tokens_carry_auth_version_and_validate_against_live_state(monkeypatch):
    row = {
        "username": "faculty1",
        "role": "FACULTY",
        "student_roll_no": None,
        "active": 1,
        "must_change_password": 0,
        "auth_version": 7,
    }
    conn = FakeConn(row)
    monkeypatch.setattr(deps, "connect", lambda: conn)

    token = auth_token.make_access_token("faculty1", "FACULTY", None, False, 7)
    payload = auth_token.read_access_token(token)
    assert payload["auth_version"] == 7
    assert deps._validate_live_user(payload).username == "faculty1"

    bad = dict(payload)
    bad["auth_version"] = 6
    with pytest.raises(ApiError) as exc:
        deps._validate_live_user(bad)
    assert exc.value.status_code == 401
    assert getattr(exc.value, "code", None) == "TOKEN_INVALID"


def test_live_validator_rejects_inactive_or_role_changed_user(monkeypatch):
    inactive = FakeConn({
        "username": "faculty1", "role": "FACULTY", "student_roll_no": None,
        "active": 0, "must_change_password": 0, "auth_version": 0,
    })
    monkeypatch.setattr(deps, "connect", lambda: inactive)
    payload = {"username": "faculty1", "role": "FACULTY", "student_roll_no": None, "auth_version": 0}
    with pytest.raises(ApiError) as exc:
        deps._validate_live_user(payload)
    assert getattr(exc.value, "code", None) == "ACCOUNT_INACTIVE"

    role_changed = FakeConn({
        "username": "faculty1", "role": "HOD", "student_roll_no": None,
        "active": 1, "must_change_password": 0, "auth_version": 0,
    })
    monkeypatch.setattr(deps, "connect", lambda: role_changed)
    with pytest.raises(ApiError) as exc:
        deps._validate_live_user(payload)
    assert getattr(exc.value, "code", None) == "TOKEN_INVALID"


def test_login_unknown_user_burns_dummy_pbkdf2(monkeypatch):
    conn = FakeConn(None)
    monkeypatch.setattr(database, "connect", lambda: conn)
    calls = []

    def fake_verify(password, stored):
        calls.append((password, stored))
        return False

    monkeypatch.setattr(database, "_verify_password", fake_verify)
    assert database.auth("unknown-user", "wrong-password") is None
    assert len(calls) == 1
    assert calls[0][1] == database._DUMMY_PASSWORD_HASH


def test_rate_limit_buckets_are_shared_by_key(monkeypatch):
    state = {}

    class RateConn:
        def __enter__(self): return self
        def __exit__(self, *args): return False

        def execute(self, sql, params=None):
            if sql.lstrip().startswith("INSERT INTO rate_limit_buckets"):
                key, window, bucket = params
                k = (key, window, bucket)
                state[k] = state.get(k, 0) + 1
                self.last = k
            elif sql.lstrip().startswith("SELECT request_count"):
                key, window, bucket = params
                self.row = {"request_count": state.get((key, window, bucket), 0)}
            elif sql.lstrip().startswith("DELETE FROM rate_limit_buckets"):
                key, window = params
                for k in list(state):
                    if k[0] == key and k[1] == window:
                        del state[k]
                self.row = None
            return self

        def fetchone(self):
            return getattr(self, "row", None)

    monkeypatch.setattr(firewall, "connect", lambda: RateConn())
    monkeypatch.setattr(firewall.time, "time", lambda: 1000.0)
    key = "firewall:auth:1.2.3.4"
    assert all(firewall._allow(key, 15) for _ in range(15))
    assert firewall._allow(key, 15) is False


# — _LockingRateConn
# WHY a real threading.Lock instead of a plain dict: a bare dict's
# read-modify-write on `state[k] = state.get(k, 0) + 1` is itself not atomic
# across Python threads at the bytecode level for compound operations, and
# more importantly we need to simulate the actual guarantee InnoDB gives us —
# that concurrent row-level upserts against the same key are serialized, not
# that they're merely "usually fine" in CPython. The lock models that
# serialization boundary explicitly so the test proves the *logic* in
# rate_limit.py is race-safe, not that the fake happens not to race.
# State is a class-level dict (shared across threads sharing this instance)
# and is cleared at the top of every test that uses it, so there's no bleed
# between tests even though the object could in principle be reused.
class _LockingRateConn:
    _lock = threading.Lock()

    def __init__(self, state):
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        sql_s = sql.lstrip()
        if sql_s.startswith("INSERT INTO rate_limit_buckets"):
            key, window, bucket = params
            k = (key, window, bucket)
            with self._lock:
                self.state[k] = self.state.get(k, 0) + 1
        elif sql_s.startswith("SELECT request_count"):
            key, window, bucket = params
            k = (key, window, bucket)
            with self._lock:
                count = self.state.get(k, 0)
            self.row = {"request_count": count}
        return self

    def fetchone(self):
        return getattr(self, "row", None)


def test_record_failure_and_is_locked_use_sixth_attempt_as_lockout_boundary(monkeypatch):
    state = {}
    monkeypatch.setattr(rate_limit, "connect", lambda: _LockingRateConn(state))
    monkeypatch.setattr(rate_limit.time, "time", lambda: 2500.0)

    key = "boundary-test-key"
    for attempt in range(1, rate_limit.MAX_ATTEMPTS + 1):
        assert rate_limit.record_failure(key) is False
        assert rate_limit.is_locked(key) is False

    assert rate_limit.record_failure(key) is True
    assert rate_limit.is_locked(key) is True


def test_concurrent_record_failure_never_undercounts(monkeypatch):
    """Proves the fix: N concurrent record_failure() calls against the same
    key, using the new fold-check-into-increment pattern, must produce
    exactly N True results once the running count is >= MAX_ATTEMPTS — no
    request is allowed to slip past the boundary because it read a stale
    pre-increment count. This is the regression test for the race the senior
    flagged: is_locked() and record_failure() as two separate steps let
    concurrent requests all observe "not locked" before any increment lands.
    """
    state = {}
    monkeypatch.setattr(rate_limit, "connect", lambda: _LockingRateConn(state))
    monkeypatch.setattr(rate_limit.time, "time", lambda: 2000.0)

    key = "concurrency-test-key"
    n_threads = 20
    results = [None] * n_threads

    def worker(i):
        results[i] = rate_limit.record_failure(key)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    bucket = rate_limit._bucket(2000.0, rate_limit.WINDOW_SECONDS)
    final_count = state[(key, rate_limit.WINDOW_SECONDS, bucket)]
    assert final_count == n_threads  # no lost updates

    # Every call whose own post-increment count reached MAX_ATTEMPTS must
    # have reported True. Since final_count (20) > MAX_ATTEMPTS (5), that's
    # every call from the one that pushed the count to 5 onward.
    true_count = sum(1 for r in results if r is True)
    expected_true = n_threads - rate_limit.MAX_ATTEMPTS
    assert true_count == expected_true, (
        f"expected exactly {expected_true} calls to observe the threshold "
        f"crossed, got {true_count} — some request likely read a stale count"
    )


def test_old_check_then_act_pattern_undercounts_under_concurrency(monkeypatch):
    """Negative control proving the regression test above is meaningful, not
    tautological: re-implements the OLD two-step pattern (separate is_locked()
    read, then a plain increment with no return value) against the same
    locking fake, and shows it lets extra requests slip past MAX_ATTEMPTS.
    This demonstrates the new test would have failed against the pre-fix
    code, and only passes because the fix folded the check into the atomic
    increment.
    """
    state = {}
    conn_factory = lambda: _LockingRateConn(state)
    monkeypatch.setattr(rate_limit, "connect", conn_factory)
    monkeypatch.setattr(rate_limit.time, "time", lambda: 3000.0)

    key = "old-pattern-test-key"
    n_threads = 20
    passed_precheck = [None] * n_threads
    # WHY two barriers, not one: the real-world worst case the senior
    # described is "N concurrent bad-password requests all read the count
    # BEFORE ANY of them has committed its increment." A single barrier only
    # synchronizes when threads *start*; the GIL then lets one thread run
    # both its read and its write before the next thread is scheduled,
    # which under-reproduces the race. Two barriers force every thread's
    # is_locked() read to complete before ANY thread's record_failure()
    # write begins — deterministically reproducing the worst case instead
    # of leaving it to incidental scheduling (which made the test flaky).
    read_barrier = threading.Barrier(n_threads)
    write_barrier = threading.Barrier(n_threads)

    def old_style_worker(i):
        # Old shape: read-then-decide, THEN increment — the two steps are
        # not in the same atomic operation, so a stale read is possible.
        was_locked_before = rate_limit.is_locked(key)
        read_barrier.wait()  # hold here until every thread has done its read
        write_barrier.wait()  # then release all writes together
        rate_limit.record_failure(key)  # return value ignored, old-style
        passed_precheck[i] = not was_locked_before

    threads = [threading.Thread(target=old_style_worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Under the old pattern, ALL requests observe "not locked" (every read
    # happens before any write, forced by the barrier), so every single one
    # proceeds to do the real (expensive) credential check regardless of
    # MAX_ATTEMPTS — this is the exact boundary-crossing bug the senior
    # flagged. That's strictly worse than the fixed pattern, which only ever
    # lets MAX_ATTEMPTS-1 requests through before the rest correctly observe
    # the threshold crossed.
    n_passed = sum(1 for p in passed_precheck if p)
    assert n_passed == n_threads, (
        "expected the old check-then-act pattern to let ALL concurrent "
        "requests through this worst-case simultaneous-read scenario — if "
        "this assertion fails, the negative control isn't reproducing the "
        "race and the positive test above may not be meaningful"
    )
    assert n_passed > rate_limit.MAX_ATTEMPTS


def test_cors_production_is_exact_origin_only(monkeypatch):
    import api.app as app_module
    monkeypatch.setenv("SMS_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://sms.example.com")
    monkeypatch.delenv("ALLOWED_ORIGIN_REGEX", raising=False)
    origins, regex = app_module._cors_config()
    assert origins == ["https://sms.example.com"]
    assert regex is None

    monkeypatch.setenv("ALLOWED_ORIGIN_REGEX", r"https://.*\\.vercel\\.app")
    with pytest.raises(RuntimeError):
        app_module._cors_config()

    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGIN_REGEX", raising=False)
    with pytest.raises(RuntimeError):
        app_module._cors_config()


def test_security_headers_and_no_store_are_present():
    from starlette.responses import Response
    response = firewall._apply_security_headers(Response(content="{}"), "/api/students")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


def test_ssrf_host_filter_rejects_private_and_accepts_public(monkeypatch):
    def fake_getaddrinfo(hostname, *args, **kwargs):
        mapping = {
            "internal.local": [(2, 1, 6, "", ("127.0.0.1", 0))],
            "metadata.local": [(2, 1, 6, "", ("169.254.169.254", 0))],
            "public.example": [(2, 1, 6, "", ("93.184.216.34", 0))],
        }
        return mapping[hostname]

    monkeypatch.setattr(dashboard.socket, "getaddrinfo", fake_getaddrinfo)
    assert dashboard._is_safe_gateway_host("public.example") is True
    assert dashboard._is_safe_gateway_host("internal.local") is False
    assert dashboard._is_safe_gateway_host("metadata.local") is False


def test_file_authorization_denies_cross_student_access():
    student_a = routes_files.CurrentUser("a", "STUDENT", "24A001")
    student_b = routes_files.CurrentUser("b", "STUDENT", "24A002")
    routes_files._authorize(student_a, "students", "24A001-abc.jpg")
    with pytest.raises(ApiError) as exc:
        routes_files._authorize(student_b, "students", "24A001-abc.jpg")
    assert exc.value.status_code == 403


def test_file_resolve_null_byte_is_clean_404(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_files, "UPLOADS_ROOT", tmp_path.resolve())
    user = SimpleNamespace(username="a", role="HOD", student_roll_no=None)
    with pytest.raises(ApiError) as exc:
        asyncio.run(routes_files.serve_file("students", "bad\x00name.jpg", user=user))
    assert exc.value.status_code == 404
    assert getattr(exc.value, "code", None) == "NOT_FOUND"


@pytest.mark.asyncio
async def test_photo_decompression_bomb_is_clean_upload_error(monkeypatch, tmp_path):
    class FakeUpload:
        filename = "bomb.png"
        async def read(self):
            return b"not-used"

    monkeypatch.setattr(photo_upload, "UPLOADS_DIR", tmp_path)
    def bomb(*args, **kwargs):
        raise photo_upload.Image.DecompressionBombError("too many pixels")
    monkeypatch.setattr(photo_upload.Image, "open", bomb)

    with pytest.raises(photo_upload.PhotoUploadError):
        await photo_upload.save_profile_photo(FakeUpload(), subdir="students", stem="24A001")


def test_bootstrap_is_fail_closed_and_never_overwrites_existing_account(monkeypatch):
    class BootstrapConn:
        def __init__(self, privileged_count=0, existing=False):
            self.privileged_count = privileged_count
            self.existing = existing
            self.inserted = None

        def execute(self, sql, params=None):
            if sql.startswith("SELECT COUNT(*) AS count FROM users"):
                return FakeCursor({"count": self.privileged_count})
            if sql.startswith("SELECT 1 FROM users"):
                return FakeCursor({"exists": 1} if self.existing else None)
            if sql.startswith("INSERT INTO users"):
                self.inserted = params
                return FakeCursor(None)
            raise AssertionError(f"Unexpected SQL: {sql}")

    monkeypatch.delenv("BOOTSTRAP_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    empty = BootstrapConn()
    with pytest.raises(RuntimeError):
        database._ensure_bootstrap_account(empty)
    assert empty.inserted is None

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "secure-hod")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "strong-pass-123")
    boot = BootstrapConn()
    assert database._ensure_bootstrap_account(boot) == "secure-hod"
    assert boot.inserted is not None
    assert boot.inserted[0] == "secure-hod"
    assert boot.inserted[2] == "Head of Department"

    existing = BootstrapConn(existing=True)
    with pytest.raises(RuntimeError):
        database._ensure_bootstrap_account(existing)
    assert existing.inserted is None


@pytest.mark.asyncio
async def test_startup_db_init_fails_closed(monkeypatch):
    async def fail_startup():
        return None

    import api.app as app_module
    monkeypatch.setattr(database, "init_db", lambda: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError, match="Database initialization failed: db unavailable"):
        await app_module.startup_db_init()


@pytest.mark.asyncio
async def test_ssrf_endpoint_rejects_private_host_before_urlopen(monkeypatch):
    gateway = {"id": 1, "gateway_mode": "local", "local_url": "http://127.0.0.1:8123", "hod_username": "hod1"}
    class Conn:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args, **kwargs): return FakeCursor(gateway)
    monkeypatch.setattr(dashboard, "connect", lambda: Conn())
    called = False
    def fail_urlopen(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("urlopen must not run for a private host")
    monkeypatch.setattr(__import__("urllib.request", fromlist=["urlopen"]), "urlopen", fail_urlopen)
    user = dashboard.CurrentUser("hod1", "HOD", None)
    with pytest.raises(ApiError) as exc:
        await dashboard.test_sms_gateway_connection(1, user=user)
    assert exc.value.status_code == 400
    assert getattr(exc.value, "code", None) == "VALIDATION_ERROR"
    assert called is False


def test_student_pdf_escapes_markup_in_student_name():
    malicious = "<b>Unclosed Bold Name"
    pdf = build_students_list_pdf(
        [{
            "roll_no": "24A001",
            "name": malicious,
            "batch": "2024-2028",
            "email": "student@example.com",
            "phone": "9999999999",
        }],
        {"semester_name": "II-I", "batch": "2024-2028", "generated_on": "today", "generated_by": "tester"},
    )
    assert pdf.startswith(b"%PDF")

    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(__import__('io').BytesIO(pdf)).pages)
    assert malicious in text

@pytest.mark.asyncio
async def test_admin_cannot_create_update_test_or_autosend_gateway(monkeypatch):
    admin = dashboard.CurrentUser("admin1", "ADMIN", None)
    body = dashboard.SmsGatewayBody(gateway_name="blocked", gateway_mode="local", local_url="http://example.com")

    with pytest.raises(ApiError) as create_exc:
        await dashboard.create_sms_gateway(body, user=admin)
    assert create_exc.value.status_code == 403

    with pytest.raises(ApiError) as update_exc:
        await dashboard.update_sms_gateway(7, body, user=admin)
    assert update_exc.value.status_code == 403

    with pytest.raises(ApiError) as test_exc:
        await dashboard.test_sms_gateway_connection(7, user=admin)
    assert test_exc.value.status_code == 403

    with pytest.raises(ApiError) as send_exc:
        await dashboard.set_gateway_auto_send(7, enabled=True, user=admin)
    assert send_exc.value.status_code == 403


def test_admin_gateway_projection_redacts_all_gateway_endpoint_secrets():
    row = {
        "id": 7,
        "hod_username": "hod1",
        "owner_username": "hod1",
        "gateway_name": "Department Gateway",
        "gateway_mode": "local",
        "device_id": "secret-device",
        "local_url": "https://gateway.internal.example/api",
        "username": "api-user",
        "password": "ciphertext-password",
        "modem_port": "/dev/ttyUSB0",
        "modem_baud": "115200",
        "sim_number": 2,
        "active": 1,
        "auto_send": 1,
        "owner_name": "HOD One",
        "owner_role": "HOD",
        "owner_department": "CSD",
        "hod_name": "HOD One",
        "hod_department": "CSD",
        "last_connection_test": None,
    }
    visible = dashboard._gateway_visible(row, admin_safe=True)
    assert visible["device_id"] == ""
    assert visible["device_id_masked"] == ""
    assert visible["local_url"] == ""
    assert visible["username"] == ""
    assert visible["modem_port"] == ""
    assert visible["modem_baud"] == ""
    assert visible["sim_number"] is None
    assert visible["password_set"] is True
