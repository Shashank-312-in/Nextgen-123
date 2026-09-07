"""
Phase 2 — Protected Files (api/routes_files.py) + Problem Reports
(api/routes_reports.py)

# — PROTECT: TestPathTraversal below is a genuine security test, not
just a coverage checkbox. api/routes_files.py's docstring calls this
route "the ONLY way to reach uploaded files" specifically because a
prior version of this app had a public static mount as a documented
data-exposure gap (§7.7). If traversal ever works again, that gap is
back.
"""
import pytest


class TestFilesRBAC:
    def test_requires_auth(self, client):
        r = client.get("/api/files/students/anything.jpg")
        assert r.status_code == 401

    def test_unknown_subdir_denied_even_for_hod(self, client, hod_headers):
        # — default-deny for unrecognized subdirs applies regardless of
        # role per _authorize()'s fallthrough; HOD/FACULTY get an early
        # return only for their own branch, but a nonexistent FILE still
        # 404s before _authorize is ever reached for a fake path — so we
        # assert "not literally 200/500", both 403 and 404 are acceptable
        # outcomes for a file that doesn't exist in an unknown subdir.
        r = client.get("/api/files/totally_unknown_subdir/probe.jpg", headers=hod_headers)
        assert r.status_code in (403, 404)

    def test_certificates_denied_for_staff_without_own_file(self, client, student_headers):
        # — STUDENT hitting a certificates file that isn't theirs (wrong
        # roll-no prefix) must be denied, not served.
        r = client.get("/api/files/certificates/OTHERROLL-cert.pdf", headers=student_headers)
        assert r.status_code in (403, 404)


class TestPathTraversal:
    """Confirms the .resolve()-based membership check actually blocks
    traversal attempts, using several encodings an attacker might try."""

    @pytest.mark.parametrize("attempt", [
        "..%2F..%2F..%2Fetc%2Fpasswd",
        "....//....//etc/passwd",
    ])
    def test_encoded_traversal_in_filename_blocked(self, client, hod_headers, attempt):
        r = client.get(f"/api/files/students/{attempt}", headers=hod_headers)
        # — Must never be 200: either FastAPI's own routing rejects the
        # malformed path (404/422) or _authorize/the resolve() guard
        # catches it (403/404). A 200 here would mean traversal succeeded.
        assert r.status_code != 200

    def test_dotdot_subdir_blocked(self, client, hod_headers):
        r = client.get("/api/files/../../../etc/passwd", headers=hod_headers)
        assert r.status_code != 200

    def test_plain_dotdot_in_filename_blocked(self, client, hod_headers):
        r = client.get("/api/files/students/..%2Fapp.py", headers=hod_headers)
        assert r.status_code != 200


class TestFilesNotFound:
    def test_nonexistent_file_404s_not_500(self, client, hod_headers):
        r = client.get("/api/files/students/zzqa_definitely_does_not_exist.jpg", headers=hod_headers)
        assert r.status_code == 404


class TestReportsRBAC:
    def test_submit_requires_auth(self, client):
        r = client.post("/api/reports/submit", json={"subject": "test", "description": "test"})
        assert r.status_code == 401

    def test_list_requires_auth(self, client):
        r = client.get("/api/reports")
        assert r.status_code == 401

    def test_list_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/reports", headers=faculty_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_list_forbidden_for_student(self, client, student_headers):
        r = client.get("/api/reports", headers=student_headers)
        assert r.status_code == 403

    def test_list_ok_for_hod(self, client, hod_headers):
        r = client.get("/api/reports", headers=hod_headers)
        assert r.status_code == 200
        assert "reports" in r.json()["data"]

    def test_update_status_forbidden_for_student(self, client, student_headers):
        r = client.patch("/api/reports/1/status", headers=student_headers, json={"status": "Resolved"})
        assert r.status_code == 403


class TestReportSubmitAndLifecycle:
    """Any authenticated role can submit — this is the one write path in
    this file that's safe to fully exercise (reports are meant to
    accumulate; HOD reviewing/resolving one we created is itself a
    realistic lifecycle test, not a side effect to avoid)."""

    def test_submit_by_student_succeeds(self, client, student_headers, run_tag):
        r = client.post("/api/reports/submit", headers=student_headers, json={
            "category": "General",
            "subject": f"ZZQA automated test report {run_tag}",
            "description": "Created by automated test suite — safe to mark Resolved/ignore.",
        })
        assert r.status_code == 201
        assert "message" in r.json()["data"]

    def test_submit_missing_required_fields_returns_422(self, client, student_headers):
        r = client.post("/api/reports/submit", headers=student_headers, json={"category": "General"})
        assert r.status_code == 422

    def test_hod_sees_submitted_report_and_can_update_status(self, client, hod_headers, student_headers, run_tag):
        marker = f"ZZQA lifecycle probe {run_tag}"
        submit = client.post("/api/reports/submit", headers=student_headers, json={
            "category": "General", "subject": marker, "description": "lifecycle test",
        })
        assert submit.status_code == 201

        listing = client.get("/api/reports", headers=hod_headers).json()["data"]["reports"]
        match = next((r for r in listing if r.get("subject") == marker), None)
        assert match is not None, "HOD's report list did not include the report just submitted"

        update = client.patch(f"/api/reports/{match['id']}/status", headers=hod_headers, json={
            "status": "Resolved", "admin_notes": "Closed by automated test suite.",
        })
        assert update.status_code == 200

    def test_update_status_nonexistent_report_rejected(self, client, hod_headers):
        r = client.patch("/api/reports/999999999/status", headers=hod_headers, json={"status": "Resolved"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
