"""Group 4 — Students API (§7.4).

Source: webapp/routes/students.py — ported to JSON API shape.
Backend for StudentsListPage, StudentFormPage, StudentViewPage which already exist
in frontend/src/pages/students/ and call through frontend/src/api/students.ts.
"""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from openpyxl import load_workbook
try:
    import xlrd
except ImportError:  # optional until a legacy .xls file is uploaded
    xlrd = None

from database import (
    audit, connect, ensure_student_login, mask_aadhaar, DEPARTMENTS,
    validate_student, IntegrityError,
)
from field_encryption import decrypt_field, encrypt_field
from sms_app.services.attendance_service import list_semesters
from sms_app.services.student_pdf import build_students_list_pdf
from webapp.photo_upload import PhotoUploadError, save_profile_photo

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok
from excel_import import FieldSpec, match_headers, normalize_header

router = APIRouter(prefix="/api/students", tags=["students"])

FIELD_SPECS = [
    ("Roll Number", "roll_no"), ("Full Name", "name"), ("Father Name", "father_name"),
    ("Email", "email"), ("Student Phone Number", "phone"), ("Parent Phone Number", "parent_phone"),
    ("Date of Birth (YYYY-MM-DD)", "dob"),
    ("Category", "category"), ("Gender", "gender"), ("Seat Category", "seat_category"),
    ("APAAR ID", "apaar_id"), ("Aadhaar Number", "aadhaar_number"),
    ("Certificates Submitted", "certificates_submitted"), ("Certificates Due", "certificates_due"),
    ("Consultant Name", "consultant_name"), ("Address", "address"),
]

EDUCATION_SPECS = [
    ("10th School Name", "tenth_school"), ("10th Year of Passing", "tenth_year"), ("10th Marks (%)", "tenth_marks"),
    ("12th / Junior College Name", "twelfth_school"), ("12th Year of Passing", "twelfth_year"), ("12th Marks (%)", "twelfth_marks"),
    ("Diploma College Name (if applicable)", "diploma_college"), ("Diploma Year of Passing", "diploma_year"), ("Diploma Marks (%)", "diploma_marks"),
]


def _decrypt_row(row) -> dict:
    """Return a dict with aadhaar_number/apaar_id decrypted.
    Row dictionary is immutable — must copy to dict first.
    """
    if row is None:
        return None
    d = dict(row)
    d["aadhaar_number"] = decrypt_field(d.get("aadhaar_number"))
    d["apaar_id"] = decrypt_field(d.get("apaar_id"))
    return d


SEMESTER_YEAR_BY_ID = {
    1: 1, 2: 1,
    3: 2, 4: 2,
    5: 3, 6: 3,
    7: 4, 8: 4,
}
SEMESTER_YEAR_LABELS = {1: "1st Year", 2: "2nd Year", 3: "3rd Year", 4: "4th Year"}


def _academic_year_start(reference_date: datetime | None = None) -> int:
    """Return the academic-year start year used for cohort calculations.

    The college cycle is treated as June→May. September 2026 therefore
    belongs to academic year 2026-27; January–May belongs to the previous
    academic-year start.
    """
    today = reference_date or datetime.now()
    return today.year if today.month >= 6 else today.year - 1


def _year_number_from_semester_id(semester_id: int | None) -> int | None:
    """Return the year-of-study represented by the selected semester.

    This is the sole source of truth for displayed year/batch. Roll-number
    prefixes are intentionally ignored because lateral-entry and legacy roll
    numbering can encode a different cohort than the student's current class.
    """
    if semester_id is None:
        return None
    try:
        return SEMESTER_YEAR_BY_ID.get(int(semester_id))
    except (TypeError, ValueError):
        return None


def _compute_year_and_batch(d: dict, reference_date: datetime | None = None) -> tuple[str, str]:
    """Derive year of study and batch from the student's current semester only.

    Example for academic year 2026-27:
      III-I / III-II -> 3rd Year -> 2024-2028 Batch
      II-I / II-II   -> 2nd Year -> 2025-2029 Batch

    The roll number is deliberately not consulted. This keeps lateral-entry
    and non-standard roll formats from being misclassified.
    """
    semester_year = _year_number_from_semester_id(d.get("current_semester_id"))
    if not semester_year:
        return "", ""

    academic_start = _academic_year_start(reference_date)
    joining_year = academic_start - semester_year + 1
    return SEMESTER_YEAR_LABELS[semester_year], f"{joining_year}-{joining_year + 4} Batch"


def _validate_semester_selection(c, semester_id: int | None) -> None:
    """Validate that the selected current semester exists.

    There is intentionally no roll-number/cohort consistency check here:
    the selected semester is authoritative for current year and batch.
    """
    if semester_id is None:
        return
    sem = c.execute("SELECT id FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()
    if not sem:
        raise ValueError("Selected semester does not exist")


def _enforce_semester_year_filter(rows: list[dict], semester_id: int | None) -> list[dict]:
    """Defensive read-side fence: a semester can only show its own year.

    Year is already derived from the semester in _compute_year_and_batch, so
    this is mainly a guard against malformed API rows or future regressions.
    """
    semester_year = _year_number_from_semester_id(semester_id)
    if not semester_year:
        return rows
    expected_label = SEMESTER_YEAR_LABELS[semester_year]
    return [row for row in rows if row.get("year_of_study") == expected_label]


def _serialize_list_row(row) -> dict:
    """For the list endpoint — decrypt then mask aadhaar."""
    d = _decrypt_row(row)
    year, batch = _compute_year_and_batch(d)
    return {
        "id": d["id"],
        "roll_no": d["roll_no"],
        "name": d["name"],
        "email": d.get("email") or "",
        "phone": d.get("phone") or "",
        "parent_phone": d.get("parent_phone") or "",
        "gender": d.get("gender") or "",
        "category": d.get("category") or "",
        "seat_category": d.get("seat_category") or "",
        "current_semester_id": d.get("current_semester_id"),
        "aadhaar_masked": mask_aadhaar(d.get("aadhaar_number")),
        "year_of_study": year,
        "batch": batch,
        "active": bool(d["active"]),
        "photo_path": d.get("photo_path"),
    }


def _serialize_full(row) -> dict:
    """Full student record — aadhaar_number/apaar_id returned decrypted."""
    d = _decrypt_row(row)
    year, batch = _compute_year_and_batch(d)
    res = {k: (d.get(k) or "") if isinstance(d.get(k), str) or d.get(k) is None else d[k]
           for k in d if k not in ("password",)}
    res["year_of_study"] = year
    res["batch"] = batch
    return res


def _get_user_hod_username(username: str) -> str | None:
    with connect() as c:
        row = c.execute("SELECT role, hod_username, department FROM users WHERE username=%s", (username,)).fetchone()
        if not row:
            return None
        if row["role"] == "HOD":
            return username
        if row.get("hod_username"):
            return row["hod_username"]
        from database import resolve_hod_for_department
        dept_hod = resolve_hod_for_department(c, row.get("department") or "CSD")
        return dept_hod or row.get("hod_username") or username


def _resolve_hod_for_student(user: CurrentUser, requested: str | None = None) -> str:
    if user.role == "HOD":
        return user.username
    candidate = (requested or "").strip()
    with connect() as c:
        if candidate:
            row = c.execute("SELECT username FROM users WHERE username=%s AND role='HOD' AND active=1", (candidate,)).fetchone()
            if not row:
                raise ApiError("Selected HOD is not an active HOD account", 400, "VALIDATION_ERROR")
            return candidate
        from database import resolve_hod_for_department
        dept_hod = resolve_hod_for_department(c, "CSD")
        if dept_hod:
            return dept_hod
    return user.username


def _student_scope_sql(user: CurrentUser) -> tuple[str, list[Any]]:
    if user.role == "ADMIN" or user.username == "admin":
        return "", []
    hod = user.username if user.role == "HOD" else _get_user_hod_username(user.username)
    if hod:
        return " AND (hod_username=? OR hod_username IS NULL)", [hod]
    return " AND 1=0", []


def _student_search_sql(q: str) -> tuple[str, list[Any]]:
    """Build the deliberately narrow student-list search predicate.

    Supported search targets are only:
      * name: partial text match
      * roll number: exact match, or a suffix match using the last 1–4
        digits entered by the user
      * phone: exact match only for a 10-digit number

    Email and parent phone are intentionally excluded. A numeric query of
    1–4 digits is interpreted as a roll-number suffix; a 10-digit numeric
    query is an exact student-phone lookup. Other non-empty queries are
    treated as name text plus exact roll-number lookup, which lets a full
    alphanumeric roll number work without making arbitrary partial roll
    searches possible.
    """
    value = str(q or "").strip()
    if not value:
        return "", []

    if value.isdigit():
        if 1 <= len(value) <= 4:
            return " AND RIGHT(roll_no, ?) = ?", [len(value), value]
        if len(value) == 10:
            return " AND phone = ?", [value]
        return " AND UPPER(roll_no) = UPPER(?)", [value]

    like = f"%{value}%"
    return " AND (name LIKE ? OR UPPER(roll_no) = UPPER(?))", [like, value]


@router.get("/semesters")
async def student_semesters(user: CurrentUser = Depends(get_current_user)):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    semesters = [dict(s) for s in list_semesters()]
    return ok(semesters)


@router.get("")
async def students_list(
    q: str = "",
    status: str = "Active",
    semester_id: int | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    sql = "SELECT * FROM students WHERE department='CSD'"
    args: list[Any] = []
    search_sql, search_args = _student_search_sql(q)
    sql += search_sql
    args.extend(search_args)
    scope_sql, scope_args = _student_scope_sql(user)
    sql += scope_sql
    args.extend(scope_args)
    if status != "All":
        sql += " AND active=?"
        args.append(1 if status == "Active" else 0)
    if semester_id:
        sql += " AND current_semester_id=?"
        args.append(semester_id)
    sql += " ORDER BY UPPER(roll_no) ASC, name ASC"
    with connect() as c:
        rows = c.execute(sql, args).fetchall()
    serialized = [_serialize_list_row(r) for r in rows]
    # Keep legacy/stale rows from leaking into an impossible year/semester
    # combination. The underlying record is still caught by write-time
    # validation, but list views must remain logically correct even before
    # old data is repaired.
    serialized = _enforce_semester_year_filter(serialized, semester_id)
    return ok(serialized)


@router.get("/pdf")
async def students_pdf(
    q: str = "",
    status: str = "Active",
    semester_id: int | None = None,
    year: str | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    """Generates official ReportLab PDF for the student list / nominal roll.
    Strictly restricted to HOD and ADMIN roles.
    """
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")

    sql = "SELECT * FROM students WHERE department='CSD'"
    args: list[Any] = []
    search_sql, search_args = _student_search_sql(q)
    sql += search_sql
    args.extend(search_args)
    scope_sql, scope_args = _student_scope_sql(user)
    sql += scope_sql
    args.extend(scope_args)

    if status != "All":
        sql += " AND active=?"
        args.append(1 if status == "Active" else 0)
    if semester_id:
        sql += " AND current_semester_id=?"
        args.append(semester_id)

    sql += " ORDER BY UPPER(roll_no) ASC, name ASC"

    with connect() as c:
        rows = c.execute(sql, args).fetchall()
        sem_row = None
        if semester_id:
            sem_row = c.execute("SELECT code, name FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()

    serialized = [_serialize_list_row(r) for r in rows]
    serialized = _enforce_semester_year_filter(serialized, semester_id)

    YEAR_LABELS = {"1": "1st Year", "2": "2nd Year", "3": "3rd Year", "4": "4th Year"}
    if year and year in YEAR_LABELS:
        serialized = [r for r in serialized if r.get("year_of_study") == YEAR_LABELS[year]]

    if sem_row:
        semester_name = f"{sem_row['name']} ({sem_row['code']})"
    elif semester_id:
        semester_name = f"Semester {semester_id}"
    elif year and year in YEAR_LABELS:
        semester_name = f"{YEAR_LABELS[year]} (All Semesters)"
    else:
        semester_name = "All Semesters"

    batches = {r.get("batch") for r in serialized if r.get("batch")}
    if len(batches) == 1:
        batch_name = list(batches)[0]
    elif len(batches) > 1:
        batch_name = ", ".join(sorted(batches))
    else:
        batch_name = "All Batches"

    now_str = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    meta = {
        "semester_name": semester_name,
        "batch": batch_name,
        "total_students": len(serialized),
        "generated_on": now_str,
        "generated_by": "NextGen SMS",
        "department": "CSE (DATA SCIENCE)",
    }

    pdf_bytes = build_students_list_pdf(serialized, meta)

    clean_sem = (sem_row["code"] if sem_row else (f"Year_{year}" if year else "All_Semesters")).replace(" ", "_").replace("/", "-")
    filename = f"Student_List_{clean_sem}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/new")
async def student_new(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD access only", 403, "FORBIDDEN")
    semesters = [dict(s) for s in list_semesters()]
    return ok({"student": None, "semesters": semesters})


@router.get("/{student_id}/edit")
async def student_edit_data(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD access only", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            hod = _get_user_hod_username(user.username)
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, hod)).fetchone() if hod else None
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    # CORRUPTION TRAP: must decrypt before returning — see §4.4 and webapp/routes/students.py
    student = _serialize_full(row)
    semesters = [dict(s) for s in list_semesters()]
    return ok({"student": student, "semesters": semesters})


@router.get("/{student_id}/track-record")
async def student_track_record(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            hod = _get_user_hod_username(user.username)
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, hod)).fetchone() if hod else None
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        student = _serialize_full(row)
        semester_rows = c.execute("SELECT id, code, name FROM academic_semesters ORDER BY sort_order, id").fetchall()
        attendance_rows = c.execute("""
            SELECT a.semester_id,
                   COUNT(DISTINCT r.session_id) AS total_classes,
                   SUM(CASE WHEN r.status='Present' THEN 1 ELSE 0 END) AS present_classes
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            WHERE r.roll_no=%s
            GROUP BY a.semester_id
        """, (row["roll_no"],)).fetchall()

    from sms_app.services.attendance_service import attendance_pct_band
    attendance_by_semester = {}
    for ar in attendance_rows:
        total = int(ar.get("total_classes") or 0)
        present = int(ar.get("present_classes") or 0)
        pct, band = attendance_pct_band(present, total)
        attendance_by_semester[int(ar["semester_id"])] = {
            "total_classes": total,
            "present_classes": present,
            "absent_classes": total - present,
            "pct": pct,
            "band": band,
        }

    from sms_app.services.learning_service import get_student_results
    results = get_student_results(roll_no=row["roll_no"])
    return ok({
        "student": student,
        "current_semester_id": row.get("current_semester_id"),
        "semesters": [dict(s) for s in semester_rows],
        "attendance_by_semester": attendance_by_semester,
        "results": results.get("results", []),
    })


@router.get("/{student_id}/track-record/{semester_id}")
async def student_track_record_semester(student_id: int, semester_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            hod = _get_user_hod_username(user.username)
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, hod)).fetchone() if hod else None
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        semester = c.execute("SELECT id, code, name FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()
        if not semester:
            raise ApiError("Semester not found", 404, "NOT_FOUND")
        student = _serialize_full(row)

    from sms_app.services.attendance_service import student_subject_attendance_for_semester, attendance_pct_band
    att_rows = student_subject_attendance_for_semester(row["roll_no"], semester_id)
    subjects_attendance = []
    total_classes = 0
    total_present = 0
    for ar in att_rows:
        pres = int(ar["present_sessions"] or 0)
        tot = int(ar["total_sessions"] or 0)
        pct, band = attendance_pct_band(pres, tot)
        total_classes += tot
        total_present += pres
        subjects_attendance.append({
            "subject_id": ar["subject_id"],
            "subject_code": ar["subject_code"],
            "subject_name": ar["subject_name"],
            "present_sessions": pres,
            "total_sessions": tot,
            "absent_sessions": tot - pres,
            "pct": pct,
            "band": band,
        })
    overall_pct, overall_band = attendance_pct_band(total_present, total_classes)

    from sms_app.services.learning_service import get_student_results
    all_results = get_student_results(roll_no=row["roll_no"]).get("results", [])
    # get_student_results doesn't echo semester_id on batch — match by the
    # semester code instead, which it does return.
    semester_result = next((r for r in all_results if r["batch"]["semester_code"] == semester["code"]), None)

    return ok({
        "student": student,
        "semester": dict(semester),
        "attendance": {
            "subjects": subjects_attendance,
            "total_classes": total_classes,
            "total_present": total_present,
            "total_absent": total_classes - total_present,
            "overall_pct": overall_pct,
            "overall_band": overall_band,
        },
        "result": semester_result,
    })


@router.get("/{student_id}")
async def student_view(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            hod = _get_user_hod_username(user.username)
            row = c.execute("SELECT * FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, hod)).fetchone() if hod else None
        semester = None
        if row and row["current_semester_id"]:
            sem_row = c.execute(
                "SELECT code, name FROM academic_semesters WHERE id=?",
                (row["current_semester_id"],)
            ).fetchone()
            if sem_row:
                semester = dict(sem_row)
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    # HOD detail view — aadhaar returned decrypted (§4.4 exception)
    student = _serialize_full(row)

    # Subject-wise attendance calculation
    from sms_app.services.attendance_service import student_subject_attendance, attendance_pct_band
    att_rows = student_subject_attendance(row["roll_no"])
    subjects_attendance = []
    total_classes = 0
    total_present = 0
    for ar in att_rows:
        pct, band = attendance_pct_band(ar["present_sessions"], ar["total_sessions"])
        pres = int(ar["present_sessions"] or 0)
        tot = int(ar["total_sessions"] or 0)
        total_classes += tot
        total_present += pres
        subjects_attendance.append({
            "subject_id": ar["subject_id"],
            "subject_code": ar["subject_code"],
            "subject_name": ar["subject_name"],
            "present_sessions": pres,
            "total_sessions": tot,
            "absent_sessions": tot - pres,
            "pct": pct,
            "band": band,
        })
    overall_pct, overall_band = attendance_pct_band(total_present, total_classes)
    attendance_summary = {
        "subjects": subjects_attendance,
        "total_classes": total_classes,
        "total_present": total_present,
        "total_absent": total_classes - total_present,
        "overall_pct": overall_pct,
        "overall_band": overall_band,
    }

    return ok({"student": student, "semester": semester, "attendance": attendance_summary})


@router.get("/{student_id}/attendance")
async def student_attendance(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role == "STUDENT":
        raise ApiError("Access denied", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT roll_no, name FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT roll_no, name FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            hod = _get_user_hod_username(user.username)
            row = c.execute("SELECT roll_no, name FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, hod)).fetchone() if hod else None
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")

    from sms_app.services.attendance_service import student_subject_attendance, attendance_pct_band, student_subject_session_history
    att_rows = student_subject_attendance(row["roll_no"])
    subjects_attendance = []
    total_classes = 0
    total_present = 0
    for ar in att_rows:
        pct, band = attendance_pct_band(ar["present_sessions"], ar["total_sessions"])
        pres = int(ar["present_sessions"] or 0)
        tot = int(ar["total_sessions"] or 0)
        total_classes += tot
        total_present += pres
        history = student_subject_session_history(row["roll_no"], ar["subject_id"])
        subjects_attendance.append({
            "subject_id": ar["subject_id"],
            "subject_code": ar["subject_code"],
            "subject_name": ar["subject_name"],
            "present_sessions": pres,
            "total_sessions": tot,
            "absent_sessions": tot - pres,
            "pct": pct,
            "band": band,
            "sessions": [
                {
                    "attendance_date": h["attendance_date"],
                    "session_type": h["session_type"],
                    "duration_hours": h["duration_hours"],
                    "status": h["status"],
                }
                for h in history
            ],
        })
    overall_pct, overall_band = attendance_pct_band(total_present, total_classes)
    return ok({
        "roll_no": row["roll_no"],
        "name": row["name"],
        "total_classes": total_classes,
        "total_present": total_present,
        "total_absent": total_classes - total_present,
        "overall_pct": overall_pct,
        "overall_band": overall_band,
        "subjects": subjects_attendance,
    })


def _clean_str(val: str | None) -> str:
    return (val or "").strip()


def _cell_to_str(val: Any) -> str:
    """openpyxl hands back int/float for numeric-looking cells (very
    common for Aadhaar/phone columns unless the column was explicitly
    Text-formatted in Excel) — str(123456789012.0) is '123456789012.0',
    which breaks validate_student's exact-digit-count checks. Strip a
    trailing '.0' from whole-number floats; everything else -> plain str."""
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


class StudentBody(BaseModel):
    roll_no: str | None = ""
    name: str | None = ""
    father_name: str | None = ""
    email: str | None = ""
    phone: str | None = ""
    parent_phone: str | None = ""
    dob: str | None = ""
    category: str | None = ""
    gender: str | None = ""
    seat_category: str | None = ""
    apaar_id: str | None = ""
    aadhaar_number: str | None = ""
    certificates_submitted: str | None = ""
    certificates_due: str | None = ""
    consultant_name: str | None = ""
    address: str | None = ""
    tenth_school: str | None = ""
    tenth_year: str | None = ""
    tenth_marks: str | None = ""
    twelfth_school: str | None = ""
    twelfth_year: str | None = ""
    twelfth_marks: str | None = ""
    diploma_college: str | None = ""
    diploma_year: str | None = ""
    diploma_marks: str | None = ""
    current_semester_id: int | None = None
    hod_username: str | None = None


def _body_to_data(body: StudentBody) -> dict:
    return {
        "roll_no": _clean_str(body.roll_no),
        "name": _clean_str(body.name),
        "department": "CSD",
        "email": _clean_str(body.email),
        "phone": _clean_str(body.phone),
        "parent_phone": _clean_str(body.parent_phone),
        "dob": _clean_str(body.dob),
        "address": _clean_str(body.address),
        "father_name": _clean_str(body.father_name),
        "category": _clean_str(body.category),
        "gender": _clean_str(body.gender),
        "seat_category": _clean_str(body.seat_category),
        "apaar_id": _clean_str(body.apaar_id),
        "aadhaar_number": _clean_str(body.aadhaar_number),
        "certificates_submitted": _clean_str(body.certificates_submitted),
        "certificates_due": _clean_str(body.certificates_due),
        "consultant_name": _clean_str(body.consultant_name),
        "tenth_school": _clean_str(body.tenth_school),
        "tenth_year": _clean_str(body.tenth_year),
        "tenth_marks": _clean_str(body.tenth_marks),
        "twelfth_school": _clean_str(body.twelfth_school),
        "twelfth_year": _clean_str(body.twelfth_year),
        "twelfth_marks": _clean_str(body.twelfth_marks),
        "diploma_college": _clean_str(body.diploma_college),
        "diploma_year": _clean_str(body.diploma_year),
        "diploma_marks": _clean_str(body.diploma_marks),
    }


STUDENT_DB_KEYS = [
    "roll_no", "name", "department", "email", "phone", "parent_phone", "dob", "address",
    "father_name", "category", "gender", "seat_category", "apaar_id", "aadhaar_number",
    "certificates_submitted", "certificates_due", "consultant_name",
    "tenth_school", "tenth_year", "tenth_marks",
    "twelfth_school", "twelfth_year", "twelfth_marks",
    "diploma_college", "diploma_year", "diploma_marks", "batch",
]


@router.post("")
async def student_create(body: StudentBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    data = _body_to_data(body)
    assigned_hod = _resolve_hod_for_student(user, body.hod_username)
    try:
        validate_student(data)
        if data["dob"]:
            datetime.strptime(data["dob"], "%Y-%m-%d")
        with connect() as c:
            _validate_semester_selection(c, body.current_semester_id)
            data["batch"] = _compute_year_and_batch({**data, "current_semester_id": body.current_semester_id})[1].removesuffix(" Batch")
            # Encrypt AFTER validation — §4.4 ordering requirement
            data["aadhaar_number"] = encrypt_field(data["aadhaar_number"])
            data["apaar_id"] = encrypt_field(data["apaar_id"])
            c.execute(
                """INSERT INTO students(roll_no,name,department,email,phone,parent_phone,dob,address,father_name,
                   category,gender,seat_category,apaar_id,aadhaar_number,
                   certificates_submitted,certificates_due,consultant_name,
                   tenth_school,tenth_year,tenth_marks,twelfth_school,twelfth_year,twelfth_marks,
                   diploma_college,diploma_year,diploma_marks,batch,current_semester_id,hod_username)
                   VALUES(?,?,?,NULLIF(?,''),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*[data[k] for k in STUDENT_DB_KEYS], body.current_semester_id, assigned_hod),
            )
            audit(c, user.username, "CREATE", "student", data["roll_no"])
            # Seed checklist — §7.4
            for item, st in [("Personal details", "Complete"), ("Documents", "Pending"),
                              ("ID card", "Pending"), ("Fees", "Pending"),
                              ("Attendance records", "Available"), ("Marks records", "Available")]:
                c.execute("INSERT IGNORE INTO checklist(roll_no,item,status) VALUES(?,?,?)",
                          (data["roll_no"], item, st))
            new_id = c.execute("SELECT id FROM students WHERE roll_no=?", (data["roll_no"],)).fetchone()["id"]
        username, password = ensure_student_login(data["roll_no"], user.username)
        return ok({"id": new_id, "created_credentials": {"username": username, "password": password}})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")
    except IntegrityError as e:
        raise ApiError("A student with that roll number or email already exists", 400, "VALIDATION_ERROR")


# — Bulk Import (Excel) —
# Column headers are matched case-insensitively with whitespace collapsed.
# "Previous Roll Number" is an optional stable key for changing a student's
# roll number during an update. Unknown columns are safely ignored.
BULK_IMPORT_COLUMN_MAP = {
    "full name of the student": "name",
    "full name of the student (as per ssc)": "name",
    "name": "name",
    "student name": "name",
    "hallticket": "roll_no",
    "hall ticket": "roll_no",
    "roll no": "roll_no",
    "roll number": "roll_no",
    "phone no": "phone",
    "student phone number": "phone",
    "student email id": "email",
    "email": "email",
    "address of the student": "address",
    "address": "address",
    "aadhaar number": "aadhaar_number",
    "father's name": "father_name",
    "father's phone number": "parent_phone",
    "parent phone number": "parent_phone",
    "parent phone": "parent_phone",
    "parent mobile": "parent_phone",
    "date of birth (yyyy-mm-dd)": "dob",
    "date of birth": "dob",
    "category": "category",
    "gender": "gender",
    "seat category": "seat_category",
    "apaar id": "apaar_id",
    "certificates submitted": "certificates_submitted",
    "certificates due": "certificates_due",
    "consultant name": "consultant_name",
    "10th school name": "tenth_school",
    "10th year of passing": "tenth_year",
    "10th marks (%)": "tenth_marks",
    "12th / junior college name": "twelfth_school",
    "12th year of passing": "twelfth_year",
    "12th marks (%)": "twelfth_marks",
    "diploma college name (if applicable)": "diploma_college",
    "diploma year of passing": "diploma_year",
    "diploma marks (%)": "diploma_marks",
    # Explicit stable-key aliases for roll-number changes.
    "previous roll number": "match_roll_no",
    "old roll number": "match_roll_no",
    "existing roll number": "match_roll_no",
    "previous hallticket": "match_roll_no",
    "old hallticket": "match_roll_no",
    "existing hallticket": "match_roll_no",
}

IMPORT_FIELD_KEYS = [
    "roll_no", "name", "email", "phone", "parent_phone", "dob", "address", "father_name",
    "category", "gender", "seat_category", "apaar_id", "aadhaar_number",
    "certificates_submitted", "certificates_due", "consultant_name",
    "tenth_school", "tenth_year", "tenth_marks", "twelfth_school", "twelfth_year",
    "twelfth_marks", "diploma_college", "diploma_year", "diploma_marks",
]

# — Bulk Import Field Specs —
# WHY: built from BULK_IMPORT_COLUMN_MAP so every alias anyone already
# relied on keeps working as an exact match, while match_headers() (see
# excel_import.py) adds a fuzzy fallback on top for header text that's
# close-but-not-identical to any of these (e.g. "Rollnumber" with no
# space). "match_roll_no" is included as a real field here — it's not a
# student column, but the stable-key alias for changing a roll number —
# so it goes through the same header-tolerance path as everything else.
def _build_import_field_specs() -> list[FieldSpec]:
    alias_groups: dict[str, set[str]] = {}
    for alias_text, field_key in BULK_IMPORT_COLUMN_MAP.items():
        alias_groups.setdefault(field_key, set()).add(normalize_header(alias_text))
    required = {"roll_no", "name"}
    return [
        FieldSpec(key=field_key, aliases=aliases, required=field_key in required)
        for field_key, aliases in alias_groups.items()
    ]


BULK_IMPORT_FIELD_SPECS = _build_import_field_specs()

YEAR_TO_SEMESTER_CODES = {
    1: {1: "I-I", 2: "I-II"},
    2: {1: "II-I", 2: "II-II"},
    3: {1: "III-I", 2: "III-II"},
    4: {1: "IV-I", 2: "IV-II"},
}


@router.get("/bulk-import/template")
async def student_bulk_import_template(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD/Admin access only", 403, "FORBIDDEN")
    from sms_app.services.learning_service import build_students_template
    return Response(
        content=build_students_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="NextGen-students-template.xlsx"'},
    )


@router.get("/bulk-import/options")
async def student_bulk_import_options(user: CurrentUser = Depends(get_current_user)):
    """Metadata for the guided import wizard."""
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        sems = c.execute(
            "SELECT id, code, name, active FROM academic_semesters ORDER BY sort_order"
        ).fetchall()
    return ok({
        "branches": [{"value": d, "label": d} for d in DEPARTMENTS],
        "years": [
            {"value": 1, "label": "1st Year"},
            {"value": 2, "label": "2nd Year"},
            {"value": 3, "label": "3rd Year"},
            {"value": 4, "label": "4th Year"},
        ],
        "semesters": [
            {"id": s["id"], "code": s["code"], "name": s["name"], "active": bool(s["active"])}
            for s in sems
        ],
    })


def _row_to_import_data(row_map: dict[str, Any]) -> dict:
    data = {k: _cell_to_str(row_map.get(k)) for k in IMPORT_FIELD_KEYS}
    data["department"] = "CSD"
    return data


def _resolve_import_semester(c, year: int, semester_id: int | None = None, semester: int | None = None) -> int:
    """Resolve the selected academic semester safely.

    The UI stores academic_semesters.id, so prefer semester_id. The legacy
    semester=1/2 form is retained only as a fallback for older clients.
    """
    if year not in YEAR_TO_SEMESTER_CODES:
        raise ApiError("Select a valid year", 400, "VALIDATION_ERROR")

    if semester_id is not None and semester_id > 0:
        row = c.execute(
            "SELECT id, code FROM academic_semesters WHERE id=?", (semester_id,)
        ).fetchone()
        if not row:
            raise ApiError("Selected semester does not exist", 400, "VALIDATION_ERROR")
        expected_codes = set(YEAR_TO_SEMESTER_CODES[year].values())
        if row["code"] not in expected_codes:
            raise ApiError("Selected semester does not belong to the selected year", 400, "VALIDATION_ERROR")
        return row["id"]

    if semester not in (1, 2):
        raise ApiError("Select a valid semester", 400, "VALIDATION_ERROR")
    code = YEAR_TO_SEMESTER_CODES[year][semester]
    row = c.execute(
        "SELECT id FROM academic_semesters WHERE code=?", (code,)
    ).fetchone()
    if not row:
        raise ApiError(f"{code} is not available for import", 400, "VALIDATION_ERROR")
    return row["id"]


def _present_import_updates(data: dict[str, str]) -> dict[str, str]:
    # Blank Excel cells mean "leave existing value unchanged" during merge.
    return {k: v for k, v in data.items() if k in IMPORT_FIELD_KEYS and v != ""}


def _drop_unverified_aadhaar(data: dict[str, Any]) -> dict[str, Any]:
    # WHY: Aadhaar isn't collected/verified at import time yet (Boss: "don't
    # consider checking aadhaar yet, we can add them later"). Sheets often
    # have junk or placeholder text in that column (e.g. a roll-number-shaped
    # value), which used to hard-fail the whole row via validate_student's
    # 12-digit check. Rather than loosen validate_student itself — which is
    # shared with the manual add/edit student forms and must keep enforcing
    # Aadhaar there — we only drop an unverified value here, at import time,
    # before validation runs. A clean 12-digit Aadhaar in the sheet still
    # comes through fine; anything else is silently skipped, not stored as
    # garbage, and can be added properly later via student edit.
    aadhaar = re.sub(r"\s", "", str(data.get("aadhaar_number") or ""))
    if aadhaar and not (aadhaar.isdigit() and len(aadhaar) == 12):
        data = dict(data)
        data["aadhaar_number"] = ""
    return data


def _parse_optional_int(raw: str | None, label: str) -> int | None:
    # WHY: some frontend paths can send the literal string "undefined" or ""
    # instead of omitting the query param (e.g. String(possiblyUndefined)).
    # FastAPI's native `int | None` param typing rejects that with a bare,
    # unhelpful 422 before this handler even runs. Accepting str | None here
    # and parsing manually lets us fail with a clear VALIDATION_ERROR instead.
    if raw is None or raw.strip() == "" or raw.strip().lower() == "undefined":
        return None
    try:
        return int(raw)
    except ValueError:
        raise ApiError(f"Invalid {label} value", 400, "VALIDATION_ERROR")


@router.post("/bulk-import")
async def student_bulk_import(
    file: UploadFile = File(...),
    branch: str = "CSD",
    year: int = 0,
    semester_id: str | None = None,
    semester: str | None = None,
    mode: str = "merge",
    user: CurrentUser = Depends(get_current_user),
):
    """Guided Excel import.

    New rows are created. Existing rows are merged by Roll Number. To change
    a roll number, include an optional "Previous Roll Number" column. Blank
    cells never erase existing data. The selected semester is applied to both
    created and updated records.
    """
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    if branch.strip().upper() != "CSD":
        raise ApiError("Only the CSD branch is currently supported by this system", 400, "VALIDATION_ERROR")
    if mode not in ("merge", "create_only"):
        raise ApiError("Invalid import mode", 400, "VALIDATION_ERROR")

    parsed_semester_id = _parse_optional_int(semester_id, "semester_id")
    parsed_semester = _parse_optional_int(semester, "semester")

    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        raise ApiError("Upload an .xlsx, .xls, or .xlsm file exported from Excel", 400, "VALIDATION_ERROR")

    raw = await file.read()
    suffix = filename.lower().rsplit(".", 1)[-1]

    try:
        with connect() as c:
            resolved_semester_id = _resolve_import_semester(c, year, parsed_semester_id, parsed_semester)
    except ApiError:
        raise

    if suffix in ("xlsx", "xlsm"):
        try:
            wb = load_workbook(filename=BytesIO(raw), read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            header_row = next(rows_iter, None)
        except Exception:
            raise ApiError("Could not read that Excel workbook — is it valid?", 400, "VALIDATION_ERROR")
    else:
        if xlrd is None:
            raise ApiError("Legacy .xls support requires xlrd. Install the backend requirements and retry.", 400, "VALIDATION_ERROR")
        try:
            book = xlrd.open_workbook(file_contents=raw, on_demand=True)
            sheet = book.sheet_by_index(0)
            def legacy_rows():
                for r in range(sheet.nrows):
                    yield tuple(sheet.cell_value(r, c) for c in range(sheet.ncols))
            rows_iter = legacy_rows()
            header_row = next(rows_iter, None)
        except Exception:
            raise ApiError("Could not read that legacy .xls workbook — is it valid?", 400, "VALIDATION_ERROR")

    if header_row is None:
        raise ApiError("The sheet is empty", 400, "VALIDATION_ERROR")

    semester_id = resolved_semester_id

    header_report = match_headers(list(header_row), BULK_IMPORT_FIELD_SPECS)
    col_index_to_field: dict[int, str] = {
        idx: m.field for idx, m in enumerate(header_report.matches) if m.field
    }

    missing = header_report.missing_required(BULK_IMPORT_FIELD_SPECS)
    if missing:
        # WHY: name the actual missing field(s) rather than a fixed string —
        # if only Name is missing (Roll No resolved fine, even via fuzzy),
        # say so, don't repeat the old blanket message for every case.
        readable = {"roll_no": "Roll Number (or HallTicket)", "name": "Name"}
        wanted = ", ".join(readable.get(f, f) for f in missing)
        raise ApiError(f"Excel must contain a {wanted} column", 400, "VALIDATION_ERROR")

    assigned_hod = _resolve_hod_for_student(user, None)
    created, updated, skipped, failed = [], [], [], []

    for row_num, row in enumerate(rows_iter, start=2):
        if row is None or all(v is None or str(v).strip() == "" for v in row):
            continue
        row_map: dict[str, Any] = {}
        for idx, field in col_index_to_field.items():
            if idx < len(row):
                row_map[field] = row[idx]

        data = _row_to_import_data(row_map)
        match_roll_no = _cell_to_str(row_map.get("match_roll_no")) or data["roll_no"]
        display_roll = data["roll_no"] or match_roll_no or f"(row {row_num})"

        if not match_roll_no:
            failed.append({"row": row_num, "roll_no": display_roll, "reason": "Missing roll number"})
            continue
        if mode == "create_only" and not data["name"]:
            failed.append({"row": row_num, "roll_no": display_roll, "reason": "Missing name"})
            continue

        # For an update, validation applies to the merged record, not to blank
        # cells in the sheet. This allows "Roll No + Name + Parent Phone" files.
        try:
            with connect() as c:
                existing = c.execute(
                    "SELECT * FROM students WHERE roll_no=%s AND department='CSD'",
                    (match_roll_no,),
                ).fetchone()

                if existing and mode == "merge":
                    merged = dict(existing)
                    updates = _present_import_updates(data)
                    if "name" not in updates:
                        updates["name"] = existing["name"]
                    if data["roll_no"]:
                        updates["roll_no"] = data["roll_no"]
                    else:
                        updates["roll_no"] = existing["roll_no"]
                    for k, v in updates.items():
                        merged[k] = v
                    merged["department"] = "CSD"
                    merged["current_semester_id"] = semester_id
                    _validate_semester_selection(c, semester_id)
                    merged = _drop_unverified_aadhaar(merged)

                    validate_student({k: _cell_to_str(merged.get(k)) for k in STUDENT_DB_KEYS if k != "department"} | {"department": "CSD"})
                    if merged.get("dob"):
                        datetime.strptime(str(merged["dob"]), "%Y-%m-%d")

                    if merged["roll_no"] != existing["roll_no"]:
                        conflict = c.execute(
                            "SELECT id FROM students WHERE roll_no=%s AND id<>? AND department='CSD'",
                            (merged["roll_no"], existing["id"]),
                        ).fetchone()
                        if conflict:
                            raise ValueError(f"New roll number {merged['roll_no']} already belongs to another student")

                    if merged.get("email"):
                        email_conflict = c.execute(
                            "SELECT id FROM students WHERE email=%s AND id<>? AND department='CSD'",
                            (merged["email"], existing["id"]),
                        ).fetchone()
                        if email_conflict:
                            raise ValueError(f"Email {merged['email']} already belongs to another student")

                    aadhaar = merged.get("aadhaar_number")
                    apaar = merged.get("apaar_id")
                    # Existing encrypted values must be reused unless the sheet
                    # actually supplied a replacement value. A sheet cell that
                    # looked non-blank but wasn't a verified 12-digit Aadhaar
                    # was already cleared to "" by _drop_unverified_aadhaar
                    # above — treat that the same as "sheet didn't supply one"
                    # so junk input never overwrites a good existing value.
                    if "aadhaar_number" in updates and aadhaar:
                        merged["aadhaar_number"] = encrypt_field(aadhaar)
                    else:
                        merged["aadhaar_number"] = existing.get("aadhaar_number")
                    if "apaar_id" in updates:
                        merged["apaar_id"] = encrypt_field(apaar)
                    else:
                        merged["apaar_id"] = existing.get("apaar_id")

                    # Batch is derived from current semester, never from roll-number structure.
                    # Recompute it on every import update so legacy/stale stored values are repaired.
                    merged["batch"] = _compute_year_and_batch({**merged, "current_semester_id": semester_id})[1].removesuffix(" Batch")


                    c.execute(
                        """UPDATE students SET roll_no=?,name=?,department=?,email=NULLIF(?,''),phone=?,parent_phone=?,dob=?,
                           address=?,father_name=?,category=?,gender=?,seat_category=?,apaar_id=?,aadhaar_number=?,
                           certificates_submitted=?,certificates_due=?,consultant_name=?,
                           tenth_school=?,tenth_year=?,tenth_marks=?,twelfth_school=?,twelfth_year=?,twelfth_marks=?,
                           diploma_college=?,diploma_year=?,diploma_marks=?,batch=?,current_semester_id=?,hod_username=?,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                        tuple([merged[k] for k in STUDENT_DB_KEYS] + [semester_id, existing.get("hod_username") or assigned_hod, existing["id"]]),
                    )
                    audit(c, user.username, "IMPORT_UPDATE", "student", f"{existing['roll_no']} -> {merged['roll_no']}")
                    updated.append({"row": row_num, "roll_no": merged["roll_no"], "name": merged["name"]})
                    if merged["roll_no"] != existing["roll_no"]:
                        linked = c.execute(
                            "SELECT id, username FROM users WHERE student_roll_no=%s AND role='STUDENT'",
                            (existing["roll_no"],),
                        ).fetchone()
                        if linked:
                            new_username = merged["roll_no"].lower()
                            username_conflict = c.execute(
                                "SELECT id FROM users WHERE username=%s AND id<>?", (new_username, linked["id"])
                            ).fetchone()
                            if username_conflict:
                                raise ValueError(f"Cannot rename login to {new_username}: username already exists")
                            c.execute(
                                "UPDATE users SET username=?,student_roll_no=?,full_name=?,auth_version=auth_version+1 WHERE id=?",
                                (new_username, merged["roll_no"], merged["name"], linked["id"]),
                            )
                            audit(c, user.username, "IMPORT_UPDATE", "student_login", f"{existing['roll_no']} -> {merged['roll_no']}")
                    else:
                        c.execute(
                            "UPDATE users SET full_name=? WHERE student_roll_no=? AND role='STUDENT'",
                            (merged["name"], merged["roll_no"]),
                        )
                    continue

                if existing and mode == "create_only":
                    skipped.append({"row": row_num, "roll_no": data["roll_no"], "reason": "Roll number already exists"})
                    continue

                if not data["name"]:
                    failed.append({"row": row_num, "roll_no": display_roll, "reason": "Missing name"})
                    continue

                data = _drop_unverified_aadhaar(data)
                _validate_semester_selection(c, semester_id)
                validate_student(data)
                if data["dob"]:
                    datetime.strptime(data["dob"], "%Y-%m-%d")
                enc_data = dict(data)
                enc_data["batch"] = _compute_year_and_batch({**data, "current_semester_id": semester_id})[1].removesuffix(" Batch")
                enc_data["aadhaar_number"] = encrypt_field(data["aadhaar_number"])
                enc_data["apaar_id"] = encrypt_field(data["apaar_id"])
                c.execute(
                    """INSERT INTO students(roll_no,name,department,email,phone,parent_phone,dob,address,father_name,
                       category,gender,seat_category,apaar_id,aadhaar_number,certificates_submitted,certificates_due,
                       consultant_name,tenth_school,tenth_year,tenth_marks,twelfth_school,twelfth_year,twelfth_marks,
                       diploma_college,diploma_year,diploma_marks,batch,current_semester_id,hod_username)
                       VALUES(?,?,?,NULLIF(?,''),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple([enc_data[k] for k in STUDENT_DB_KEYS] + [semester_id, assigned_hod]),
                )
                audit(c, user.username, "IMPORT_CREATE", "student", data["roll_no"])
                for item, st in [("Personal details", "Complete"), ("Documents", "Pending"),
                                  ("ID card", "Pending"), ("Fees", "Pending"),
                                  ("Attendance records", "Available"), ("Marks records", "Available")]:
                    c.execute("INSERT IGNORE INTO checklist(roll_no,item,status) VALUES(?,?,?)", (data["roll_no"], item, st))

            username, password = ensure_student_login(data["roll_no"], user.username)
            created.append({"row": row_num, "roll_no": data["roll_no"], "name": data["name"], "username": username, "password": password})
        except IntegrityError:
            failed.append({"row": row_num, "roll_no": display_roll, "reason": "Duplicate roll number or email"})
        except ValueError as e:
            failed.append({"row": row_num, "roll_no": display_roll, "reason": str(e)})
        except Exception:
            failed.append({"row": row_num, "roll_no": display_roll, "reason": "Unexpected error — see server logs"})

    total = len(created) + len(updated) + len(skipped) + len(failed)
    return ok({
        "total_rows": total,
        "created_count": len(created),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "branch": branch.upper(),
        "year": year,
        "semester": semester,
        "semester_id": semester_id,
        "mode": mode,
        # WHY: per Boss — the user must always be told which columns were
        # recognized (and how) vs. ignored. A clean run with zero failed
        # rows must not read as "everything in the sheet was used" when a
        # column was actually silently skipped.
        "column_mapping": header_report.as_dict(),
    })


@router.patch("/{student_id}")
async def student_update(student_id: int, body: StudentBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            existing = c.execute("SELECT id,hod_username FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
        elif user.role == "HOD":
            existing = c.execute("SELECT id,hod_username FROM students WHERE id=? AND department='CSD' AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            existing = c.execute("SELECT id,hod_username FROM students WHERE id=? AND department='CSD'", (student_id,)).fetchone()
    if not existing:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    assigned_hod = existing.get("hod_username") if user.role == "HOD" else _resolve_hod_for_student(user, body.hod_username or existing.get("hod_username"))
    data = _body_to_data(body)
    try:
        validate_student(data)
        if data["dob"]:
            datetime.strptime(data["dob"], "%Y-%m-%d")
        with connect() as c:
            _validate_semester_selection(c, body.current_semester_id)
            data["batch"] = _compute_year_and_batch({**data, "current_semester_id": body.current_semester_id})[1].removesuffix(" Batch")
            # Encrypt AFTER validation — §4.4 ordering requirement
            data["aadhaar_number"] = encrypt_field(data["aadhaar_number"])
            data["apaar_id"] = encrypt_field(data["apaar_id"])
            c.execute(
                """UPDATE students SET roll_no=?,name=?,department=?,email=NULLIF(?,''),phone=?,parent_phone=?,dob=?,
                   address=?,father_name=?,category=?,gender=?,seat_category=?,apaar_id=?,aadhaar_number=?,
                   certificates_submitted=?,certificates_due=?,consultant_name=?,
                   tenth_school=?,tenth_year=?,tenth_marks=?,twelfth_school=?,twelfth_year=?,twelfth_marks=?,
                   diploma_college=?,diploma_year=?,diploma_marks=?,batch=?,
                   current_semester_id=?,hod_username=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (*[data[k] for k in STUDENT_DB_KEYS], body.current_semester_id, assigned_hod, student_id),
            )
            audit(c, user.username, "UPDATE", "student", data["roll_no"])
        return ok({"id": student_id, "created_credentials": None})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")
    except IntegrityError:
        raise ApiError("A student with that roll number or email already exists", 400, "VALIDATION_ERROR")


@router.post("/{student_id}/toggle-status")
async def toggle_status(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        new_active = 0 if row["active"] else 1
        c.execute("UPDATE students SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_active, student_id))
        audit(c, user.username, "STATUS", "student", f"{row['roll_no']} -> {new_active}")
    return ok({"active": bool(new_active)})


@router.post("/{student_id}/photo")
async def student_photo(
    student_id: int,
    photo: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if not row:
        raise ApiError("Student not found", 404, "NOT_FOUND")
    try:
        path = await save_profile_photo(photo, subdir="students", stem=row["roll_no"])
        with connect() as c:
            c.execute("UPDATE students SET photo_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (path, student_id))
            audit(c, user.username, "PHOTO", "student", row["roll_no"])
        return ok({"photo_path": path})
    except PhotoUploadError as e:
        raise ApiError(str(e), 400, "UPLOAD_ERROR")


@router.post("/{student_id}/photo/delete")
async def student_photo_delete(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        c.execute("UPDATE students SET photo_path=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (student_id,))
        audit(c, user.username, "PHOTO_DELETE", "student", row["roll_no"])
    return ok({"photo_path": None})


@router.delete("/{student_id}")
async def student_delete(student_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "ADMIN" or user.username == "admin":
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        elif user.role == "HOD":
            row = c.execute("SELECT * FROM students WHERE id=? AND (hod_username=? OR hod_username IS NULL)", (student_id, user.username)).fetchone()
        else:
            row = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not row:
            raise ApiError("Student not found", 404, "NOT_FOUND")
        roll_no = row["roll_no"]
        c.execute("DELETE FROM attendance_records WHERE roll_no=?", (roll_no,))
        c.execute("DELETE FROM sms_queue WHERE roll_no=?", (roll_no,))
        c.execute("DELETE FROM checklist WHERE roll_no=?", (roll_no,))
        c.execute("DELETE FROM users WHERE student_roll_no=? OR username=?", (roll_no, roll_no))
        c.execute("DELETE FROM students WHERE id=?", (student_id,))
        audit(c, user.username, "DELETE", "student", roll_no)
    return ok({"deleted": True, "id": student_id})


# Halted certificate upload (§4.5) — accepts the request, returns success without writing anything
@router.post("/{student_id}/certificate/{doc_type}")
async def certificate_upload(student_id: int, doc_type: str, user: CurrentUser = Depends(get_current_user)):
    """HALTED per §4.5 — certificate upload disabled. Route kept for backward-compat."""
    return ok({"message": "Certificate upload is currently disabled"})