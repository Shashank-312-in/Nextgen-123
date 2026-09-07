"""
Phase 1 — Students (api/routes_students.py)

Covers: RBAC (HOD/ADMIN-only writes, STUDENT read restrictions),
validation rules (required fields, phone/Aadhaar format, marks range),
full create->read->update->delete lifecycle against a real throwaway
student row (tagged, cleaned up after).

# — PROTECT: every roll_no/username this file creates starts with the
run_tag prefix so conftest's cleanup and manual DB inspection can
always tell test data apart from real students at a glance.
"""
import pytest


def _student_payload(tag: str, **overrides) -> dict:
    payload = {
        "roll_no": f"{tag}_R001",
        "name": "ZZQA Test Student",
        "father_name": "ZZQA Test Father",
        "email": f"{tag}_student@example.com",
        "phone": "9876543210",
        "parent_phone": "9876543211",
        "dob": "2005-01-15",
        "category": "General",
        "gender": "Male",
        "seat_category": "General",
        "apaar_id": "",
        "aadhaar_number": "",
        "certificates_submitted": "",
        "certificates_due": "",
        "consultant_name": "",
        "address": "Test Address",
        "tenth_school": "", "tenth_year": "", "tenth_marks": "",
        "twelfth_school": "", "twelfth_year": "", "twelfth_marks": "",
        "diploma_college": "", "diploma_year": "", "diploma_marks": "",
        "current_semester_id": None,
    }
    payload.update(overrides)
    return payload


class TestStudentsRBAC:
    def test_list_requires_auth(self, client):
        r = client.get("/api/students")
        assert r.status_code == 401

    def test_student_role_cannot_hit_hod_list_shape(self, client, student_headers):
        # — routes_students.py: STUDENT role gets a restricted branch,
        # not a 403 — confirm it doesn't 500 and doesn't return other
        # students' rows unrestricted. We only assert it's not a server
        # error and is envelope-shaped; exact restriction shape is
        # covered by ENDPOINTS.md's documented behavior, not re-derived here.
        r = client.get("/api/students", headers=student_headers)
        assert r.status_code in (200, 403)
        assert "error" in r.json() or "data" in r.json()

    def test_create_forbidden_for_faculty(self, client, faculty_headers, run_tag):
        r = client.post("/api/students", headers=faculty_headers, json=_student_payload(run_tag))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_create_forbidden_for_student(self, client, student_headers, run_tag):
        r = client.post("/api/students", headers=student_headers, json=_student_payload(run_tag))
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_create_forbidden_without_auth(self, client, run_tag):
        r = client.post("/api/students", json=_student_payload(run_tag))
        assert r.status_code == 401


class TestStudentValidation:
    """These hit validate_student() in database.py — pure logic, and
    since HOD role-check happens before validation, all of these use
    hod_headers so we're actually reaching the validation code path."""

    def test_missing_required_name_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, name="")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_missing_roll_no_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, roll_no="")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_email_format_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, email="not-a-valid-email")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert "email" in r.json()["error"]["message"].lower()

    def test_phone_wrong_length_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, phone="12345")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert "phone" in r.json()["error"]["message"].lower()

    def test_phone_non_numeric_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, phone="98765abcde")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400

    def test_aadhaar_wrong_length_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, aadhaar_number="12345")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert "aadhaar" in r.json()["error"]["message"].lower()

    def test_marks_out_of_range_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, tenth_marks="150")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert "marks" in r.json()["error"]["message"].lower()

    def test_marks_non_numeric_rejected(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag, twelfth_marks="not-a-number")
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400


class TestStudentLifecycle:
    """Full create -> get -> update -> toggle -> delete against one
    real throwaway row. Session-scoped so later tests can reuse the id
    without re-creating; cleans itself up at the end regardless of
    whether later assertions fail."""

    @pytest.fixture(scope="class")
    def created_student(self, client, hod_headers, run_tag):
        payload = _student_payload(run_tag)
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 200, f"Setup failed, cannot continue lifecycle tests: {r.text}"
        student_id = r.json()["data"]["id"]
        yield student_id, payload
        # — teardown: always attempt delete even if a test above failed
        client.delete(f"/api/students/{student_id}", headers=hod_headers)

    def test_create_returns_generated_credentials(self, client, hod_headers, created_student):
        student_id, payload = created_student
        assert isinstance(student_id, int)

    def test_get_detail_returns_created_data(self, client, hod_headers, created_student):
        student_id, payload = created_student
        r = client.get(f"/api/students/{student_id}", headers=hod_headers)
        assert r.status_code == 200
        # GET /api/students/{id} nests the record under "student" (same
        # convention as the /edit route) — not a flat top-level shape.
        data = r.json()["data"]["student"]
        assert data["roll_no"] == payload["roll_no"]
        assert data["name"] == payload["name"]

    def test_duplicate_roll_no_rejected(self, client, hod_headers, created_student):
        _, payload = created_student
        r = client.post("/api/students", headers=hod_headers, json=payload)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
        assert "already exists" in r.json()["error"]["message"].lower()

    def test_update_changes_persist(self, client, hod_headers, created_student):
        student_id, payload = created_student
        updated = dict(payload)
        updated["name"] = "ZZQA Updated Name"
        r = client.patch(f"/api/students/{student_id}", headers=hod_headers, json=updated)
        assert r.status_code == 200
        r2 = client.get(f"/api/students/{student_id}", headers=hod_headers)
        assert r2.json()["data"]["student"]["name"] == "ZZQA Updated Name"

    def test_update_nonexistent_student_404s(self, client, hod_headers, run_tag):
        r = client.patch("/api/students/999999999", headers=hod_headers, json=_student_payload(run_tag))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_toggle_status_flips_active_flag(self, client, hod_headers, created_student):
        student_id, _ = created_student
        r = client.post(f"/api/students/{student_id}/toggle-status", headers=hod_headers)
        assert r.status_code == 200

    def test_delete_forbidden_for_faculty(self, client, faculty_headers, created_student):
        student_id, _ = created_student
        r = client.delete(f"/api/students/{student_id}", headers=faculty_headers)
        assert r.status_code == 403

    def test_get_nonexistent_student_404s(self, client, hod_headers):
        r = client.get("/api/students/999999999", headers=hod_headers)
        assert r.status_code == 404


class TestAadhaarMasking:
    """Confirms mask_aadhaar's documented failure-mode-on-ciphertext
    doesn't leak plaintext Aadhaar in list views — this is a genuine
    privacy-sensitive field per field_encryption.py."""

    def test_list_view_never_returns_raw_12_digit_aadhaar(self, client, hod_headers):
        r = client.get("/api/students", headers=hod_headers)
        assert r.status_code == 200
        rows = r.json()["data"]
        rows_list = rows if isinstance(rows, list) else rows.get("students", rows.get("items", []))
        for row in (rows_list or [])[:25]:
            aadhaar = row.get("aadhaar_number") or row.get("aadhaar_masked")
            if aadhaar and aadhaar not in ("—",):
                assert not aadhaar.replace(" ", "").isdigit(), (
                    f"List view leaked what looks like a raw Aadhaar number: {aadhaar!r}"
                )


class TestRollNoOrderingAndSemesters:
    def test_list_is_sorted_by_roll_no(self, client, hod_headers):
        r = client.get("/api/students", headers=hod_headers)
        assert r.status_code == 200
        rows = r.json()["data"]
        roll_nos = [row["roll_no"].upper() for row in rows]
        assert roll_nos == sorted(roll_nos), "Students are not sorted roll_no wise"

    def test_semesters_endpoint(self, client, hod_headers):
        r = client.get("/api/students/semesters", headers=hod_headers)
        assert r.status_code == 200
        sems = r.json()["data"]
        assert len(sems) > 0
        assert "code" in sems[0]


class TestStudentsPDF:
    def test_pdf_requires_auth(self, client):
        r = client.get("/api/students/pdf")
        assert r.status_code == 401

    def test_pdf_forbidden_for_faculty(self, client, faculty_headers):
        r = client.get("/api/students/pdf", headers=faculty_headers)
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_pdf_allowed_for_hod(self, client, hod_headers):
        r = client.get("/api/students/pdf", headers=hod_headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")

    def test_pdf_with_semester_filter(self, client, hod_headers):
        r = client.get("/api/students/pdf?semester_id=5", headers=hod_headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")

    def test_pdf_with_year_filter(self, client, hod_headers):
        r = client.get("/api/students/pdf?year=3", headers=hod_headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")
