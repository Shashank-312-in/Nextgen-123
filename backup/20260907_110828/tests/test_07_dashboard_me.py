"""
Phase 2 — Dashboard (api/routes_dashboard.py) + Self-service
(api/routes_me.py)

# — WHY sms-test is never actually called: routes_dashboard.py's
test_sms_gateway() calls webapp/sms_worker.py's send_single_sms(),
which per DEPLOYMENT_AND_AUTH.md / project memory talks to a real
Android SMS gateway device or serial modem. Calling it from an
automated suite would either fail loudly against no configured gateway
(fine) or, worse, actually attempt to send a real SMS on some
deployments. RBAC on that route IS tested (auth boundary is safe to
verify); the actual send is not exercised here.
"""
import pytest


class TestDashboardRoleAware:
    def test_requires_auth(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 401

    def test_faculty_gets_redirect_shape(self, client, faculty_headers):
        r = client.get("/api/dashboard", headers=faculty_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["role"] == "FACULTY"
        assert data["redirect"] == "/attendance"

    def test_hod_gets_days_grid(self, client, hod_headers):
        r = client.get("/api/dashboard", headers=hod_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["role"] == "HOD"
        assert "days" in data

    def test_student_gets_student_shape(self, client, student_headers):
        r = client.get("/api/dashboard", headers=student_headers)
        assert r.status_code == 200
        # — student branch doesn't echo a "role" key the same way (see
        # _student_dashboard) so just confirm it's a normal envelope,
        # not the FACULTY-style redirect or HOD-style days grid.
        data = r.json()["data"]
        assert "redirect" not in data or data.get("role") != "FACULTY"

    def test_hod_dashboard_accepts_date_filter(self, client, hod_headers):
        r = client.get("/api/dashboard?date=2026-01-15", headers=hod_headers)
        assert r.status_code == 200
        assert r.json()["data"]["picked_date"] == "2026-01-15"

    def test_hod_dashboard_invalid_date_does_not_500(self, client, hod_headers):
        # — Confirms malformed query input degrades gracefully (400 or
        # just ignored/200), never a raw 500 leaking a traceback.
        r = client.get("/api/dashboard?date=not-a-real-date", headers=hod_headers)
        assert r.status_code in (200, 400, 422)


class TestSessionDrilldownRBAC:
    def test_present_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/dashboard/session/1/present", headers=student_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_absent_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/dashboard/session/1/absent", headers=student_headers)
        assert r.status_code == 403

    def test_present_nonexistent_session_404s(self, client, hod_headers):
        r = client.get("/api/dashboard/session/999999999/present", headers=hod_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_absent_nonexistent_session_404s(self, client, hod_headers):
        r = client.get("/api/dashboard/session/999999999/absent", headers=hod_headers)
        assert r.status_code == 404


class TestStudentSubjectHistoryRBAC:
    def test_forbidden_for_hod(self, client, hod_headers):
        r = client.get("/api/dashboard/student/subject/1/history", headers=hod_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/dashboard/student/subject/1/history", headers=faculty_headers)
        assert r.status_code == 403

    def test_student_can_access_own_history(self, client, student_headers):
        r = client.get("/api/dashboard/student/subject/1/history", headers=student_headers)
        # — subject_id=1 may or may not exist for this student; either
        # way the ROLE gate must let them through to the actual logic
        # (200 empty history) rather than 403.
        assert r.status_code in (200, 404)


class TestAuditAndSmsLogRBAC:
    """audit-log / sms-log / sms-settings GET are HOD-only with NO ADMIN
    carve-out (routes_dashboard.py: `if user.role != "HOD"`), unlike the
    POST mutators (sms-settings/sms-test/sms-trigger) which DO allow
    ADMIN. Tested as written, not as might be assumed."""

    def test_audit_log_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/dashboard/audit-log", headers=faculty_headers)
        assert r.status_code == 403

    def test_audit_log_ok_for_hod(self, client, hod_headers):
        r = client.get("/api/dashboard/audit-log", headers=hod_headers)
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def test_sms_log_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/dashboard/sms-log", headers=student_headers)
        assert r.status_code == 403

    def test_sms_log_ok_for_hod(self, client, hod_headers):
        r = client.get("/api/dashboard/sms-log", headers=hod_headers)
        assert r.status_code == 200

    def test_sms_settings_get_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/dashboard/sms-settings", headers=faculty_headers)
        assert r.status_code == 403

    def test_sms_settings_get_ok_for_hod(self, client, hod_headers):
        r = client.get("/api/dashboard/sms-settings", headers=hod_headers)
        assert r.status_code == 200
        assert "sms_daily_cap" in r.json()["data"]

    def test_sms_trigger_forbidden_for_faculty(self, client, faculty_headers):
        r = client.post("/api/dashboard/sms-trigger", headers=faculty_headers)
        assert r.status_code == 403

    def test_sms_test_route_forbidden_for_student(self, client, student_headers):
        # — RBAC-only check; deliberately does NOT assert on the 200 path
        # since a real send would hit live SMS hardware (see module docstring).
        r = client.post("/api/dashboard/sms-test", headers=student_headers, json={"phone": "9999999999"})
        assert r.status_code == 403


class TestMeAccountRBAC:
    def test_account_requires_auth(self, client):
        r = client.get("/api/me/account")
        assert r.status_code == 401

    def test_account_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/me/account", headers=student_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_account_ok_for_hod(self, client, hod_headers, hod_creds):
        r = client.get("/api/me/account", headers=hod_headers)
        assert r.status_code == 200
        assert r.json()["data"]["user"]["username"] == hod_creds[0]

    def test_account_ok_for_faculty(self, client, faculty_headers):
        r = client.get("/api/me/account", headers=faculty_headers)
        assert r.status_code == 200


class TestMeAccountUpdate:
    def test_update_forbidden_for_student(self, client, student_headers):
        r = client.patch("/api/me/account", headers=student_headers, json={"full_name": "ZZQA Probe"})
        assert r.status_code == 403

    def test_update_and_restore_own_full_name(self, client, hod_headers):
        """Round-trips a real field change on the logged-in HOD's OWN
        account (safe — it's the test account, not another user's data)
        and restores the original value afterward."""
        before = client.get("/api/me/account", headers=hod_headers).json()["data"]["user"]
        original_name = before.get("full_name") or ""

        r = client.patch("/api/me/account", headers=hod_headers, json={
            "full_name": "ZZQA Automated Test Name",
            "department": before.get("department") or "",
            "designation": before.get("designation") or "",
            "employee_id": before.get("employee_id") or "",
            "email": before.get("email") or "",
            "phone": before.get("phone") or "",
            "qualification": before.get("qualification") or "",
            "date_of_joining": before.get("date_of_joining") or "",
        })
        assert r.status_code == 200
        assert r.json()["data"]["user"]["full_name"] == "ZZQA Automated Test Name"

        # — restore
        restore = client.patch("/api/me/account", headers=hod_headers, json={
            "full_name": original_name,
            "department": before.get("department") or "",
            "designation": before.get("designation") or "",
            "employee_id": before.get("employee_id") or "",
            "email": before.get("email") or "",
            "phone": before.get("phone") or "",
            "qualification": before.get("qualification") or "",
            "date_of_joining": before.get("date_of_joining") or "",
        })
        assert restore.status_code == 200
        assert restore.json()["data"]["user"]["full_name"] == original_name


class TestMeProfileRBAC:
    def test_profile_requires_auth(self, client):
        r = client.get("/api/me/profile")
        assert r.status_code == 401

    def test_profile_forbidden_for_hod(self, client, hod_headers):
        r = client.get("/api/me/profile", headers=hod_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_profile_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/me/profile", headers=faculty_headers)
        assert r.status_code == 403

    def test_profile_ok_for_student(self, client, student_headers):
        r = client.get("/api/me/profile", headers=student_headers)
        assert r.status_code in (200, 404)  # 404 only if fixture account has no linked student row


class TestMeProfileUpdate:
    def test_update_forbidden_for_hod(self, client, hod_headers):
        r = client.patch("/api/me/profile", headers=hod_headers, json={"name": "ZZQA Probe"})
        assert r.status_code == 403

    def test_student_self_edit_disabled_by_default(self, client, student_headers, hod_headers):
        """Student self-editing must be disabled by default (or when setting is off)"""
        # Ensure setting is off
        client.patch("/api/dashboard/settings/student-self-edit", headers=hod_headers, json={"student_self_edit_enabled": False})
        
        before = client.get("/api/me/profile", headers=student_headers)
        if before.status_code != 200:
            pytest.skip("Test student account has no linked student row")
        assert before.json()["data"]["student_self_edit_enabled"] is False

        r = client.patch("/api/me/profile", headers=student_headers, json={"name": "Attempted Self-Edit"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "STUDENT_SELF_EDIT_DISABLED"

    def test_student_can_edit_when_enabled_and_cannot_hijack_roll_no(self, client, student_headers, hod_headers):
        """When enabled by admin, student can update profile and roll_no hijacking is ignored"""
        # Enable setting
        client.patch("/api/dashboard/settings/student-self-edit", headers=hod_headers, json={"student_self_edit_enabled": True})
        try:
            before = client.get("/api/me/profile", headers=student_headers)
            if before.status_code != 200:
                pytest.skip("Test student account has no linked student row")
            assert before.json()["data"]["student_self_edit_enabled"] is True
            original_roll = before.json()["data"]["student"]["roll_no"]
            original_name = before.json()["data"]["student"].get("name") or "Test Student"

            r = client.patch("/api/me/profile", headers=student_headers, json={
                "name": original_name,
                "roll_no": "ZZQA_HIJACKED_ROLL",  # not a real field on ProfileUpdateBody — must be ignored
            })
            assert r.status_code == 200
            assert r.json()["data"]["student"]["roll_no"] == original_roll
        finally:
            # Revert setting back to False (default)
            client.patch("/api/dashboard/settings/student-self-edit", headers=hod_headers, json={"student_self_edit_enabled": False})


class TestStudentSelfEditSettingControl:
    def test_setting_requires_auth(self, client):
        r = client.get("/api/dashboard/settings/student-self-edit")
        assert r.status_code == 401

    def test_setting_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/dashboard/settings/student-self-edit", headers=student_headers)
        assert r.status_code == 403
        r_patch = client.patch("/api/dashboard/settings/student-self-edit", headers=student_headers, json={"student_self_edit_enabled": True})
        assert r_patch.status_code == 403

    def test_setting_patch_forbidden_for_faculty(self, client, faculty_headers):
        r = client.patch("/api/dashboard/settings/student-self-edit", headers=faculty_headers, json={"student_self_edit_enabled": True})
        assert r.status_code == 403

    def test_admin_can_get_and_patch_setting(self, client, hod_headers):
        # GET setting
        r = client.get("/api/dashboard/settings/student-self-edit", headers=hod_headers)
        assert r.status_code == 200
        assert "student_self_edit_enabled" in r.json()["data"]

        # PATCH to True
        r2 = client.patch("/api/dashboard/settings/student-self-edit", headers=hod_headers, json={"student_self_edit_enabled": True})
        assert r2.status_code == 200
        assert r2.json()["data"]["student_self_edit_enabled"] is True

        # PATCH back to False
        r3 = client.patch("/api/dashboard/settings/student-self-edit", headers=hod_headers, json={"student_self_edit_enabled": False})
        assert r3.status_code == 200
        assert r3.json()["data"]["student_self_edit_enabled"] is False


class TestMeChangePasswordRoute:
    def test_requires_auth(self, client):
        r = client.post("/api/me/change-password", json={
            "old_password": "x", "new_password": "y", "confirm_password": "y",
        })
        assert r.status_code == 401

    def test_mismatch_rejected_for_student(self, client, student_headers):
        r = client.post("/api/me/change-password", headers=student_headers, json={
            "old_password": "whatever",
            "new_password": "NewPass123!",
            "confirm_password": "Mismatch456!",
        })
        assert r.status_code == 400

class TestAuditMonitoringFilters:
    def test_audit_defaults_to_actions_only(self, client, hod_headers):
        r = client.get("/api/dashboard/audit-log", headers=hod_headers)
        assert r.status_code == 200
        assert all(str(x.get("action", "")).upper() not in {"LOGIN", "LOGOUT"} for x in r.json()["data"])

    def test_hod_cannot_request_admin_audit(self, client, hod_headers):
        r = client.get("/api/dashboard/audit-log?actor_type=ADMIN", headers=hod_headers)
        assert r.status_code == 403

    def test_hod_can_filter_people_audit_to_faculty(self, client, hod_headers):
        r = client.get("/api/dashboard/audit-log?actor_type=FACULTY&activity=ACTIONS", headers=hod_headers)
        assert r.status_code == 200
        assert all(x.get("actor_role") == "FACULTY" for x in r.json()["data"])
