"""
Phase 2 — Faculty & Accounts (api/routes_faculty.py)

Covers: HOD/ADMIN-only RBAC (this file's _require_hod allows BOTH, unlike
routes_subjects.py's — see test_05_subjects_calendar.py's dedicated drift
test for that gap), permission-update validation, and the three
self-protection guards in account lifecycle routes:
  - toggle-status blocks deactivating HOD accounts or yourself
  - delete blocks deleting yourself or username "admin"
  - reset-password only works on STUDENT-linked accounts

# — WHY no full create-account lifecycle test here: create_user() writes
a real login credential pair with no safe generic teardown path across
unknown schema variations (unlike students, which has a documented
DELETE cascade). RBAC and validation on create-account ARE covered;
the full create->delete round trip is deliberately left for a manual
smoke test rather than risking orphaned login rows.
"""
import pytest


class TestFacultyPageRBAC:
    def test_requires_auth(self, client):
        r = client.get("/api/faculty")
        assert r.status_code == 401

    def test_forbidden_for_faculty_role(self, client, faculty_headers):
        # — Faculty accounts cannot view the Faculty management page itself.
        r = client.get("/api/faculty", headers=faculty_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/faculty", headers=student_headers)
        assert r.status_code == 403

    def test_hod_can_view(self, client, hod_headers):
        r = client.get("/api/faculty", headers=hod_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert "hours" in data
        assert "accounts" in data
        assert "permissions" in data


class TestPermissionsRBAC:
    def test_get_permissions_requires_hod(self, client, faculty_headers):
        r = client.get("/api/faculty/permissions", headers=faculty_headers)
        assert r.status_code == 403

    def test_get_permissions_ok_for_hod(self, client, hod_headers):
        r = client.get("/api/faculty/permissions", headers=hod_headers)
        assert r.status_code == 200
        assert "permissions" in r.json()["data"]


class TestPermissionUpdateValidation:
    def test_invalid_role_rejected(self, client, hod_headers):
        r = client.post("/api/faculty/permissions", headers=hod_headers, json={
            "role": "STUDENT",  # only HOD/FACULTY are valid targets
            "can_view_student_phone": True,
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_forbidden_for_non_hod(self, client, faculty_headers):
        r = client.post("/api/faculty/permissions", headers=faculty_headers, json={"role": "FACULTY"})
        assert r.status_code == 403

    def test_valid_role_update_round_trips(self, client, hod_headers):
        """Reads current FACULTY permissions, flips one boolean, writes it
        back, confirms it stuck, then restores the original value so this
        test doesn't leave a permanent side effect on a real permission row."""
        before = client.get("/api/faculty/permissions", headers=hod_headers).json()["data"]["permissions"]
        faculty_perm = next((p for p in before if p.get("role") == "FACULTY"), None)
        if faculty_perm is None:
            pytest.skip("No FACULTY permission row found to test against")

        original_value = bool(faculty_perm.get("can_manage_calendar", True))
        flipped = not original_value

        body = {
            "role": "FACULTY",
            "can_view_student_phone": faculty_perm.get("can_view_student_phone", True),
            "can_edit_students": faculty_perm.get("can_edit_students", False),
            "can_delete_students": faculty_perm.get("can_delete_students", False),
            "can_view_audit_logs": faculty_perm.get("can_view_audit_logs", False),
            "can_view_sms_logs": faculty_perm.get("can_view_sms_logs", False),
            "can_manage_calendar": flipped,
            "can_manage_subjects": faculty_perm.get("can_manage_subjects", True),
        }
        r = client.post("/api/faculty/permissions", headers=hod_headers, json=body)
        assert r.status_code == 200

        after = client.get("/api/faculty/permissions", headers=hod_headers).json()["data"]["permissions"]
        after_faculty = next(p for p in after if p.get("role") == "FACULTY")
        assert bool(after_faculty["can_manage_calendar"]) == flipped

        # — restore original value; teardown, not a new assertion
        body["can_manage_calendar"] = original_value
        client.post("/api/faculty/permissions", headers=hod_headers, json=body)


class TestAccountAdminGuards:
    """These test the self-protection logic directly, using safe targets
    (the HOD's own account id, a nonexistent id) rather than mutating a
    real second account."""

    def _hod_account_id(self, client, hod_headers, hod_creds):
        accounts = client.get("/api/faculty", headers=hod_headers).json()["data"]["accounts"]
        me = next((a for a in accounts if a["username"] == hod_creds[0]), None)
        if me is None:
            pytest.skip("Could not locate logged-in HOD's own account row")
        return me["id"]

    def test_cannot_toggle_status_of_own_account(self, client, hod_headers, hod_creds):
        account_id = self._hod_account_id(client, hod_headers, hod_creds)
        r = client.post(f"/api/faculty/accounts/{account_id}/toggle-status", headers=hod_headers)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "SELF_DEACTIVATE"

    def test_cannot_delete_own_account(self, client, hod_headers, hod_creds):
        account_id = self._hod_account_id(client, hod_headers, hod_creds)
        r = client.delete(f"/api/faculty/accounts/{account_id}", headers=hod_headers)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "CANNOT_DELETE_ADMIN"

    def test_toggle_status_nonexistent_account_404s(self, client, hod_headers):
        r = client.post("/api/faculty/accounts/999999999/toggle-status", headers=hod_headers)
        assert r.status_code == 404

    def test_delete_nonexistent_account_404s(self, client, hod_headers):
        r = client.delete("/api/faculty/accounts/999999999", headers=hod_headers)
        assert r.status_code == 404

    def test_reset_password_on_own_hod_account_rejected(self, client, hod_headers, hod_creds):
        # — reset-password only works on STUDENT-linked accounts; the
        # logged-in HOD's own account is role=HOD, so this must reject.
        account_id = self._hod_account_id(client, hod_headers, hod_creds)
        r = client.post(f"/api/faculty/accounts/{account_id}/reset-password", headers=hod_headers)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_account_lifecycle_routes_forbidden_for_faculty(self, client, faculty_headers):
        r1 = client.post("/api/faculty/accounts/1/toggle-status", headers=faculty_headers)
        r2 = client.delete("/api/faculty/accounts/1", headers=faculty_headers)
        r3 = client.post("/api/faculty/accounts/1/reset-password", headers=faculty_headers)
        assert r1.status_code == 403
        assert r2.status_code == 403
        assert r3.status_code == 403


class TestCreateAccountValidation:
    def test_forbidden_for_faculty(self, client, faculty_headers, run_tag):
        r = client.post("/api/faculty/create-account", headers=faculty_headers, json={
            "username": f"{run_tag}_probe",
            "password": "Testpass123!",
            "role": "FACULTY",
        })
        assert r.status_code == 403

    def test_requires_auth(self, client, run_tag):
        r = client.post("/api/faculty/create-account", json={
            "username": f"{run_tag}_probe",
            "password": "Testpass123!",
            "role": "FACULTY",
        })
        assert r.status_code == 401

    def test_missing_required_fields_returns_422(self, client, hod_headers):
        r = client.post("/api/faculty/create-account", headers=hod_headers, json={"role": "FACULTY"})
        assert r.status_code == 422

class TestStrictAdminHierarchy:
    def test_hod_cannot_edit_admin_role_permissions(self, client, hod_headers):
        r = client.post("/api/faculty/permissions", headers=hod_headers, json={"role": "ADMIN"})
        assert r.status_code == 400

    def test_hod_permissions_endpoint_does_not_expose_admin_role(self, client, hod_headers):
        r = client.get("/api/faculty/permissions", headers=hod_headers)
        assert r.status_code == 200
        roles = {p["role"] for p in r.json()["data"]["permissions"]}
        assert "ADMIN" not in roles
        assert "HOD" not in roles
        assert "FACULTY" in roles

    def test_hod_cannot_manage_admin_individual_permissions(self, client, hod_headers, db_available):
        import os, database
        admin_username = os.environ.get("TEST_ADMIN_USERNAME")
        if not admin_username:
            pytest.skip("TEST_ADMIN_USERNAME not set")
        with database.connect() as c:
            row = c.execute("SELECT username FROM users WHERE LOWER(username)=LOWER(%s) AND role='ADMIN'", (admin_username,)).fetchone()
        if not row:
            pytest.skip("Configured test admin does not exist")
        r = client.get(f"/api/faculty/accounts/{admin_username}/permissions", headers=hod_headers)
        assert r.status_code == 403

    def test_hod_faculty_page_has_no_admin_or_hod_rows(self, client, hod_headers):
        r = client.get("/api/faculty", headers=hod_headers)
        assert r.status_code == 200
        assert all(a["role"] == "FACULTY" for a in r.json()["data"]["accounts"])
