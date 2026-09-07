"""
Phase 2 — Subjects/Semesters (api/routes_subjects.py) + Academic Calendar
(api/routes_academic_calendar.py)

# — PROTECT: TestSubjectsAdminRoleGap below is the single most
important test in this file. ENDPOINTS.md §5 explicitly documents that
routes_subjects.py's _require_hod checks `role != "HOD"` with NO ADMIN
carve-out, unlike routes_faculty.py's `(HOD, ADMIN)`. If an ADMIN
account ever needs subject-management access, this is the line that
has to change — and if someone "fixes" it without meaning to (e.g. by
copy-pasting faculty.py's _require_hod over this one), this test will
also need updating. Until then, this test enforces the CURRENT
documented behavior, not a guess at intended behavior.
"""
import pytest


class TestSubjectsRBAC:
    def test_list_requires_auth(self, client):
        r = client.get("/api/subjects")
        assert r.status_code == 401

    def test_list_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/subjects", headers=faculty_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_list_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/subjects", headers=student_headers)
        assert r.status_code == 403

    def test_list_ok_for_hod(self, client, hod_headers):
        r = client.get("/api/subjects", headers=hod_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert "semesters" in data
        assert "grouped" in data
        assert "faculty" in data

    def test_create_forbidden_for_faculty(self, client, faculty_headers):
        r = client.post("/api/subjects", headers=faculty_headers, json={
            "semester_id": 1, "code": "ZZQA101", "name": "Probe Subject",
        })
        assert r.status_code == 403

    def test_delete_forbidden_for_faculty(self, client, faculty_headers):
        r = client.delete("/api/subjects/999999999", headers=faculty_headers)
        assert r.status_code == 403

    def test_assign_faculty_forbidden_for_faculty_role(self, client, faculty_headers):
        r = client.post("/api/subjects/999999999/assign-faculty", headers=faculty_headers,
                         json={"faculty_usernames": []})
        assert r.status_code == 403

    def test_semester_toggle_forbidden_for_faculty(self, client, faculty_headers):
        r = client.post("/api/semesters/999999999/toggle-active", headers=faculty_headers)
        assert r.status_code == 403


class TestSubjectsAdminRoleGap:
    """Documented drift (ENDPOINTS.md §5): unlike routes_faculty.py, this
    file's HOD check has no ADMIN carve-out. This test only runs if a
    real ADMIN-role test account is configured (optional — most
    deployments may not have a distinct ADMIN account at all, hence a
    separate opt-in credential rather than reusing TEST_HOD/FACULTY)."""

    @pytest.fixture(scope="class")
    def admin_headers(self, client):
        import os
        user = os.environ.get("TEST_ADMIN_USERNAME")
        pw = os.environ.get("TEST_ADMIN_PASSWORD")
        if not user or not pw:
            pytest.skip(
                "TEST_ADMIN_USERNAME/TEST_ADMIN_PASSWORD not set — skipping ADMIN-role "
                "drift check (optional; only relevant if this deployment uses a distinct ADMIN role)"
            )
        r = client.post("/api/auth/login", json={"username": user, "password": pw})
        assert r.status_code == 200, f"ADMIN login failed: {r.text}"
        token = r.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_admin_currently_forbidden_from_subjects_list(self, client, admin_headers):
        """As of this writing, an ADMIN account gets 403 here even though
        faculty.py treats ADMIN as HOD-equivalent everywhere else. This
        assertion documents CURRENT behavior — if Boss intentionally adds
        the ADMIN carve-out to subjects.py, update this test to expect 200
        alongside that change, don't just delete it."""
        r = client.get("/api/subjects", headers=admin_headers)
        assert r.status_code == 403, (
            "ADMIN can now access /api/subjects — routes_subjects.py's "
            "_require_hod was updated to include ADMIN. Update this test "
            "(and ENDPOINTS.md §5) to reflect the new intended behavior "
            "instead of treating this as a failure."
        )


class TestSubjectValidation:
    def test_create_missing_fields_returns_422(self, client, hod_headers):
        r = client.post("/api/subjects", headers=hod_headers, json={"semester_id": 1})
        assert r.status_code == 422

    def test_create_invalid_semester_rejected(self, client, hod_headers, run_tag):
        r = client.post("/api/subjects", headers=hod_headers, json={
            "semester_id": 999999999, "code": f"{run_tag}_X", "name": "ZZQA Probe Subject",
        })
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_toggle_active_nonexistent_subject_404s(self, client, hod_headers):
        r = client.post("/api/subjects/999999999/toggle-active", headers=hod_headers)
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_update_nonexistent_subject_rejected(self, client, hod_headers):
        r = client.patch("/api/subjects/999999999", headers=hod_headers, json={
            "code": "ZZQA999", "name": "Ghost Subject",
        })
        # — update_subject() raises ValueError for a missing row (VALIDATION_ERROR),
        # not a 404 — this file doesn't pre-check existence like toggle-active does.
        assert r.status_code in (400, 404)

    def test_semester_toggle_nonexistent_404s(self, client, hod_headers):
        r = client.post("/api/semesters/999999999/toggle-active", headers=hod_headers)
        assert r.status_code == 404


class TestSubjectDuplicateCode:
    """Uses a real semester (discovered, not guessed) to exercise the
    IntegrityError -> VALIDATION_ERROR path on a genuine duplicate-code
    conflict, then cleans up the created subject."""

    @pytest.fixture(scope="class")
    def real_semester_id(self, client, hod_headers):
        data = client.get("/api/subjects", headers=hod_headers).json()["data"]
        semesters = data.get("semesters") or data.get("all_semesters") or []
        if not semesters:
            pytest.skip("No semesters configured — cannot test subject creation")
        return semesters[0]["id"]

    def test_duplicate_subject_code_in_same_semester_rejected(self, client, hod_headers, real_semester_id, run_tag):
        code = f"{run_tag[:12]}DUP"
        payload = {"semester_id": real_semester_id, "code": code, "name": "ZZQA Duplicate Probe"}
        r1 = client.post("/api/subjects", headers=hod_headers, json=payload)
        assert r1.status_code == 201, f"Could not create initial subject for dup test: {r1.text}"
        try:
            r2 = client.post("/api/subjects", headers=hod_headers, json=payload)
            assert r2.status_code == 400
            assert r2.json()["error"]["code"] == "VALIDATION_ERROR"
        finally:
            # — best-effort cleanup: find and delete the subject we created
            data = client.get("/api/subjects", headers=hod_headers).json()["data"]
            for sem_code, subjects in data.get("grouped", {}).items():
                for s in subjects:
                    if s.get("code") == code:
                        client.delete(f"/api/subjects/{s['id']}", headers=hod_headers)


class TestAcademicCalendarRBAC:
    def test_get_requires_auth(self, client):
        r = client.get("/api/academic-calendar")
        assert r.status_code == 401

    def test_get_ok_for_all_roles(self, client, hod_headers, faculty_headers, student_headers):
        for headers, role in [(hod_headers, "HOD"), (faculty_headers, "FACULTY"), (student_headers, "STUDENT")]:
            r = client.get("/api/academic-calendar", headers=headers)
            assert r.status_code == 200, f"{role} should be able to view academic calendar"
            assert "can_edit" in r.json()["data"]

    def test_can_edit_flag_true_only_for_hod(self, client, hod_headers, faculty_headers, student_headers):
        hod_data = client.get("/api/academic-calendar", headers=hod_headers).json()["data"]
        fac_data = client.get("/api/academic-calendar", headers=faculty_headers).json()["data"]
        stu_data = client.get("/api/academic-calendar", headers=student_headers).json()["data"]
        assert hod_data["can_edit"] is True
        assert fac_data["can_edit"] is False
        assert stu_data["can_edit"] is False

    def test_upload_forbidden_for_faculty(self, client, faculty_headers):
        r = client.post(
            "/api/academic-calendar/1/upload/timetable",
            headers=faculty_headers,
            files={"file": ("probe.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert r.status_code == 403

    def test_upload_invalid_kind_rejected(self, client, hod_headers):
        r = client.post(
            "/api/academic-calendar/1/upload/not_a_real_kind",
            headers=hod_headers,
            files={"file": ("probe.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_upload_nonexistent_semester_404s(self, client, hod_headers):
        r = client.post(
            "/api/academic-calendar/999999999/upload/timetable",
            headers=hod_headers,
            files={"file": ("probe.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert r.status_code == 404

    def test_delete_invalid_kind_rejected(self, client, hod_headers):
        r = client.post("/api/academic-calendar/1/delete/bogus_kind", headers=hod_headers)
        assert r.status_code == 400

    def test_delete_forbidden_for_student(self, client, student_headers):
        r = client.post("/api/academic-calendar/1/delete/timetable", headers=student_headers)
        assert r.status_code == 403
