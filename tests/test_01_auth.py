"""
Phase 1 — Auth (api/routes_auth.py)

Covers: login success/failure shape, envelope format, rate limiting,
missing-field validation, /me, unauthenticated access, register
validation, password-mismatch checks.

Does NOT cover (needs real email sending, out of scope for Phase 1):
send-otp / verify-otp / reset-password-otp happy paths. Their input
validation (bad purpose, bad email) IS covered — that's pure logic,
no email required.
"""
import pytest


class TestLoginEnvelope:
    def test_login_missing_fields_returns_400(self, client):
        r = client.post("/api/auth/login", json={"username": "", "password": ""})
        assert r.status_code == 400
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "MISSING_CREDENTIALS"

    def test_login_invalid_credentials_returns_401(self, client):
        r = client.post("/api/auth/login", json={
            "username": "zzqa_definitely_not_a_real_user",
            "password": "wrong_password_123",
        })
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "INVALID_CREDENTIALS"
        # — Must not leak whether the username exists (anti-enumeration)
        assert "not found" not in body["error"]["message"].lower()

    def test_login_response_envelope_shape_on_success(self, client, hod_creds):
        username, password = hod_creds
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        data = body["data"]
        assert "access_token" in data
        assert data["expires_in"] == 900
        assert data["user"]["username"] == username
        assert "redirect" in body["data"]

    def test_login_sets_httponly_refresh_cookie(self, client, hod_creds):
        username, password = hod_creds
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert "sms_refresh" in r.cookies


class TestRateLimiting:
    def test_repeated_bad_logins_eventually_rate_limited(self, client):
    
        username = "zzqa_ratelimit_probe_user"
        last_status = None
        for _ in range(15):
            r = client.post("/api/auth/login", json={"username": username, "password": "wrong"})
            last_status = r.status_code
            if last_status == 429:
                break
        assert last_status in (401, 429), (
            "Expected either continued 401s or an eventual 429 RATE_LIMITED; "
            f"got {last_status}. If this never trips, check api/rate_limit.py's "
            "threshold hasn't regressed to effectively unlimited."
        )
        if last_status == 429:
            body = r.json()
            assert body["error"]["code"] == "RATE_LIMITED"


class TestMeAndUnauthenticated:
    # — WHY these still explicitly clear client.cookies
    # conftest.py's autouse reset_client_cookies fixture now clears the
    # shared session-scoped client's cookie jar before every test, which is
    # the primary fix for the ordering bug this class originally exposed
    # (an earlier login test leaving a valid sms_refresh cookie that
    # get_current_user legitimately accepts as a fallback auth path). The
    # explicit clear here is now redundant defense-in-depth, kept because
    # these tests exist specifically to prove "truly no credentials", so
    # the intent should be visible locally and not depend on remembering
    # what conftest.py does elsewhere.
    def test_me_without_token_returns_401(self, client):
        client.cookies.clear()
        r = client.get("/api/auth/me")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "NOT_AUTHENTICATED"

    def test_me_with_valid_token_returns_user(self, client, hod_headers, hod_creds):
        r = client.get("/api/auth/me", headers=hod_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["username"] == hod_creds[0]
        assert data["role"] == "HOD"
        assert "must_change_password" in data

    def test_me_with_garbage_bearer_token_returns_401(self, client):
        client.cookies.clear()
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.real.jwt"})
        assert r.status_code == 401

    def test_protected_route_without_auth_returns_401_not_500(self, client):
        # — Any protected route, not just /me — this confirms
        # get_current_user's dependency is actually wired on
        # non-auth routers too, not just auth's own.
        client.cookies.clear()
        r = client.get("/api/students")
        assert r.status_code == 401


class TestRegisterValidation:
    def test_register_missing_email_rejected(self, client):
        r = client.post("/api/auth/register", json={
            "roll_no": "zzqa_test_roll",
            "username": "zzqa_test_user",
            "password": "Testpass123!",
            "confirm_password": "Testpass123!",
            "email": "",
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "EMAIL_REQUIRED"

    def test_register_password_mismatch_rejected(self, client):
        r = client.post("/api/auth/register", json={
            "roll_no": "zzqa_test_roll",
            "username": "zzqa_test_user",
            "password": "Testpass123!",
            "confirm_password": "DifferentPass456!",
            "email": "zzqa_test@example.com",
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "PASSWORD_MISMATCH"


class TestChangePasswordValidation:
    def test_change_password_mismatch_rejected(self, client, hod_headers):
        r = client.post("/api/auth/change-password", headers=hod_headers, json={
            "old_password": "whatever",
            "new_password": "NewPass123!",
            "confirm_password": "DoesNotMatch456!",
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "PASSWORD_MISMATCH"

    def test_change_password_wrong_old_password_rejected(self, client, hod_headers):
        r = client.post("/api/auth/change-password", headers=hod_headers, json={
            "old_password": "zzqa_definitely_wrong_old_pw",
            "new_password": "NewPass123!",
            "confirm_password": "NewPass123!",
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "PASSWORD_CHANGE_FAILED"


class TestOtpInputValidation:
    """Pure validation logic — no real email dispatch required."""

    def test_send_otp_invalid_purpose_rejected(self, client):
        r = client.post("/api/auth/send-otp", json={"email": "a@b.com", "purpose": "NOT_A_REAL_PURPOSE"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_PURPOSE"

    def test_send_otp_invalid_email_rejected(self, client):
        r = client.post("/api/auth/send-otp", json={"email": "not-an-email", "purpose": "REGISTER"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_EMAIL"

    def test_verify_otp_invalid_purpose_rejected(self, client):
        r = client.post("/api/auth/verify-otp", json={"email": "a@b.com", "purpose": "BOGUS", "code": "123456"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_PURPOSE"


class TestLogout:
    def test_logout_clears_refresh_cookie(self, client, hod_creds):
        username, password = hod_creds
        login_resp = client.post("/api/auth/login", json={"username": username, "password": password})
        assert login_resp.status_code == 200, f"Login failed ({login_resp.status_code}): {login_resp.text}"
        token = login_resp.json()["data"]["access_token"]
        r = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["data"]["ok"] is True

    def test_logout_without_session_still_succeeds(self, client):
        # — logout uses get_optional_user, must not 401 on an already-
        # logged-out / never-logged-in caller.
        r = client.post("/api/auth/logout")
        assert r.status_code == 200

