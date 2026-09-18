"""Notes and results business logic for the JSON API."""

from __future__ import annotations

import io
import re
import uuid
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from excel_import import FieldSpec, HeaderMatch, MatchReport, match_headers, normalize_header

from database import audit, connect
from webapp.photo_upload import UPLOADS_DIR


NOTES_MAX_BYTES = 15 * 1024 * 1024
NOTES_ALLOWED_EXT = {".pdf", ".ppt", ".pptx", ".doc", ".docx"}
RESULT_ALLOWED_EXT = {".xlsx", ".xlsm"}


def _safe_filename(value: str, fallback: str = "file") -> str:
    base = Path(value or "").stem.strip().lower()
    base = re.sub(r"[^a-z0-9_-]+", "-", base).strip("-_")
    return base or fallback


def save_note_bytes(*, raw: bytes, original_filename: str, subject_code: str) -> tuple[str, str]:
    if not raw:
        raise ValueError("No file was selected")
    if len(raw) > NOTES_MAX_BYTES:
        raise ValueError("Notes file must be smaller than 15MB")
    ext = Path(original_filename or "").suffix.lower()
    if ext not in NOTES_ALLOWED_EXT:
        raise ValueError("Notes must be a PDF, PowerPoint, or Word document")

    target_dir = UPLOADS_DIR / "notes"
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_filename(subject_code, 'subject')}-{uuid.uuid4().hex[:10]}{ext}"
    (target_dir / filename).write_bytes(raw)
    return f"/files/notes/{filename}", filename


def _note_row(row) -> dict:
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "original_filename": row["original_filename"],
        "subject_id": int(row["subject_id"]),
        "subject_code": row["subject_code"],
        "subject_name": row["subject_name"],
        "semester_id": int(row["semester_id"]),
        "semester_code": row["semester_code"],
        "semester_name": row["semester_name"],
        "faculty_username": row["faculty_username"],
        "faculty_name": row["faculty_name"] or row["faculty_username"],
        "created_at": row["created_at"],
        "file_path": row["file_path"],
    }


def list_notes(*, username: str, role: str, student_roll_no: str | None = None) -> list[dict]:
    with connect() as c:
        if role == "STUDENT":
            student = c.execute(
                "SELECT department, current_semester_id FROM students WHERE roll_no=? AND active=1",
                (student_roll_no,),
            ).fetchone()
            if not student or not student.get("current_semester_id"):
                return []
            rows = c.execute(
                """
                SELECT n.id,n.title,n.original_filename,n.file_path,n.created_at,
                       s.id AS subject_id,s.code AS subject_code,s.name AS subject_name,
                       sem.id AS semester_id,sem.code AS semester_code,sem.name AS semester_name,
                       n.faculty_username,u.full_name AS faculty_name
                FROM notes n
                JOIN subjects s ON s.id=n.subject_id
                JOIN academic_semesters sem ON sem.id=s.semester_id
                JOIN users u ON u.username=n.faculty_username
                JOIN subject_faculty sf ON sf.subject_id=s.id AND sf.faculty_username=n.faculty_username
                WHERE s.active=1 AND sem.active=1 AND sem.id=? AND n.active=1
                ORDER BY s.name, n.created_at DESC, n.id DESC
                """,
                (student["current_semester_id"],),
            ).fetchall()
        elif role == "FACULTY":
            rows = c.execute(
                """
                SELECT n.id,n.title,n.original_filename,n.file_path,n.created_at,
                       s.id AS subject_id,s.code AS subject_code,s.name AS subject_name,
                       sem.id AS semester_id,sem.code AS semester_code,sem.name AS semester_name,
                       n.faculty_username,u.full_name AS faculty_name
                FROM notes n
                JOIN subjects s ON s.id=n.subject_id
                JOIN academic_semesters sem ON sem.id=s.semester_id
                JOIN users u ON u.username=n.faculty_username
                JOIN subject_faculty sf ON sf.subject_id=s.id AND sf.faculty_username=n.faculty_username
                WHERE n.faculty_username=? AND n.active=1
                ORDER BY sem.sort_order, s.name, n.created_at DESC, n.id DESC
                """,
                (username,),
            ).fetchall()
        elif role == "HOD":
            rows = c.execute(
                """
                SELECT n.id,n.title,n.original_filename,n.file_path,n.created_at,
                       s.id AS subject_id,s.code AS subject_code,s.name AS subject_name,
                       sem.id AS semester_id,sem.code AS semester_code,sem.name AS semester_name,
                       n.faculty_username,u.full_name AS faculty_name
                FROM notes n
                JOIN subjects s ON s.id=n.subject_id
                JOIN academic_semesters sem ON sem.id=s.semester_id
                JOIN users u ON u.username=n.faculty_username
                JOIN users fu ON fu.username=n.faculty_username
                WHERE n.active=1 AND (fu.hod_username=? OR fu.username=?)
                ORDER BY sem.sort_order, s.name, n.created_at DESC, n.id DESC
                """,
                (username, username),
            ).fetchall()
        else:  # ADMIN
            rows = c.execute(
                """
                SELECT n.id,n.title,n.original_filename,n.file_path,n.created_at,
                       s.id AS subject_id,s.code AS subject_code,s.name AS subject_name,
                       sem.id AS semester_id,sem.code AS semester_code,sem.name AS semester_name,
                       n.faculty_username,u.full_name AS faculty_name
                FROM notes n
                JOIN subjects s ON s.id=n.subject_id
                JOIN academic_semesters sem ON sem.id=s.semester_id
                JOIN users u ON u.username=n.faculty_username
                WHERE n.active=1
                ORDER BY sem.sort_order, s.name, n.created_at DESC, n.id DESC
                """
            ).fetchall()
    return [_note_row(r) for r in rows]


def get_note_for_download(*, note_id: int, username: str, role: str, student_roll_no: str | None):
    with connect() as c:
        row = c.execute(
            """
            SELECT n.*, s.code AS subject_code, s.name AS subject_name, s.semester_id,
                   sem.code AS semester_code, sem.name AS semester_name,
                   u.full_name AS faculty_name, u.hod_username AS faculty_hod_username
            FROM notes n
            JOIN subjects s ON s.id=n.subject_id
            JOIN academic_semesters sem ON sem.id=s.semester_id
            JOIN users u ON u.username=n.faculty_username
            WHERE n.id=? AND n.active=1
            """,
            (note_id,),
        ).fetchone()
        if not row:
            return None
        if role == "ADMIN":
            return row
        if role == "FACULTY":
            assigned = c.execute(
                "SELECT 1 FROM subject_faculty WHERE subject_id=? AND faculty_username=?",
                (row["subject_id"], username),
            ).fetchone()
            if not assigned:
                return None
            return row
        if role == "HOD":
            if row.get("faculty_hod_username") != username and row.get("faculty_username") != username:
                return None
            return row
        student = c.execute(
            "SELECT current_semester_id FROM students WHERE roll_no=? AND active=1",
            (student_roll_no,),
        ).fetchone()
        if not student or int(student.get("current_semester_id") or 0) != int(row["semester_id"]):
            return None
        # Keep the assignment relationship in the authorization path. A note
        # from an unassigned faculty member must never become student-visible.
        assigned = c.execute(
            "SELECT 1 FROM subject_faculty WHERE subject_id=? AND faculty_username=?",
            (row["subject_id"], row["faculty_username"]),
        ).fetchone()
        return row if assigned else None


def create_note(*, subject_id: int, title: str, filename: str, file_path: str, faculty_username: str) -> int:
    title = (title or "").strip()
    if not title:
        raise ValueError("Note title is required")
    if len(title) > 180:
        raise ValueError("Note title must be 180 characters or fewer")
    with connect() as c:
        row = c.execute(
            """
            SELECT s.id,s.code,s.name,sem.code AS semester_code
            FROM subjects s JOIN academic_semesters sem ON sem.id=s.semester_id
            JOIN subject_faculty sf ON sf.subject_id=s.id
            WHERE s.id=? AND s.active=1 AND sf.faculty_username=?
            """,
            (subject_id, faculty_username),
        ).fetchone()
        if not row:
            raise ValueError("You can upload notes only for subjects assigned to you")
        cur = c.execute(
            """
            INSERT INTO notes(subject_id,faculty_username,title,original_filename,file_path,active)
            VALUES(?,?,?,?,?,1)
            """,
            (subject_id, faculty_username, title, filename, file_path),
        )
        note_id = cur.lastrowid
        audit(c, faculty_username, "UPLOAD", "note", f"{row['code']} — {title}")
    return int(note_id)


def delete_note(*, note_id: int, username: str, role: str) -> str | None:
    with connect() as c:
        row = c.execute(
            """
            SELECT n.file_path,n.faculty_username,s.code,u.hod_username
            FROM notes n JOIN subjects s ON s.id=n.subject_id
            JOIN users u ON u.username=n.faculty_username
            WHERE n.id=? AND n.active=1
            """,
            (note_id,),
        ).fetchone()
        if not row:
            return None
        allowed = (
            role == "ADMIN"
            or (role == "FACULTY" and row["faculty_username"] == username)
            or (role == "HOD" and row.get("hod_username") == username)
        )
        if not allowed:
            raise PermissionError("You do not have access to remove this note")
        c.execute("UPDATE notes SET active=0 WHERE id=?", (note_id,))
        audit(c, username, "DELETE_UPLOAD", "note", f"{row['code']} — note {note_id}")
        return row["file_path"]


def result_upload_options() -> dict:
    with connect() as c:
        semesters = c.execute(
            "SELECT id,code,name,active FROM academic_semesters ORDER BY sort_order"
        ).fetchall()
        batches = c.execute(
            "SELECT DISTINCT batch FROM students WHERE department=? AND batch IS NOT NULL ORDER BY batch DESC",
            ("CSD",),
        ).fetchall()
    return {
        "branches": [{"value": d, "label": d} for d in ("CSD",)],
        "semesters": [
            {"id": int(s["id"]), "code": s["code"], "name": s["name"], "active": bool(s["active"])}
            for s in semesters
        ],
        "batches": [str(b["batch"]) for b in batches if b.get("batch")],
    }


# Results import fields. These are the minimum semantic fields the importer
# understands; aliases are normalized once so every Results surface shares the
# exact same matcher as Students.
RESULT_LONG_FIELD_ALIASES = {
    "roll_no": {"roll no", "roll number", "roll", "hall ticket", "hallticket", "h t no", "ht no", "student id"},
    "subject_code": {"subject code", "code", "subject"},
    "subject_name": {"subject name", "subject title", "name"},
    "marks": {"marks", "score", "obtained marks", "obtained", "total", "total marks"},
    "max_marks": {"max marks", "maximum marks", "max", "out of"},
    "grade": {"grade", "letter grade"},
    "grade_point": {"grade point", "grade points", "gp"},
    "result_status": {"result", "result status", "status"},
    "sgpa": {"sgpa", "gpa"},
    "percentage": {"percentage", "percent", "overall percentage"},
}

RESULT_WIDE_SUBHEADER_ALIASES = {
    "internal_marks": {"im", "internal", "internal marks", "internal mark"},
    "external_marks": {"em", "external", "external marks", "external mark"},
    "marks": {"tm", "total", "total marks"},
    "grade": {"g", "grade", "letter grade"},
    "grade_point": {"gp", "grade point", "grade points"},
    "credits": {"c", "credit", "credits"},
}


def _field_specs(aliases: dict[str, set[str]], required: set[str] | None = None) -> list[FieldSpec]:
    required = required or set()
    return [
        FieldSpec(key=key, aliases={normalize_header(v) for v in values}, required=key in required)
        for key, values in aliases.items()
    ]


RESULT_LONG_FIELD_SPECS = _field_specs(
    RESULT_LONG_FIELD_ALIASES,
    {"roll_no", "subject_code", "subject_name", "marks"},
)
RESULT_WIDE_SUBHEADER_SPECS = _field_specs(RESULT_WIDE_SUBHEADER_ALIASES)
RESULT_ROLL_SPECS = _field_specs({"roll_no": RESULT_LONG_FIELD_ALIASES["roll_no"]}, {"roll_no"})

# — WHY this exists: real VR24-style wide sheets have per-student summary
# fields (SGPA, total Credits, Backlogs) as single-column headers trailing
# the last 6-column subject block — see II_B_Tech_I_sem__VR24__Result_
# Analysis_JAN-2026 col 57-59. These are NOT a malformed 10th subject
# block; the wide-block loop must recognize and skip them via this spec
# set rather than walking into them with its 6-column stride.
# "credits" here is the sheet's *total* credits column (already equal to
# the sum of every subject block's per-row C value — verified against the
# real file: 3+3+4+3+3+1.5+1.5+1+0 = 20, matching the trailing column
# exactly) so it is recognized/reported but never written anywhere new;
# the batch total is always derivable via SUM(result_items.credits).
# "backlogs" has no existing result_items column and adding one is a new
# schema decision outside this workstream's approved scope (§2.5 approved
# exactly three columns) — recognized so it is reported as mapped, not
# silently dropped, but not written to the DB.
RESULT_SUMMARY_FIELD_ALIASES = {
    "sgpa": {"sgpa", "gpa"},
    "credits_total": {"credits", "credit", "total credits"},
    "backlogs": {"backlogs", "backlog", "no of backlogs", "number of backlogs"},
}
RESULT_SUMMARY_FIELD_SPECS = _field_specs(RESULT_SUMMARY_FIELD_ALIASES)


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value: Any, label: str, excel_row_no: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Row {excel_row_no}: {label} must be numeric")


def _optional_number(value: Any, label: str, excel_row_no: int) -> float | None:
    """Same as _number, but a genuinely blank cell returns None instead of
    erroring — see IM/EM/Credits handling in _parse_wide_results.

    # WHY: real VR24 sheets leave IM/EM/C blank for subjects with no
    # internal/external split (e.g. an internal-marks-only lab where TM
    # already equals IM, or a 0-credit course) — verified against the real
    # uploaded file: block 9 ("Gender Sensitization Laboratory", C=0) has
    # EM blank for 72 of 73 real students. A blank here is real, meaningful
    # source data, not a data-entry error — it must store as NULL, never as
    # 0, or the stored data claims a mark that was never actually taken.
    # A non-blank value that still fails to parse (garbage/typo) is a
    # different situation and must still raise, same as _number.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Row {excel_row_no}: {label} must be numeric")


def _looks_like_roll_number(cell_text: str) -> bool:
    """Structural/permissive roll-number shape check — see §7.3 in
    scratch/HANDOFF_EXCEL_IMPORT_OVERHAUL.md.

    # WHY: real VR24-style sheets bury a statistics/sign-off footer
    # (REGISTERED / APPEARED / PASSED / FAILED / PASS % / FACULTY /
    # SIGNATURE / CGPA-distribution table / coordinator sign-off) directly
    # below the last real student row, often with no blank separator to
    # rely on in general. The row loop must recognize "student data has
    # ended" using the roll-number cell's *shape*, not just non-blankness.
    #
    # Deliberately NOT a college-specific regex (e.g. tied to `YYBTnA NNNN`)
    # — the real file already has two differently-shaped valid rolls in play
    # (`24BT1A6701` regular-entry, `25BT5A6703` lateral-entry), and a strict
    # scheme-specific pattern would incorrectly reject a different
    # institution's format. Instead this rejects what footer/label text
    # structurally looks like: prose (contains a space) or pure-alphabetic
    # text with no digit at all (e.g. "REGISTERED", "PASS %", "FACULTY").
    # Do not tighten this into a positive roll-format match — that was
    # explicitly discussed and rejected in favor of this permissive check.
    """
    text = cell_text.strip()
    if not text:
        return False
    if " " in text:
        return False
    if not any(ch.isdigit() for ch in text):
        return False
    if not any(ch.isalpha() for ch in text):
        # A pure-numeric S.No-like value (e.g. "1") is not a roll number
        # shape either — real rolls here always mix letters and digits.
        return False
    return True


def _header_matches_for_long(headers: list[Any]) -> MatchReport:
    return match_headers(headers, RESULT_LONG_FIELD_SPECS)


def _detect_wide_format(rows: list[list[Any]]) -> bool:
    """Conservative detector for the verified VR24 3-row result shape.

    We require both a strong IM/EM/TM/G/GP/C signature on row 3 and at least
    one subject-code/name pair above it. A normal one-row long-format sheet
    therefore falls through unchanged even if a data row happens to contain
    a short token such as 'G'.
    """
    if len(rows) < 3:
        return False
    row1, row2, row3 = rows[:3]
    third = match_headers(row3, RESULT_WIDE_SUBHEADER_SPECS)
    mapped = {m.field for m in third.mapped}
    signature = {"internal_marks", "external_marks", "marks", "grade", "grade_point", "credits"}
    signature_hits = len(mapped & signature)
    subject_headers = 0
    for idx in range(2, min(len(row1), len(row2))):
        code = _cell_str(row1[idx])
        name = _cell_str(row2[idx])
        if code and name:
            subject_headers += 1
    return signature_hits >= 4 and subject_headers >= 1


def _validate_wide_subheaders(subheaders: list[Any], start_col: int) -> MatchReport:
    """Use the shared matcher, but fail closed on duplicate field claims."""
    report = match_headers(subheaders, RESULT_WIDE_SUBHEADER_SPECS)
    expected = {"internal_marks", "external_marks", "marks", "grade", "grade_point", "credits"}
    missing = expected - {m.field for m in report.mapped}
    if missing:
        readable = {
            "internal_marks": "IM / Internal Marks",
            "external_marks": "EM / External Marks",
            "marks": "TM / Total Marks",
            "grade": "G / Grade",
            "grade_point": "GP / Grade Point",
            "credits": "C / Credits",
        }
        wanted = ", ".join(readable[k] for k in sorted(missing))
        raise ValueError(f"Subject block starting at column {start_col + 1}: missing {wanted}")
    return report


def _parse_long_results(*, ws, headers: list[Any], semester_id: int, department: str, batch: str, c, sem, max_source_rows: int, skipped_students: list[dict] | None = None) -> tuple[list[dict], MatchReport]:
    report = _header_matches_for_long(headers)
    cols = report.field_index()
    missing = report.missing_required(RESULT_LONG_FIELD_SPECS)
    if missing:
        readable = {
            "roll_no": "Roll Number",
            "subject_code": "Subject Code",
            "subject_name": "Subject Name",
            "marks": "Marks",
        }
        wanted = ", ".join(readable.get(f, f) for f in missing)
        raise ValueError("Missing required Excel columns: " + wanted)

    parsed: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for excel_row_no, row_values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if excel_row_no > max_source_rows + 1:
            raise ValueError(f"Results sheet cannot contain more than {max_source_rows} data rows")
        vals = list(row_values)
        get = lambda field: vals[cols[field]] if cols[field] < len(vals) else None
        roll_no = _cell_str(get("roll_no"))
        subject_code = _cell_str(get("subject_code")).upper()
        subject_name = _cell_str(get("subject_name"))
        if not roll_no and not subject_code and not subject_name:
            continue
        if not roll_no or not subject_code or not subject_name:
            raise ValueError(f"Row {excel_row_no}: roll number, subject code, and subject name are required")
        student = c.execute(
            "SELECT roll_no,name FROM students WHERE roll_no=? AND department=? AND batch=? AND active=1",
            (roll_no, department, batch),
        ).fetchone()
        if not student:
            if skipped_students is not None:
                skipped_students.append({
                    "row": excel_row_no,
                    "roll_no": roll_no,
                    "reason": "Student is not registered in the app for this branch/batch",
                })
            continue
        key = (roll_no.lower(), subject_code)
        if key in seen:
            raise ValueError(f"Row {excel_row_no}: duplicate subject result for {roll_no} / {subject_code}")
        seen.add(key)

        marks = _number(get("marks"), "marks", excel_row_no)
        max_marks = 100.0
        if "max_marks" in cols and get("max_marks") not in (None, ""):
            max_marks = _number(get("max_marks"), "max marks", excel_row_no)
        if max_marks <= 0 or marks < 0 or marks > max_marks:
            raise ValueError(f"Row {excel_row_no}: marks must be between 0 and max marks")

        def optional(field: str) -> str:
            return _cell_str(get(field)) if field in cols else ""

        parsed.append({
            "roll_no": roll_no,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "marks": marks,
            "max_marks": max_marks,
            "internal_marks": None,
            "external_marks": None,
            "credits": None,
            "grade": optional("grade"),
            "grade_point": optional("grade_point"),
            "result_status": optional("result_status"),
            "sgpa": optional("sgpa"),
            "percentage": optional("percentage"),
        })
    return parsed, report


def _parse_wide_results(*, ws, header_rows: list[list[Any]], semester_id: int, department: str, batch: str, c, sem, max_source_rows: int, skipped_students: list[dict] | None = None) -> tuple[list[dict], MatchReport]:
    row1, row2, row3 = header_rows[:3]
    report = match_headers(row3, RESULT_WIDE_SUBHEADER_SPECS)
    roll_report = match_headers(row1[:2], RESULT_ROLL_SPECS)

    # The first two cells are intentionally both surfaced: S NO is expected
    # to be ignored; H T NO must resolve to roll_no.
    combined = MatchReport(matches=[])
    combined.matches.extend(roll_report.matches)
    block_specs: list[dict] = []
    summary_cols: dict[str, int] = {}  # field key -> column index, e.g. {"sgpa": 56}
    subject_count = 0
    max_col = max(len(row1), len(row2), len(row3))
    col = 2
    while col < max_col:
        code = _cell_str(row1[col] if col < len(row1) else "")
        name = _cell_str(row2[col] if col < len(row2) else "")
        block_values = list((row3[col:col + 6] + [None] * 6)[:6])
        populated = any(_cell_str(v) for v in block_values)
        if not code and not name and not populated:
            col += 6
            continue
        # — WHY: trailing per-student summary fields (SGPA / Credits /
        # Backlogs) look like a broken subject block to the naive check
        # above (code present, name blank) but are a single labeled column,
        # not a 6-column block. Detect this shape and route it to
        # summary_cols instead of raising — see RESULT_SUMMARY_FIELD_SPECS
        # comment for why each field is (or isn't) written downstream.
        if code and not name:
            summary_match = match_headers([code], RESULT_SUMMARY_FIELD_SPECS)
            resolved = summary_match.field_index()
            if "sgpa" in resolved or "credits_total" in resolved or "backlogs" in resolved:
                field_key = next(iter(resolved))
                summary_cols[field_key] = col
                combined.matches.append(HeaderMatch(code, f"summary:{field_key}", summary_match.matches[0].via, summary_match.matches[0].score))
                col += 1
                continue
        if not code or not name:
            raise ValueError(f"Subject block starting at column {col + 1}: subject code and subject name are required")
        if col + 6 > max_col:
            raise ValueError(f"Subject block {code}: incomplete 6-column block")
        block_report = _validate_wide_subheaders(block_values, col)
        block_specs.append({"start": col, "code": code.upper(), "name": name, "report": block_report})
        subject_count += 1
        col += 6

    # Report every recognized subject block as a mapped field and every
    # unsupported populated first-row block as ignored, without changing the
    # public mapped/ignored contract.
    mapped_headers = {m.header for m in combined.matches}
    for spec in block_specs:
        block_header = f"{spec['code']} — {spec['name']}"
        combined.matches.append(HeaderMatch(block_header, f"subject_block:{spec['code']}", "exact", 0.0))
        for m in spec["report"].matches:
            combined.matches.append(HeaderMatch(m.header, f"{m.field}:{spec['code']}" if m.field else None, m.via, m.score))

    if roll_report.missing_required(RESULT_ROLL_SPECS):
        raise ValueError("Wide results sheet must contain an H T NO / Hall Ticket / Roll Number column")
    if not block_specs:
        raise ValueError("No subject blocks were found in the wide-format results sheet")

    roll_col = roll_report.field_index()["roll_no"]
    parsed: list[dict] = []
    seen: set[tuple[str, str]] = set()
    data_limit = 3 + max_source_rows
    for excel_row_no, row_values in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
        if excel_row_no > data_limit:
            raise ValueError(f"Results sheet cannot contain more than {max_source_rows} data rows")
        vals = list(row_values)
        roll_no = _cell_str(vals[roll_col] if roll_col < len(vals) else "")
        if not roll_no:
            # Completely blank student rows are harmless separators.
            if not any(_cell_str(v) for v in vals):
                continue
            raise ValueError(f"Row {excel_row_no}: hall ticket / roll number is required")
        # — WHY: stop (not skip) at the first non-blank row whose roll-number
        # cell doesn't look like a real roll number — this is the
        # student-data-ended boundary for VR24-style sheets, which bury a
        # REGISTERED/APPEARED/PASSED/... statistics footer + CGPA table +
        # sign-off block directly after the last real student row. See
        # _looks_like_roll_number and §7.3 in
        # scratch/HANDOFF_EXCEL_IMPORT_OVERHAUL.md for why this stops
        # entirely rather than skipping just this one row: the real file's
        # structure is one contiguous student block then footer, so treating
        # the first non-roll-shaped row as "footer has started" is safer
        # than silently absorbing a genuinely malformed student row as if it
        # were footer noise.
        if not _looks_like_roll_number(roll_no):
            break
        student = c.execute(
            "SELECT roll_no,name FROM students WHERE roll_no=? AND department=? AND batch=? AND active=1",
            (roll_no, department, batch),
        ).fetchone()
        if not student:
            if skipped_students is not None:
                skipped_students.append({
                    "row": excel_row_no,
                    "roll_no": roll_no,
                    "reason": "Student is not registered in the app for this branch/batch",
                })
            continue

        # — WHY: SGPA is per-student, not per-subject, but result_items is
        # one row per (student, subject) — so the same row-level SGPA value
        # is written onto every subject row for this student, same pattern
        # the long-format path already uses for its own "sgpa" column.
        row_sgpa = ""
        if "sgpa" in summary_cols:
            sgpa_col = summary_cols["sgpa"]
            row_sgpa = _cell_str(vals[sgpa_col] if sgpa_col < len(vals) else "")

        for spec in block_specs:
            sub_report = spec["report"]
            local_cols = sub_report.field_index()
            get = lambda field: vals[spec["start"] + local_cols[field]] if spec["start"] + local_cols[field] < len(vals) else None
            # — WHY: TM stays strict (_number) — a blank total is still an
            # error today; IM/EM/credits use _optional_number because real
            # VR24 sheets legitimately leave these blank per subject (e.g. an
            # internal-only lab, or a 0-credit course) — see _optional_number's
            # docstring and §7.2 in scratch/HANDOFF_EXCEL_IMPORT_OVERHAUL.md.
            # Do not swap TM to _optional_number without re-checking real data
            # once §7.3's footer/roll-shape fix lands (blank TM was only ever
            # observed on rows that turn out not to be real students at all).
            total = _number(get("marks"), "total marks (TM)", excel_row_no)
            internal = _optional_number(get("internal_marks"), "internal marks (IM)", excel_row_no)
            # — WHY: "AB" (Absent) is a real, meaningful non-numeric marker on
            # VR24 mark sheets — distinct from a blank cell. Blank means "no
            # such component exists for this subject"; AB means "this student
            # did not attempt the external exam." Confirmed against every real
            # occurrence in the reference file (20/20 consistent): EM='AB',
            # TM=IM exactly (external contributed 0 to the total), G='AB',
            # GP=0, C=0. Per the project owner: AB != a scored 0 (0 means
            # "attempted and scored zero"), so external_marks must store NULL
            # here, never 0 — storing 0 would falsely claim an attempt.
            # Grade is force-set to the literal "AB" (not read from the G
            # cell) so the marker survives even if a future sheet's G column
            # is blank instead of also saying "AB" — do not read grade from
            # the cell in this branch, keep the marker authoritative here.
            em_raw = get("external_marks")
            is_absent = isinstance(em_raw, str) and em_raw.strip().upper() == "AB"
            if is_absent:
                external = None
            else:
                external = _optional_number(em_raw, "external marks (EM)", excel_row_no)
            credits = _optional_number(get("credits"), "credits (C)", excel_row_no)
            if total < 0:
                raise ValueError(f"Row {excel_row_no}: total marks (TM) cannot be negative")
            # — WHY: None-tolerant guard — internal/external/credits can now be
            # None (a genuine blank, not a parse failure); `None < 0` raises
            # TypeError in Python 3, so each must be checked individually.
            if (internal is not None and internal < 0) or (external is not None and external < 0) or (credits is not None and credits < 0):
                raise ValueError(f"Row {excel_row_no}: IM, EM, and credits cannot be negative")
            subject_code = spec["code"]
            key = (roll_no.lower(), subject_code)
            if key in seen:
                raise ValueError(f"Row {excel_row_no}: duplicate subject result for {roll_no} / {subject_code}")
            seen.add(key)
            grade_col = spec["start"] + local_cols["grade"]
            gp_col = spec["start"] + local_cols["grade_point"]
            # — WHY: grade is force-set to "AB" here (not read from the G
            # cell) so the Absent marker is authoritative and survives even
            # on a future sheet where G might be blank instead of also
            # saying "AB" — do not read grade from the cell in this branch.
            grade_value = "AB" if is_absent else _cell_str(vals[grade_col] if grade_col < len(vals) else "")
            parsed.append({
                "roll_no": roll_no,
                "subject_code": subject_code,
                "subject_name": spec["name"],
                "marks": total,
                "max_marks": 100.0,
                "internal_marks": internal,
                "external_marks": external,
                "credits": credits,
                "grade": grade_value,
                "grade_point": _cell_str(vals[gp_col] if gp_col < len(vals) else ""),
                "result_status": "",
                "sgpa": row_sgpa,
                "percentage": "",
            })

    if not parsed:
        raise ValueError("No valid result rows were found in the Excel file")
    return parsed, combined


def upload_results_excel(*, raw: bytes, filename: str, department: str, batch: str, semester_id: int, title: str, admin_username: str) -> dict:
    if not raw:
        raise ValueError("No results file was selected")
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("Results Excel file must be smaller than 10MB")
    if Path(filename or "").suffix.lower() not in RESULT_ALLOWED_EXT:
        raise ValueError("Results must be an .xlsx or .xlsm file")
    department = (department or "").strip().upper()
    batch = (batch or "").strip()
    title = (title or "").strip() or "Semester Result"
    if department not in {"CSD"}:
        raise ValueError("Select a valid branch")
    if not batch:
        raise ValueError("Select a valid batch")
    if len(title) > 120:
        raise ValueError("Result title must be 120 characters or fewer")

    import io
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=False, data_only=True)
        ws = wb.active
    except Exception as exc:
        raise ValueError("The uploaded Excel file could not be read") from exc

    try:
        first_three = [list(r) for r in ws.iter_rows(min_row=1, max_row=3, values_only=True)]
        while len(first_three) < 3:
            first_three.append([])
        wide = _detect_wide_format(first_three)

        max_source_rows = 5000
        with connect() as c:
            skipped_students: list[dict] = []
            sem = c.execute("SELECT id,code,name FROM academic_semesters WHERE id=?", (semester_id,)).fetchone()
            if not sem:
                raise ValueError("Selected semester does not exist")
            cohort = c.execute(
                "SELECT 1 FROM students WHERE department=? AND batch=? LIMIT 1",
                (department, batch),
            ).fetchone()
            if not cohort:
                raise ValueError("Selected batch does not exist for this branch")

            if wide:
                parsed, mapping = _parse_wide_results(
                    ws=ws, header_rows=first_three, semester_id=semester_id,
                    department=department, batch=batch, c=c, sem=sem, max_source_rows=max_source_rows,
                    skipped_students=skipped_students,
                )
                source_format = "wide"
            else:
                headers = first_three[0]
                parsed, mapping = _parse_long_results(
                    ws=ws, headers=headers, semester_id=semester_id,
                    department=department, batch=batch, c=c, sem=sem, max_source_rows=max_source_rows,
                    skipped_students=skipped_students,
                )
                source_format = "long"

            if not parsed:
                if skipped_students:
                    raise ValueError("No registered student result rows were found in the Excel file")
                raise ValueError("No valid result rows were found in the Excel file")

            batch_cur = c.execute(
                "INSERT INTO result_batches(department,batch,semester_id,title,uploaded_by,source_filename) VALUES(?,?,?,?,?,?)",
                (department, batch, semester_id, title, admin_username, filename),
            )
            batch_id = int(batch_cur.lastrowid)
            for item in parsed:
                c.execute(
                    """
                    INSERT INTO result_items(
                        batch_id,roll_no,subject_code,subject_name,marks,max_marks,
                        internal_marks,external_marks,credits,grade,grade_point,result_status,sgpa,percentage
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        batch_id, item["roll_no"], item["subject_code"], item["subject_name"],
                        item["marks"], item["max_marks"], item["internal_marks"],
                        item["external_marks"], item["credits"], item["grade"],
                        item["grade_point"], item["result_status"], item["sgpa"], item["percentage"],
                    ),
                )
            audit(c, admin_username, "UPLOAD", "results", f"{department} / {sem['code']} — {title} — {len(parsed)} rows")
    finally:
        wb.close()

    return {
        "batch_id": batch_id,
        "department": department,
        "semester_id": semester_id,
        "semester_code": sem["code"],
        "title": title,
        "rows_imported": len(parsed),
        "students_affected": len({x["roll_no"] for x in parsed}),
        "source_format": source_format,
        "column_mapping": mapping.as_dict(),
        "skipped_students": skipped_students,
        "skipped_count": len(skipped_students),
    }


def build_students_template() -> bytes:
    """Build the official student-import template from the existing alias map."""
    from api.routes_students import BULK_IMPORT_COLUMN_MAP
    wb = Workbook()
    ws = wb.active
    ws.title = "Students"
    seen_fields: set[str] = set()
    headers: list[str] = []
    for alias_text, field_key in BULK_IMPORT_COLUMN_MAP.items():
        if field_key not in seen_fields:
            seen_fields.add(field_key)
            headers.append(alias_text)
    examples = {
        "Name": "Example Student",
        "Full Name Of The Student": "Example Student",
        "Hallticket": "24CSDS0001",
        "Hall Ticket": "24CSDS0001",
        "Roll No": "24CSDS0001",
        "Roll Number": "24CSDS0001",
        "Phone No": "9876543210",
        "Student Phone Number": "9876543210",
        "Student Email Id": "student@example.com",
        "Email": "student@example.com",
        "Parent Phone Number": "9876543211",
        "Parent Phone": "9876543211",
        "Address Of The Student": "Example Colony, Hyderabad",
        "Address": "Example Colony, Hyderabad",
        "Father's Name": "Example Parent",
        "Previous Roll Number": "",
        "Old Roll Number": "",
    }
    for col, header in enumerate(headers, 1):
        cell = ws.cell(1, col, header)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")
        cell.alignment = Alignment(horizontal="center")
        ws.cell(2, col, examples.get(header, "Example"))
        ws.column_dimensions[get_column_letter(col)].width = max(16, min(34, len(header) + 4))
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def build_results_template() -> bytes:
    import io
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    subject_blocks = [
        ("24CS301PC", "Digital Electronics"),
        ("24CS302PC", "Data Structures"),
        ("24CS303PC", "Object Oriented Programming"),
    ]
    ws.cell(1, 1, "S NO")
    ws.cell(1, 2, "H T NO")
    ws.cell(2, 1, "")
    ws.cell(2, 2, "")
    for c in (1, 2):
        ws.merge_cells(start_row=1, start_column=c, end_row=3, end_column=c)
    subheaders = ["IM", "EM", "TM", "G", "GP", "C"]
    for block_idx, (code, name) in enumerate(subject_blocks):
        start = 3 + block_idx * 6
        ws.merge_cells(start_row=1, start_column=start, end_row=1, end_column=start + 5)
        ws.merge_cells(start_row=2, start_column=start, end_row=2, end_column=start + 5)
        ws.cell(1, start, code)
        ws.cell(2, start, name)
        for offset, header in enumerate(subheaders):
            ws.cell(3, start + offset, header)
    sample = [1, "24CSDS0001", 36, 48, 84, "A+", 9, 3, 38, 37, 75, "A", 8, 3, 40, 46, 86, "A+", 9, 4]
    for col, value in enumerate(sample, 1):
        ws.cell(4, col, value)
    for row in ws.iter_rows(min_row=1, max_row=3, min_col=1, max_col=20):
        for cell in row:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="E2E8F0")
            cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "C4"
    widths = {1: 9, 2: 16}
    for col in range(3, 21):
        widths[col] = 13
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 24
    ws.row_dimensions[3].height = 22
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()

def get_student_results(*, roll_no: str) -> dict:
    with connect() as c:
        student = c.execute(
            "SELECT roll_no,name,department,batch FROM students WHERE roll_no=? AND active=1",
            (roll_no,),
        ).fetchone()
        if not student or not student.get("batch"):
            return {"student": dict(student) if student else None, "results": []}

        upload_batches = c.execute(
            """SELECT rb.id,rb.title,rb.created_at,rb.source_filename,rb.semester_id,
                      sem.code AS semester_code, sem.name AS semester_name
               FROM result_batches rb JOIN academic_semesters sem ON sem.id=rb.semester_id
               WHERE rb.department=? AND rb.batch=?
               ORDER BY sem.sort_order""",
            (student["department"], student["batch"]),
        ).fetchall()

        result_entries = []
        for upload_batch in upload_batches:
            rows = c.execute(
                """SELECT subject_code,subject_name,marks,max_marks,internal_marks,external_marks,credits,
                          grade,grade_point,result_status,sgpa,percentage
                   FROM result_items WHERE batch_id=? AND roll_no=? ORDER BY subject_name""",
                (upload_batch["id"], roll_no),
            ).fetchall()
            subjects = [dict(r) for r in rows]
            if not subjects:
                # This upload batch belongs to the student's cohort, but no
                # result_items row exists for this specific roll_no in it —
                # e.g. they weren't in the sheet, or joined the batch later.
                # Skip it rather than showing an empty "Marksheet" record.
                continue
            total_credits = sum(float(r.get("credits") or 0) for r in subjects)
            sgpa = next((str(r.get("sgpa")) for r in subjects if r.get("sgpa") not in (None, "")), None)
            raw_statuses = [str(r.get("result_status") or "").strip() for r in subjects if str(r.get("result_status") or "").strip()]
            if raw_statuses:
                result_status = "FAIL" if any("fail" in s.lower() for s in raw_statuses) else raw_statuses[0]
            else:
                result_status = "FAIL" if any(str(r.get("grade") or "").strip().upper() in {"F", "FAIL"} for r in subjects) else ("PASS" if subjects else None)
            result_entries.append({
                "batch": {
                    "id": int(upload_batch["id"]),
                    "title": upload_batch["title"],
                    "created_at": upload_batch["created_at"],
                    "source_filename": upload_batch["source_filename"],
                    "semester_code": upload_batch["semester_code"],
                    "semester_name": upload_batch["semester_name"],
                },
                "subjects": subjects,
                "total_credits": total_credits,
                "sgpa": sgpa,
                "result_status": result_status,
            })

        return {
            "student": {
                "roll_no": student["roll_no"],
                "name": student["name"],
                "department": student["department"],
            },
            "results": result_entries,
        }
