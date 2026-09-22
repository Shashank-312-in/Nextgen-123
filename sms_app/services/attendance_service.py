from datetime import date, datetime, timedelta, timezone
from contextlib import nullcontext
from pathlib import Path
import io
import re
from difflib import SequenceMatcher

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel

from excel_import import FieldSpec, MatchReport, match_headers, normalize_header
from sms_app.services.timetable_service import local_now

from database import audit, connect, IntegrityError

VALID_SESSION_TYPES = ("CLASS", "LAB")
VALID_CLASS_HOURS = (1, 2, 3)
LAB_HOURS = 3

ATTENDANCE_IMPORT_ALLOWED_EXT = {".xlsx", ".xlsm"}
ATTENDANCE_IMPORT_MAX_BYTES = 10 * 1024 * 1024
ATTENDANCE_IMPORT_MAX_ROWS = 25000

# Historical sheets are intentionally tolerant about the header wording but
# strict about the semantic fields needed to build a real attendance session.
ATTENDANCE_FIELD_ALIASES = {
    "roll_no": {"roll no", "roll number", "roll", "hall ticket", "hallticket", "h t no", "ht no", "student id"},
    "date": {"date", "attendance date", "class date", "session date"},
    "subject_code": {"subject code", "code", "subject id", "paper code"},
    "subject_name": {"subject name", "subject", "subject title", "paper name"},
    "status": {"status", "attendance", "attendance status", "present absent", "p a"},
    "session_type": {"session type", "type", "class lab", "class type"},
    "duration_hours": {"duration", "duration hours", "hours", "class hours"},
    "topic": {"topic", "today's topic", "todays topic", "class topic", "lecture topic"},
}

ATTENDANCE_FIELD_SPECS = [
    FieldSpec(key=key, aliases={normalize_header(v) for v in aliases}, required=key in {"roll_no", "date", "status"})
    for key, aliases in ATTENDANCE_FIELD_ALIASES.items()
]

_ATTENDANCE_STATUS_VALUES = {
    "present": "Present", "p": "Present", "1": "Present", "yes": "Present", "y": "Present", "true": "Present",
    "absent": "Absent", "a": "Absent", "0": "Absent", "no": "Absent", "n": "Absent", "false": "Absent",
}
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y")


def _attendance_import_cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_import_date(value, *, row_no):
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            excel_value = from_excel(value)
            parsed = excel_value.date() if isinstance(excel_value, datetime) else None
        except (TypeError, ValueError, OverflowError):
            parsed = None
        if parsed is None:
            raw = _attendance_import_cell(value)
            raise ValueError(f"Row {row_no}: invalid attendance date '{raw}'")
    else:
        raw = _attendance_import_cell(value)
        parsed = None
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError(f"Row {row_no}: invalid attendance date '{raw}'")
    if parsed > local_now().date():
        raise ValueError(f"Row {row_no}: attendance date cannot be in the future")
    return parsed.isoformat()


def _parse_import_status(value, *, row_no):
    if isinstance(value, bool):
        return "Present" if value else "Absent"
    raw = _attendance_import_cell(value).casefold()
    status = _ATTENDANCE_STATUS_VALUES.get(raw)
    if status:
        return status
    raise ValueError(f"Row {row_no}: status must be Present/Absent (accepted: P/A, 1/0, Yes/No)")


def _parse_import_session_type(value, *, row_no):
    raw = _attendance_import_cell(value).upper() if value not in (None, "") else "CLASS"
    if raw in {"CLASS", "THEORY", "LECTURE"}:
        return "CLASS"
    if raw in {"LAB", "PRACTICAL", "PRACTICALS"}:
        return "LAB"
    raise ValueError(f"Row {row_no}: session type must be CLASS or LAB")


def _parse_import_duration(value, session_type, *, row_no):
    if session_type == "LAB":
        return LAB_HOURS
    if value in (None, ""):
        return 1
    raw = _attendance_import_cell(value)
    try:
        hours = int(float(raw))
    except (TypeError, ValueError):
        raise ValueError(f"Row {row_no}: duration must be 1, 2, or 3 hours")
    if hours not in VALID_CLASS_HOURS:
        raise ValueError(f"Row {row_no}: duration must be 1, 2, or 3 hours")
    return hours


def _subject_key(value):
    return re.sub(r"[^A-Z0-9]+", "", _attendance_import_cell(value).upper())


def _subject_name_key(value):
    return " ".join(_attendance_import_cell(value).casefold().split())


def _resolve_import_subject(c, *, semester_id, subject_code, subject_name, row_no):
    code = _attendance_import_cell(subject_code)
    name = _attendance_import_cell(subject_name)
    if not code and not name:
        raise ValueError(f"Row {row_no}: Subject Code or Subject Name is required")

    # Historical attendance must be able to target a real subject that has
    # since been deactivated. The subject's semester is the authoritative
    # scope; `active` is a current-usage flag, not a historical-existence flag.
    rows = c.execute(
        "SELECT id, code, name FROM subjects WHERE semester_id=%s ORDER BY id",
        (semester_id,),
    ).fetchall()
    if not rows:
        raise ValueError("Selected semester has no subjects")

    by_code = {str(r["code"]).strip().casefold(): r for r in rows}
    by_code_norm = {_subject_key(r["code"]): r for r in rows if _subject_key(r["code"])}
    exact_names: dict[str, list] = {}
    for row in rows:
        key = _subject_name_key(row["name"])
        if key:
            exact_names.setdefault(key, []).append(row)

    code_match = None
    name_match = None
    if code:
        code_match = by_code.get(code.casefold()) or by_code_norm.get(_subject_key(code))
    if name:
        name_candidates = exact_names.get(_subject_name_key(name), [])
        if len(name_candidates) > 1:
            raise ValueError(f"Row {row_no}: Subject Name is ambiguous in the selected semester; use Subject Code")
        name_match = name_candidates[0] if name_candidates else None

    if code_match and name_match and int(code_match["id"]) != int(name_match["id"]):
        raise ValueError(f"Row {row_no}: Subject Code and Subject Name refer to different subjects")
    if code_match:
        return code_match
    if name_match:
        return name_match

    # Deliberate second-stage tolerance: unique contains/fuzzy name match.
    candidates = []
    needle = _subject_name_key(name) if name else _attendance_import_cell(code).casefold()
    if needle:
        for row in rows:
            code_text = str(row["code"]).casefold()
            name_text = _subject_name_key(row["name"])
            if needle in name_text or (code and needle in code_text):
                candidates.append(row)
        if len(candidates) == 1:
            return candidates[0]

        scored = []
        for row in rows:
            target = name_text = _subject_name_key(row["name"])
            score = SequenceMatcher(None, needle, target).ratio()
            if code:
                score = max(score, SequenceMatcher(None, needle, str(row["code"]).casefold()).ratio())
            if score >= 0.88:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0] + 0.03):
            return scored[0][1]

    display = code or name
    raise ValueError(f"Row {row_no}: could not resolve subject '{display}' in the selected semester")


def _hod_scoped_student(c, *, roll_no, hod_username):
    return c.execute(
        """
        SELECT roll_no, name
        FROM students
        WHERE roll_no=%s
          AND department='CSD'
          AND active=1
          AND LOWER(COALESCE(hod_username,''))=LOWER(%s)
        LIMIT 1
        """,
        (roll_no, hod_username),
    ).fetchone()


def upload_attendance_excel(*, raw: bytes, filename: str, semester_id: int, hod_username: str) -> dict:
    """Import historical attendance as one session per date/subject/type.

    Import is an administrative backfill, so it intentionally writes
    attendance_records directly instead of calling save_register(), which
    protects the normal faculty 24-hour editing path. No absentee SMS is
    queued for imported historical rows.
    """
    if not raw:
        raise ValueError("No attendance file was selected")
    if len(raw) > ATTENDANCE_IMPORT_MAX_BYTES:
        raise ValueError("Attendance Excel file must be smaller than 10MB")
    if Path(filename or "").suffix.lower() not in ATTENDANCE_IMPORT_ALLOWED_EXT:
        raise ValueError("Attendance must be an .xlsx or .xlsm file")
    if not hod_username:
        raise ValueError("A HOD account is required")

    try:
        wb = load_workbook(io.BytesIO(raw), read_only=False, data_only=True)
        ws = wb.active
    except Exception as exc:
        raise ValueError("The uploaded Excel file could not be read") from exc

    try:
        headers = [str(v or "").strip() for v in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), [])]
        mapping = match_headers(headers, ATTENDANCE_FIELD_SPECS)
        missing = mapping.missing_required(ATTENDANCE_FIELD_SPECS)
        if missing:
            readable = {"roll_no": "Roll Number", "date": "Date", "status": "Status"}
            raise ValueError("Missing required Excel columns: " + ", ".join(readable.get(x, x) for x in missing))
        cols = mapping.field_index()

        rows = []
        with connect() as c:
            sem = c.execute("SELECT id,code,name FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
            if not sem:
                raise ValueError("Selected semester does not exist")

            subject_cache: dict[tuple[str, str], dict] = {}
            student_cache: dict[str, dict | None] = {}
            seen_student_groups: set[tuple[str, str, int, str]] = set()
            group_topics: dict[tuple[str, int, str], str] = {}
            group_topic_explicit: set[tuple[str, int, str]] = set()
            group_duration: dict[tuple[str, int, str], int] = {}
            group_duration_explicit: set[tuple[str, int, str]] = set()
            skipped_students: list[dict] = []

            for excel_row_no, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                if excel_row_no > ATTENDANCE_IMPORT_MAX_ROWS + 1:
                    raise ValueError(f"Attendance sheet cannot contain more than {ATTENDANCE_IMPORT_MAX_ROWS} data rows")
                vals = list(values)
                get = lambda field: vals[cols[field]] if field in cols and cols[field] < len(vals) else None
                raw_roll = _attendance_import_cell(get("roll_no"))
                raw_date = get("date")
                raw_code = get("subject_code")
                raw_name = get("subject_name")
                raw_status = get("status")
                raw_type = get("session_type")
                raw_duration = get("duration_hours")
                raw_topic = get("topic")

                if not any(v not in (None, "") for v in (raw_roll, raw_date, raw_code, raw_name, raw_status, raw_type, raw_duration, raw_topic)):
                    continue
                if not raw_roll:
                    raise ValueError(f"Row {excel_row_no}: Roll Number is required")

                attendance_date = _parse_import_date(raw_date, row_no=excel_row_no)
                status = _parse_import_status(raw_status, row_no=excel_row_no)
                session_type = _parse_import_session_type(raw_type, row_no=excel_row_no)
                duration_hours = _parse_import_duration(raw_duration, session_type, row_no=excel_row_no)
                topic_raw = _attendance_import_cell(raw_topic)
                topic = topic_raw or "Imported attendance"
                topic_is_explicit = bool(topic_raw)
                if len(topic) > 300:
                    raise ValueError(f"Row {excel_row_no}: topic must be 300 characters or fewer")
                duration_is_explicit = raw_duration not in (None, "")

                subject_key = (_attendance_import_cell(raw_code).casefold(), _subject_name_key(raw_name))
                if subject_key not in subject_cache:
                    subject_cache[subject_key] = _resolve_import_subject(
                        c, semester_id=semester_id, subject_code=raw_code, subject_name=raw_name, row_no=excel_row_no,
                    )
                subject = subject_cache[subject_key]
                student_key = raw_roll.casefold()
                if student_key not in student_cache:
                    student_cache[student_key] = _hod_scoped_student(c, roll_no=raw_roll, hod_username=hod_username)
                student = student_cache[student_key]
                if not student:
                    skipped_students.append({"row": excel_row_no, "roll_no": raw_roll, "reason": "Student is not registered in this HOD's CSD scope"})
                    continue

                group_key = (attendance_date, int(subject["id"]), session_type)
                topic_key = (attendance_date, int(subject["id"]), session_type)
                previous_topic = group_topics.get(topic_key)
                if topic_is_explicit:
                    if topic_key in group_topic_explicit and previous_topic != topic:
                        raise ValueError(f"Row {excel_row_no}: conflicting topics for the same date/subject/session type")
                    group_topics[topic_key] = topic
                    group_topic_explicit.add(topic_key)
                elif previous_topic is None:
                    group_topics[topic_key] = topic

                previous_duration = group_duration.get(topic_key)
                if duration_is_explicit:
                    if topic_key in group_duration_explicit and previous_duration != duration_hours:
                        raise ValueError(f"Row {excel_row_no}: conflicting durations for the same date/subject/session type")
                    group_duration[topic_key] = duration_hours
                    group_duration_explicit.add(topic_key)
                elif previous_duration is None:
                    group_duration[topic_key] = duration_hours

                student_group_key = (attendance_date, str(subject["id"]), session_type, student_key)
                if student_group_key in seen_student_groups:
                    raise ValueError(f"Row {excel_row_no}: duplicate attendance row for {raw_roll} on {attendance_date} for {subject['code']}")
                seen_student_groups.add(student_group_key)
                rows.append({
                    "row": excel_row_no,
                    "roll_no": student["roll_no"],
                    "date": attendance_date,
                    "subject_id": int(subject["id"]),
                    "subject_code": subject["code"],
                    "session_type": session_type,
                    "duration_hours": duration_hours,
                    "topic": topic,
                    "status": status,
                })

            if not rows and not skipped_students:
                raise ValueError("No valid attendance rows were found in the Excel file")

            grouped: dict[tuple[str, int, str], list[dict]] = {}
            for item in rows:
                grouped.setdefault((item["date"], item["subject_id"], item["session_type"]), []).append(item)

            sessions_created = 0
            sessions_existing = 0
            records_written = 0
            students_affected = {item["roll_no"] for item in rows}

            # One transaction covers the whole import: a bad DB write cannot
            # leave half of a historical sheet committed.
            for (attendance_date, subject_id, session_type), items in grouped.items():
                existing = c.execute(
                    "SELECT id, topic, duration_hours FROM attendance_sessions WHERE attendance_date=%s AND subject_id=%s AND faculty_username=%s AND session_type=%s",
                    (attendance_date, subject_id, hod_username, session_type),
                ).fetchone()
                if existing:
                    session_id = int(existing["id"])
                    existing_topic = _attendance_import_cell(existing.get("topic"))
                    existing_duration = int(existing.get("duration_hours") or 1)
                    if (attendance_date, subject_id, session_type) in group_topic_explicit and existing_topic != group_topics[(attendance_date, subject_id, session_type)]:
                        raise ValueError(
                            f"Conflicting topic for existing attendance session on {attendance_date} for subject {items[0]['subject_code']}"
                        )
                    if (attendance_date, subject_id, session_type) in group_duration_explicit and existing_duration != group_duration[(attendance_date, subject_id, session_type)]:
                        raise ValueError(
                            f"Conflicting duration for existing attendance session on {attendance_date} for subject {items[0]['subject_code']}"
                        )
                    updates = []
                    params = []
                    if (attendance_date, subject_id, session_type) in group_topic_explicit:
                        updates.append("topic=%s")
                        params.append(group_topics[(attendance_date, subject_id, session_type)])
                    if (attendance_date, subject_id, session_type) in group_duration_explicit:
                        updates.append("duration_hours=%s")
                        params.append(group_duration[(attendance_date, subject_id, session_type)])
                    if updates:
                        params.append(session_id)
                        c.execute(
                            f"UPDATE attendance_sessions SET {', '.join(updates)}, updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                            tuple(params),
                        )
                    sessions_existing += 1
                else:
                    subject = c.execute("SELECT code, name FROM subjects WHERE id=%s", (subject_id,)).fetchone()
                    if not subject:
                        raise ValueError(f"Subject {subject_id} was removed during import")
                    session = get_or_create_session(
                        attendance_date=attendance_date,
                        semester_id=semester_id,
                        subject_id=subject_id,
                        faculty_username=hod_username,
                        session_type=session_type,
                        duration_hours=items[0]["duration_hours"],
                        topic=items[0]["topic"],
                        actor=hod_username,
                        connection=c,
                    )
                    session_id = int(session["id"])
                    sessions_created += 1

                for item in items:
                    c.execute(
                        """
                        INSERT INTO attendance_records(session_id,roll_no,status,marked_by)
                        VALUES(%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE status=VALUES(status), marked_by=VALUES(marked_by), updated_at=CURRENT_TIMESTAMP
                        """,
                        (session_id, item["roll_no"], item["status"], hod_username),
                    )
                    records_written += 1
                c.execute("UPDATE attendance_sessions SET saved_at=CURRENT_TIMESTAMP WHERE id=%s", (session_id,))

            audit(c, hod_username, "IMPORT", "attendance",
                  f"{sem['code']} — {len(rows)} records / {len(grouped)} sessions; skipped={len(skipped_students)}")

        return {
            "semester_id": int(semester_id),
            "semester_code": sem["code"],
            "sessions_created": sessions_created,
            "sessions_updated": sessions_existing,
            "records_written": records_written,
            "students_affected": len(students_affected),
            "skipped_students": skipped_students,
            "skipped_count": len(skipped_students),
            "column_mapping": mapping.as_dict(),
        }
    finally:
        wb.close()


def build_attendance_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    headers = ["Roll No", "Date", "Subject Code", "Subject Name", "Status", "Session Type", "Duration Hours", "Topic"]
    sample = ["24CSD0001", date.today().strftime("%Y-%m-%d"), "24CS301PC", "Data Structures", "P", "CLASS", 1, "Imported attendance"]
    for col, value in enumerate(headers, 1):
        cell = ws.cell(1, col, value)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DCEBFA")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for col, value in enumerate(sample, 1):
        ws.cell(2, col, value)
    ws.freeze_panes = "A2"
    widths = [18, 14, 18, 28, 14, 16, 18, 30]
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.auto_filter.ref = "A1:H2"

    guide = wb.create_sheet("Instructions")
    guide_rows = [
        ["Field", "Required", "Accepted / Notes"],
        ["Roll No", "Yes", "Roll No / Roll Number / Hall Ticket / HT No"],
        ["Date", "Yes", "YYYY-MM-DD preferred; common Indian date formats are accepted"],
        ["Subject Code", "One of code/name", "Exact code match first; tolerant unique matching follows"],
        ["Subject Name", "One of code/name", "Use the official subject name when code is unavailable"],
        ["Status", "Yes", "Present/Absent, P/A, 1/0, Yes/No"],
        ["Session Type", "No", "CLASS or LAB; defaults to CLASS"],
        ["Duration Hours", "No", "1, 2, or 3 for CLASS; LAB is always forced to 3"],
        ["Topic", "No", "Defaults to Imported attendance; maximum 300 characters"],
    ]
    for r, values in enumerate(guide_rows, 1):
        for cidx, value in enumerate(values, 1):
            guide.cell(r, cidx, value)
            if r == 1:
                guide.cell(r, cidx).font = Font(bold=True)
                guide.cell(r, cidx).fill = PatternFill("solid", fgColor="DCEBFA")
    for col, width in enumerate([20, 18, 76], 1):
        guide.column_dimensions[get_column_letter(col)].width = width
    out = io.BytesIO()
    wb.save(out)
    wb.close()
    return out.getvalue()


def validate_session_payload(*, attendance_date, semester_id, subject_id, faculty_username,
                             session_type, duration_hours, topic):
    try:
        datetime.strptime(attendance_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("Select a valid attendance date")
    if not semester_id:
        raise ValueError("Select a semester")
    if not subject_id:
        raise ValueError("Select a subject")
    if not faculty_username:
        raise ValueError("A faculty account is required")
    session_type = str(session_type or "").upper()
    if session_type not in VALID_SESSION_TYPES:
        raise ValueError("Choose Class or Lab")
    try:
        duration_hours = int(duration_hours)
    except (TypeError, ValueError):
        raise ValueError("Choose the session duration")
    if session_type == "LAB":
        duration_hours = LAB_HOURS
    elif session_type == "CLASS" and duration_hours not in VALID_CLASS_HOURS:
        raise ValueError("Class duration must be 1, 2, or 3 hours")
    topic = str(topic or "").strip()
    if not topic:
        raise ValueError("Enter today's topic")
    if len(topic) > 300:
        raise ValueError("Today's topic must be 300 characters or fewer")
    return session_type, duration_hours, topic


def list_semesters():
    with connect() as c:
        return c.execute("SELECT id, code, name FROM academic_semesters ORDER BY sort_order").fetchall()


def list_all_semesters():
    """HOD-facing semester management view: every semester, active AND
    inactive, so HOD can see and toggle 1st Year (or any other semester)
    on/off. Unlike list_semesters() (used everywhere else — subject
    pickers, faculty attendance workflow, etc.) which only returns active
    ones, so a deactivated semester disappears from normal use immediately.
    """
    with connect() as c:
        return c.execute("SELECT id, code, name, sort_order, active FROM academic_semesters ORDER BY sort_order").fetchall()


def set_semester_active(*, semester_id, active, actor):
    with connect() as c:
        row = c.execute("SELECT * FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not row:
            raise ValueError("Semester was not found")
        c.execute("UPDATE academic_semesters SET active=%s WHERE id=%s", (1 if active else 0, semester_id))
        audit(c, actor, "STATUS", "semester", f"{row['code']} -> {'active' if active else 'inactive'}")


def faculty_semester_ids(faculty_username):
    """Semester ids a given faculty member teaches in (derived from their
    subject assignments), used to scope Academic Calendar to only the
    semesters that faculty member is relevant to.
    """
    with connect() as c:
        rows = c.execute("""
            SELECT DISTINCT s.semester_id
            FROM subjects s JOIN subject_faculty sf ON sf.subject_id = s.id
            WHERE sf.faculty_username = %s AND s.active = 1
        """, (faculty_username,)).fetchall()
        return [r["semester_id"] for r in rows]


def academic_calendar_for_semesters(semester_ids=None):
    """Semester + Timetable/Calendar upload info, joined, ordered by
    sort_order. semester_ids=None returns every active semester (HOD view);
    a list scopes to just those semesters (Faculty/Student views).
    """
    with connect() as c:
        sql = """
            SELECT sem.id AS semester_id, sem.code, sem.name, sem.sort_order,
                   ac.timetable_path, ac.timetable_updated_at, ac.timetable_updated_by,
                   ac.calendar_path, ac.calendar_updated_at, ac.calendar_updated_by
            FROM academic_semesters sem
            LEFT JOIN academic_calendar ac ON ac.semester_id = sem.id
            WHERE sem.active = 1
        """
        args = []
        if semester_ids is not None:
            if not semester_ids:
                return []
            placeholders = ",".join("%s" for _ in semester_ids)
            sql += f" AND sem.id IN ({placeholders})"
            args = list(semester_ids)
        sql += " ORDER BY sem.sort_order"
        return c.execute(sql, args).fetchall()


def save_calendar_upload(*, semester_id, kind, path, actor):
    """kind: 'timetable' or 'calendar'. Upserts the academic_calendar row
    for this semester — HOD-only write path (enforced at the route level).
    """
    if kind not in ("timetable", "calendar"):
        raise ValueError("Invalid upload kind")
    path_col = f"{kind}_path"
    at_col = f"{kind}_updated_at"
    by_col = f"{kind}_updated_by"
    with connect() as c:
        sem = c.execute("SELECT code FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not sem:
            raise ValueError("Semester was not found")
        c.execute(f"""
            INSERT INTO academic_calendar(semester_id, {path_col}, {at_col}, {by_col})
            VALUES(%s, %s, CURRENT_TIMESTAMP, %s)
            ON DUPLICATE KEY UPDATE
                {path_col}=VALUES({path_col}), {at_col}=CURRENT_TIMESTAMP, {by_col}=VALUES({by_col})
        """, (semester_id, path, actor))
        audit(c, actor, "UPLOAD", "academic_calendar", f"{sem['code']} ({kind})")


def delete_calendar_upload(*, semester_id, kind, actor):
    """kind: 'timetable' or 'calendar'. Clears the path for this semester."""
    if kind not in ("timetable", "calendar"):
        raise ValueError("Invalid upload kind")
    path_col = f"{kind}_path"
    at_col = f"{kind}_updated_at"
    by_col = f"{kind}_updated_by"
    with connect() as c:
        sem = c.execute("SELECT code FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not sem:
            raise ValueError("Semester was not found")
        c.execute(f"""
            UPDATE academic_calendar SET {path_col}=NULL, {at_col}=CURRENT_TIMESTAMP, {by_col}=%s
            WHERE semester_id=%s
        """, (actor, semester_id))
        audit(c, actor, "DELETE_UPLOAD", "academic_calendar", f"{sem['code']} ({kind})")


def list_subjects(semester_id, username=None, role=None):
    with connect() as c:
        if role == "FACULTY":
            # SECURITY/LOGIC: faculty must see only subjects explicitly
            # assigned to them. Never fall back to the semester-wide subject
            # list when their assignment set is empty. That fallback made a
            # faculty member appear able to mark attendance for another
            # faculty's subject.
            return c.execute("""
                SELECT s.id,s.code,s.name,s.has_lab
                FROM subjects s
                JOIN subject_faculty sf ON sf.subject_id=s.id
                WHERE s.semester_id=%s AND s.active=1 AND sf.faculty_username=%s
                ORDER BY s.name
            """, (semester_id, username)).fetchall()
        return c.execute("SELECT id,code,name,has_lab FROM subjects WHERE semester_id=%s AND active=1 ORDER BY name", (semester_id,)).fetchall()


def subject_faculty_map():
    """Subject -> assigned faculty, grouped by semester. Inverse of
    faculty_teaching_hours() (which is faculty -> aggregate hours); this is
    the "which faculty teaches this subject" view Boss asked for
    (HANDOFF.md Session 3, item 5). Uses only existing tables/columns —
    no schema change needed.
    """
    with connect() as c:
        rows = c.execute("""
            SELECT sem.id AS semester_id, sem.code AS semester_code, sem.name AS semester_name,
                   s.id AS subject_id, s.code AS subject_code, s.name AS subject_name, s.has_lab,
                   sf.faculty_username, u.full_name AS faculty_full_name
            FROM subjects s
            JOIN academic_semesters sem ON sem.id = s.semester_id
            LEFT JOIN subject_faculty sf ON sf.subject_id = s.id
            LEFT JOIN users u ON u.username = sf.faculty_username
            WHERE s.active = 1
            ORDER BY sem.sort_order, s.name, u.full_name
        """).fetchall()

    semesters: dict[int, dict] = {}
    for r in rows:
        sem = semesters.setdefault(r["semester_id"], {
            "semester_id": r["semester_id"], "semester_code": r["semester_code"],
            "semester_name": r["semester_name"], "subjects": {},
        })
        subj = sem["subjects"].setdefault(r["subject_id"], {
            "subject_id": r["subject_id"], "subject_code": r["subject_code"],
            "subject_name": r["subject_name"], "has_lab": r["has_lab"], "faculty": [],
        })
        if r["faculty_username"]:
            subj["faculty"].append({
                "faculty_username": r["faculty_username"],
                "full_name": r["faculty_full_name"] or r["faculty_username"],
            })

    return [
        {**sem, "subjects": list(sem["subjects"].values())}
        for sem in semesters.values()
    ]


def subject_details(subject_id):
    with connect() as c:
        return c.execute("""
            SELECT s.*, sem.code AS semester_code, sem.name AS semester_name
            FROM subjects s JOIN academic_semesters sem ON sem.id=s.semester_id
            WHERE s.id=%s
        """, (subject_id,)).fetchone()


def validate_subject_payload(*, code, name, has_lab):
    code = str(code or "").strip().upper()
    name = str(name or "").strip()
    if not code:
        raise ValueError("Subject code is required")
    if not name:
        raise ValueError("Subject name is required")
    return code, name, 1 if has_lab else 0


def all_subjects_admin():
    """HOD-facing subject management view: every subject (active AND
    inactive, unlike subject_faculty_map()/list_subjects() which only
    show active ones), grouped by semester, with the list of assigned
    faculty usernames so the assignment form can pre-check them.
    """
    with connect() as c:
        semesters = c.execute(
            "SELECT id, code, name FROM academic_semesters WHERE active=1 ORDER BY sort_order"
        ).fetchall()
        subjects = c.execute("""
            SELECT s.id, s.semester_id, s.code, s.name, s.has_lab, s.active
            FROM subjects s ORDER BY s.semester_id, s.name
        """).fetchall()
        assigned = c.execute("""
            SELECT sf.subject_id, sf.faculty_username, u.full_name
            FROM subject_faculty sf JOIN users u ON u.username = sf.faculty_username
        """).fetchall()

    by_subject: dict[int, list[dict]] = {}
    for r in assigned:
        by_subject.setdefault(r["subject_id"], []).append(
            {"username": r["faculty_username"], "full_name": r["full_name"] or r["faculty_username"]}
        )

    subjects_by_sem: dict[int, list[dict]] = {}
    for s in subjects:
        subjects_by_sem.setdefault(s["semester_id"], []).append({
            "id": s["id"], "code": s["code"], "name": s["name"],
            "has_lab": s["has_lab"], "active": s["active"],
            "faculty": by_subject.get(s["id"], []),
        })

    return [
        {"id": sem["id"], "code": sem["code"], "name": sem["name"],
         "subjects": subjects_by_sem.get(sem["id"], [])}
        for sem in semesters
    ]


def create_subject(*, semester_id, code, name, has_lab, actor):
    code, name, has_lab = validate_subject_payload(code=code, name=name, has_lab=has_lab)
    with connect() as c:
        if not c.execute("SELECT 1 FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone():
            raise ValueError("Select a valid semester")
        cur = c.execute(
            "INSERT INTO subjects(semester_id,code,name,has_lab) VALUES(%s,%s,%s,%s)",
            (semester_id, code, name, has_lab),
        )
        audit(c, actor, "CREATE", "subject", f"{code} - {name} (semester={semester_id})")
        return cur.lastrowid


def update_subject(*, subject_id, code, name, has_lab, actor):
    code, name, has_lab = validate_subject_payload(code=code, name=name, has_lab=has_lab)
    with connect() as c:
        row = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Subject was not found")
        c.execute("UPDATE subjects SET code=%s, name=%s, has_lab=%s WHERE id=%s", (code, name, has_lab, subject_id))
        audit(c, actor, "UPDATE", "subject", f"{subject_id}: {row['code']} - {row['name']} -> {code} - {name}")


def set_subject_active(*, subject_id, active, actor):
    with connect() as c:
        row = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Subject was not found")
        c.execute("UPDATE subjects SET active=%s WHERE id=%s", (1 if active else 0, subject_id))
        audit(c, actor, "STATUS", "subject", f"{row['code']} -> {'active' if active else 'inactive'}")


def delete_subject(*, subject_id, actor):
    with connect() as c:
        row = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Subject was not found")
        sess = c.execute("SELECT COUNT(*) AS cnt FROM attendance_sessions WHERE subject_id=%s", (subject_id,)).fetchone()
        if sess and sess["cnt"] > 0:
            raise ValueError("Cannot delete subject with existing attendance sessions. Please deactivate it instead.")
        c.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))
        audit(c, actor, "DELETE", "subject", f"Deleted subject {row['code']} - {row['name']}")



def set_subject_faculty(*, subject_id, faculty_usernames, actor):
    """Replaces the full assigned-faculty set for a subject with
    faculty_usernames (a list of active FACULTY usernames). Editable by
    HOD any time — each subject can be given its own distinct faculty.
    """
    with connect() as c:
        subject = c.execute("SELECT * FROM subjects WHERE id=%s", (subject_id,)).fetchone()
        if not subject:
            raise ValueError("Subject was not found")
        valid = {
            r["username"] for r in c.execute(
                "SELECT username FROM users WHERE role='FACULTY' AND active=1"
            ).fetchall()
        }
        chosen = [u for u in dict.fromkeys(faculty_usernames or []) if u in valid]
        c.execute("DELETE FROM subject_faculty WHERE subject_id=%s", (subject_id,))
        for username in chosen:
            c.execute("INSERT INTO subject_faculty(subject_id,faculty_username) VALUES(%s,%s)", (subject_id, username))
        audit(c, actor, "UPDATE", "subject_faculty",
              f"{subject['code']}: faculty=[{', '.join(chosen) or '—'}]")


def get_or_create_session(*, attendance_date, semester_id, subject_id, faculty_username,
                          session_type, duration_hours, topic, actor, connection=None):
    session_type, duration_hours, topic = validate_session_payload(
        attendance_date=attendance_date, semester_id=semester_id, subject_id=subject_id,
        faculty_username=faculty_username, session_type=session_type,
        duration_hours=duration_hours, topic=topic,
    )
    with (nullcontext(connection) if connection is not None else connect()) as c:
        faculty = c.execute(
            "SELECT username, role, department, hod_username FROM users WHERE username=%s AND active=1",
            (faculty_username,),
        ).fetchone()
        if not faculty:
            raise ValueError("Faculty account is not active")
        hod_username = faculty["hod_username"]
        if faculty["role"] == "HOD" and faculty["username"] != "admin":
            hod_username = faculty_username
        elif not hod_username or hod_username == "admin":
            from database import resolve_hod_for_department
            dept_hod = resolve_hod_for_department(c, faculty.get("department") or "CSD")
            if dept_hod:
                hod_username = dept_hod
        if not hod_username:
            raise ValueError("This faculty account is not assigned to a HOD scope")
        if faculty["role"] == "FACULTY":
            assigned = c.execute(
                "SELECT 1 FROM subject_faculty WHERE subject_id=%s AND faculty_username=%s",
                (subject_id, faculty_username),
            ).fetchone()
            if not assigned:
                raise ValueError("This subject is not assigned to the selected faculty account")

        row = c.execute("""
            SELECT * FROM attendance_sessions
            WHERE attendance_date=%s AND subject_id=%s AND faculty_username=%s AND session_type=%s
        """, (attendance_date, subject_id, faculty_username, session_type)).fetchone()
        if row:
            # Legacy sessions without an owner are repaired only from the
            # authenticated faculty's current HOD scope. Never guess from
            # physical location or another gateway.
            if not row.get("hod_username") or (row.get("hod_username") == "admin" and hod_username != "admin"):
                c.execute("UPDATE attendance_sessions SET hod_username=%s WHERE id=%s", (hod_username, row["id"]))
                row = c.execute("SELECT * FROM attendance_sessions WHERE id=%s", (row["id"],)).fetchone()
            return row
        try:
            cur = c.execute("""
                INSERT INTO attendance_sessions(
                    attendance_date,semester_id,subject_id,faculty_username,hod_username,
                    session_type,duration_hours,topic,created_by
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (attendance_date, semester_id, subject_id, faculty_username, hod_username,
                  session_type, duration_hours, topic, actor))
        except IntegrityError:
            # Concurrent register opens can race between SELECT and INSERT.
            # The unique key is the final authority; fetch the row created by
            # the winner instead of surfacing a duplicate-key 500.
            row = c.execute("""
                SELECT * FROM attendance_sessions
                WHERE attendance_date=%s AND subject_id=%s AND faculty_username=%s AND session_type=%s
            """, (attendance_date, subject_id, faculty_username, session_type)).fetchone()
            if row:
                return row
            raise
        audit(c, actor, "CREATE", "attendance_session",
              f"session={cur.lastrowid}; subject={subject_id}; type={session_type}; hours={duration_hours}")
        return c.execute("SELECT * FROM attendance_sessions WHERE id=%s", (cur.lastrowid,)).fetchone()


def session_details(session_id):
    with connect() as c:
        return c.execute("""
            SELECT a.*, s.code AS subject_code, s.name AS subject_name,
                   sem.code AS semester_code, sem.name AS semester_name,
                   u.full_name AS faculty_name
            FROM attendance_sessions a
            JOIN subjects s ON s.id=a.subject_id
            JOIN academic_semesters sem ON sem.id=a.semester_id
            LEFT JOIN users u ON u.username=a.faculty_username
            WHERE a.id=%s
        """, (session_id,)).fetchone()


def session_is_editable(session, role):
    if role in ("HOD", "ADMIN"):
        return True
    # — UTC-consistent comparison
    # WHY: SQLite's CURRENT_TIMESTAMP (what created_at is stored with) is
    # always UTC, but formatted as a plain "YYYY-MM-DD HH:MM:SS" string
    # with no "Z" or offset — so the old .replace("Z","+00:00") was a
    # no-op here, and fromisoformat() produced a NAIVE datetime that is
    # secretly UTC-valued. Comparing that against datetime.now() (naive
    # LOCAL time) silently mixes timezones: on any server whose local
    # time is ahead of UTC (e.g. IST, UTC+5:30), the 24h edit window
    # appears to expire that many hours early, locking faculty out of
    # legitimate same-day corrections. Fix: treat created_at as UTC
    # explicitly and compare against utcnow(), both timezone-aware.
    created = datetime.fromisoformat(str(session["created_at"]).replace("Z", "")).replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return now <= created + timedelta(hours=24)


def load_register(session_id):
    with connect() as c:
        session = c.execute(
            "SELECT * FROM attendance_sessions WHERE id=%s",
            (session_id,),
        ).fetchone()

        if not session or not session.get("hod_username"):
            raise ValueError("Attendance session has no HOD ownership assigned")

        students = c.execute(
            """
            SELECT st.roll_no, st.name
            FROM students st
            WHERE st.department='CSD'
              AND LOWER(COALESCE(st.hod_username,''))=LOWER(%s)
              AND st.active=1
              AND st.current_semester_id=%s
            ORDER BY st.roll_no
            """,
            (
                session["hod_username"],
                session["semester_id"],
            ),
        ).fetchall()

        if not students and session.get("hod_username") == "admin":
            from database import resolve_hod_for_department
            dept_hod = resolve_hod_for_department(c, "CSD")
            if dept_hod and dept_hod != "admin":
                dept_students = c.execute(
                    """
                    SELECT st.roll_no, st.name
                    FROM students st
                    WHERE st.department='CSD'
                      AND LOWER(COALESCE(st.hod_username,''))=LOWER(%s)
                      AND st.active=1
                      AND st.current_semester_id=%s
                    ORDER BY st.roll_no
                    """,
                    (
                        dept_hod,
                        session["semester_id"],
                    ),
                ).fetchall()
                if dept_students:
                    students = dept_students
                    c.execute("UPDATE attendance_sessions SET hod_username=%s WHERE id=%s", (dept_hod, session_id))

        existing = {
            r["roll_no"]: r["status"]
            for r in c.execute(
                """
                SELECT roll_no,status
                FROM attendance_records
                WHERE session_id=%s
                """,
                (session_id,),
            ).fetchall()
        }

    return students, existing


def set_student_semester(*, roll_no, semester_id, actor, effective_from=None):
    """Change a student's current semester."""
    with connect() as c:
        student = c.execute(
            """
            SELECT roll_no, name, current_semester_id
            FROM students
            WHERE roll_no=%s
              AND department='CSD'
            """,
            (roll_no,),
        ).fetchone()

        if not student:
            raise ValueError("Student not found")

        old_semester_id = student["current_semester_id"]

        c.execute(
            """
            UPDATE students
            SET current_semester_id=%s
            WHERE roll_no=%s
              AND department='CSD'
            """,
            (semester_id, roll_no),
        )

        audit(
            c,
            actor,
            "UPDATE",
            "student_semester",
            f"{roll_no}: {old_semester_id} -> {semester_id}",
        )


def month_register(*, faculty_username, semester_id, subject_id, year, month):
    """Build the month/register view strictly from: assigned subject, the
    selected semester, actual sessions conducted by that faculty/department, and central
    holiday rows. Calendar days with no session are blank (not A)."""
    import calendar

    first_day = datetime(int(year), int(month), 1).date()
    last_day = datetime(int(year), int(month), calendar.monthrange(int(year), int(month))[1]).date()
    with connect() as c:
        faculty = c.execute(
            "SELECT username,role,hod_username,full_name,department FROM users WHERE username=%s AND active=1",
            (faculty_username,),
        ).fetchone()
        if not faculty:
            raise ValueError("Faculty account is not active")

        is_hod_or_admin = faculty["role"] in ("HOD", "ADMIN")

        if faculty["role"] == "FACULTY":
            assigned = c.execute(
                "SELECT 1 FROM subject_faculty WHERE subject_id=%s AND faculty_username=%s",
                (subject_id, faculty_username),
            ).fetchone()
            if not assigned:
                has_sess = c.execute(
                    "SELECT 1 FROM attendance_sessions WHERE subject_id=%s AND faculty_username=%s LIMIT 1",
                    (subject_id, faculty_username),
                ).fetchone()
                if not has_sess:
                    raise ValueError("This subject is not assigned to the faculty account")

        subject = c.execute(
            """SELECT s.id,s.code,s.name,s.semester_id,sem.code AS semester_code,sem.name AS semester_name
               FROM subjects s JOIN academic_semesters sem ON sem.id=s.semester_id
               WHERE s.id=%s AND s.active=1""", (subject_id,)
        ).fetchone()
        if not subject or int(subject["semester_id"]) != int(semester_id):
            raise ValueError("Subject does not belong to the selected semester")

        hod_scope = faculty.get("hod_username") or faculty_username
        if hod_scope == "admin" or not hod_scope:
            from database import resolve_hod_for_department
            dept_hod = resolve_hod_for_department(c, faculty.get("department") or "CSD")
            if dept_hod:
                hod_scope = dept_hod

        if is_hod_or_admin:
            sessions = c.execute(
                """SELECT a.id, a.attendance_date, a.session_type, a.duration_hours, a.topic, a.created_at,
                          a.faculty_username, u.full_name AS faculty_name
                   FROM attendance_sessions a
                   LEFT JOIN users u ON u.username = a.faculty_username
                   WHERE a.semester_id=%s AND a.subject_id=%s
                     AND a.attendance_date BETWEEN %s AND %s
                     AND (a.faculty_username=%s OR u.hod_username=%s OR a.faculty_username='admin' OR %s='admin')
                   ORDER BY a.attendance_date""",
                (semester_id, subject_id, first_day.isoformat(), last_day.isoformat(), faculty_username, hod_scope, faculty_username),
            ).fetchall()
        else:
            sessions = c.execute(
                """SELECT id,attendance_date,session_type,duration_hours,topic,created_at,faculty_username
                   FROM attendance_sessions
                   WHERE faculty_username=%s AND semester_id=%s AND subject_id=%s
                     AND attendance_date BETWEEN %s AND %s
                   ORDER BY attendance_date""",
                (faculty_username, semester_id, subject_id, first_day.isoformat(), last_day.isoformat()),
            ).fetchall()

        sessions_by_date: dict[str, list[dict]] = {}
        for row in sessions:
            sessions_by_date.setdefault(str(row["attendance_date"]), []).append(dict(row))
        holidays = c.execute(
            """SELECT holiday_date, holiday_name FROM academic_holidays
               WHERE active=1 AND holiday_date BETWEEN %s AND %s
                 AND (semester_id IS NULL OR semester_id=%s)
               ORDER BY holiday_date""",
            (first_day.isoformat(), last_day.isoformat(), semester_id),
        ).fetchall()
        holiday_map = {str(r["holiday_date"]): r["holiday_name"] for r in holidays}
        sunday_map = {
            (first_day.replace(day=day)).isoformat(): "Sunday"
            for day in range(1, calendar.monthrange(int(year), int(month))[1] + 1)
            if first_day.replace(day=day).weekday() == 6
        }
        for sunday_date, sunday_name in sunday_map.items():
            holiday_map.setdefault(sunday_date, sunday_name)

        students = c.execute(
            """
            SELECT DISTINCT st.roll_no, st.name, st.current_semester_id
            FROM students st
            WHERE st.department='CSD'
              AND (LOWER(COALESCE(st.hod_username,''))=LOWER(%s) OR %s='admin')
              AND st.active=1
              AND st.current_semester_id=%s
            ORDER BY st.roll_no
            """,
            (hod_scope, faculty_username, semester_id),
        ).fetchall()

        records = {}
        if sessions:
            ids = [r["id"] for r in sessions]
            placeholders = ",".join("%s" for _ in ids)
            rows = c.execute(
                f"""
                SELECT session_id,roll_no,status
                FROM attendance_records
                WHERE session_id IN ({placeholders})
                """,
                ids,
            ).fetchall()
            for r in rows:
                records[(int(r["session_id"]), r["roll_no"])] = r["status"]

    days = []
    total_teaching_sessions = 0
    for day in range(1, calendar.monthrange(int(year), int(month))[1] + 1):
        d = datetime(int(year), int(month), day).date().isoformat()
        day_sessions = sessions_by_date.get(d, [])
        representative = day_sessions[-1] if day_sessions else None
        if day_sessions:
            total_teaching_sessions += 1
        days.append({
            "day": day, "date": d, "weekday": first_day.replace(day=day).strftime("%a"),
            "holiday": d in holiday_map, "holiday_name": holiday_map.get(d),
            "session_id": representative["id"] if representative else None,
            "session_ids": [s["id"] for s in day_sessions],
            "session_count": len(day_sessions),
            "session_type": representative["session_type"] if representative else None,
            "duration_hours": sum(int(s["duration_hours"] or 0) for s in day_sessions) if day_sessions else None,
            "topic": representative["topic"] if representative else None,
        })

    roster = []
    for st in students:
        cells = []
        present_count = 0
        marked_count = 0
        for day in days:
            status = None
            if day["holiday"]:
                status = "H"
            elif day["session_ids"]:
                statuses = [records.get((sid, st["roll_no"])) for sid in day["session_ids"]]
                if statuses and all(v == "Present" for v in statuses):
                    status = "P"
                    present_count += 1
                    marked_count += 1
                elif any(v == "Absent" for v in statuses):
                    status = "A"
                    marked_count += 1
                elif statuses and any(v == "Present" for v in statuses):
                    status = "P"
                    present_count += 1
                    marked_count += 1
            cells.append({
                "day": day["day"], "status": status,
                "session_id": day["session_id"], "session_ids": day["session_ids"],
            })

        pct = round(present_count * 100 / marked_count, 1) if marked_count > 0 else (100.0 if total_teaching_sessions == 0 else 0.0)
        if marked_count == 0:
            band = "muted"
        elif pct >= 75.0:
            band = "green"
        elif pct >= 50.0:
            band = "yellow"
        else:
            band = "red"

        roster.append({
            "roll_no": st["roll_no"],
            "name": st["name"],
            "cells": cells,
            "present_count": present_count,
            "absent_count": marked_count - present_count,
            "total_count": marked_count,
            "pct": pct,
            "band": band,
        })

    class_avg = round(sum(r["pct"] for r in roster) / len(roster), 1) if roster else 0.0
    eligible_count = sum(1 for r in roster if r["pct"] >= 75.0)
    shortage_count = sum(1 for r in roster if r["pct"] < 75.0)

    return {
        "faculty_username": faculty_username,
        "faculty_name": faculty.get("full_name") or faculty_username,
        "semester": dict(subject) | {"id": subject["semester_id"]},
        "subject": dict(subject),
        "year": int(year), "month": int(month),
        "month_label": first_day.strftime("%B %Y"),
        "days": days, "roster": roster,
        "stats": {
            "total_students": len(roster),
            "total_sessions": total_teaching_sessions,
            "class_avg_pct": class_avg,
            "eligible_count": eligible_count,
            "shortage_count": shortage_count,
        }
    }


def sessions_last_n_days(days=15, on_date=None, semester_id=None, year=None, hod_username=None):
    # — HOD 15-day view (P0-P1 req 5): sessions grouped by date, newest first.
    # on_date (YYYY-MM-DD): if given, shows just that single day instead of
    # the rolling N-day window (Boss's date-picker request, 2026-07-22).
    # semester_id: if given, filters sessions for that specific semester.
    # year: "1", "2", "3", or "4" — filters by academic year prefix in
    # semester code (e.g. year="2" matches codes starting with "II-").
    YEAR_PREFIXES = {"1": "I-", "2": "II-", "3": "III-", "4": "IV-"}
    with connect() as c:
        where_clauses = []
        params = []
        if on_date:
            where_clauses.append("a.attendance_date = %s")
            params.append(on_date)
        else:
            cutoff = (datetime.now().date() - timedelta(days=int(days) - 1)).isoformat()
            where_clauses.append("a.attendance_date >= %s")
            params.append(cutoff)

        if semester_id is not None:
            where_clauses.append("a.semester_id = %s")
            params.append(int(semester_id))
        elif year and year in YEAR_PREFIXES:
            prefix = YEAR_PREFIXES[year]
            where_clauses.append("sem.code LIKE %s")
            params.append(prefix + "%")

        if hod_username:
            where_clauses.append("a.hod_username = %s")
            params.append(hod_username)

        # Only persisted/saved sessions belong in HOD summaries. Opening the
        # register creates a session shell; attendance_records are written
        # only when Save is confirmed. saved_at is the durable commit marker,
        # so an abandoned shell cannot masquerade as a real class.
        where_clauses.append("a.saved_at IS NOT NULL")

        where_clause = "WHERE " + " AND ".join(where_clauses)
        rows = c.execute(f"""
            SELECT a.id, a.attendance_date, a.session_type, a.duration_hours, a.topic, a.created_at,
                   s.name AS subject_name, s.code AS subject_code,
                   u.full_name AS faculty_name, a.faculty_username,
                   sem.code AS semester_code, sem.name AS semester_name,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id AND r.status='Absent') AS absent_count,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id AND r.status='Present') AS present_count,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id) AS total_marked
            FROM attendance_sessions a
            JOIN subjects s ON s.id=a.subject_id
            JOIN academic_semesters sem ON sem.id=a.semester_id
            LEFT JOIN users u ON u.username=a.faculty_username
            {where_clause}
            ORDER BY a.attendance_date DESC, a.created_at DESC
        """, params).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["attendance_date"], []).append(r)
    return grouped


def saved_sessions_for_user(*, role, username, limit=30):
    """Return recent committed attendance sessions visible to the caller.

    FACULTY sees only their own saved sessions; HOD sees sessions in their
    scope; ADMIN sees all saved sessions. Abandoned register shells are
    intentionally excluded in SQL via saved_at.
    """
    with connect() as c:
        where = ["a.saved_at IS NOT NULL"]
        params = []
        if role == "FACULTY":
            where.append("a.faculty_username=%s")
            params.append(username)
        elif role == "HOD":
            where.append("a.hod_username=%s")
            params.append(username)

        params.append(max(1, min(int(limit), 100)))
        rows = c.execute(f"""
            SELECT a.id, a.attendance_date, a.session_type, a.duration_hours,
                   a.topic, a.created_at, a.saved_at, a.faculty_username,
                   s.name AS subject_name, s.code AS subject_code,
                   sem.code AS semester_code, sem.name AS semester_name,
                   u.full_name AS faculty_name,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id AND r.status='Present') AS present_count,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id AND r.status='Absent') AS absent_count,
                   (SELECT COUNT(*) FROM attendance_records r WHERE r.session_id=a.id) AS total_marked
            FROM attendance_sessions a
            JOIN subjects s ON s.id=a.subject_id
            JOIN academic_semesters sem ON sem.id=a.semester_id
            LEFT JOIN users u ON u.username=a.faculty_username
            WHERE {' AND '.join(where)}
            ORDER BY a.attendance_date DESC, a.saved_at DESC, a.id DESC
            LIMIT %s
        """, params).fetchall()
    return rows


def delete_attendance_session(*, session_id, actor):
    """Hard-delete a session and its records, retaining a useful audit trail."""
    with connect() as c:
        session = c.execute("""
            SELECT a.id, a.attendance_date, a.faculty_username, a.session_type,
                   s.code AS subject_code, s.name AS subject_name,
                   SUM(CASE WHEN r.status='Present' THEN 1 ELSE 0 END) AS present_count,
                   SUM(CASE WHEN r.status='Absent' THEN 1 ELSE 0 END) AS absent_count
            FROM attendance_sessions a
            JOIN subjects s ON s.id=a.subject_id
            LEFT JOIN attendance_records r ON r.session_id=a.id
            WHERE a.id=%s
            GROUP BY a.id, a.attendance_date, a.faculty_username, a.session_type, s.code, s.name
        """, (session_id,)).fetchone()
        if not session:
            raise ValueError("Attendance session was not found")

        present = int(session.get("present_count") or 0)
        absent = int(session.get("absent_count") or 0)
        details = (
            f"session={session_id}; subject={session['subject_code']} - {session['subject_name']}; "
            f"date={session['attendance_date']}; faculty={session['faculty_username']}; "
            f"present={present}; absent={absent}"
        )
        # Hard-delete dependent operational rows first because SMS queue /
        # trigger tables intentionally use restrictive foreign keys. The
        # session itself and attendance_records are still the authoritative
        # attendance data being removed; the audit entry is the only trace
        # deliberately retained for the deleted session.
        c.execute("DELETE FROM sms_queue WHERE attendance_session_id=%s", (session_id,))
        c.execute("DELETE FROM sms_absentee_triggers WHERE session_id=%s", (session_id,))
        c.execute("DELETE FROM attendance_records WHERE session_id=%s", (session_id,))
        c.execute("DELETE FROM attendance_sessions WHERE id=%s", (session_id,))
        audit(c, actor, "DELETE", "attendance_session", details)
        return dict(session)


def absent_students_for_session(session_id):
    # — kept for internal/audit use; HOD-facing drill-down now shows Present
    # (see present_students_for_session) since a full roster is usually
    # present and the absent few are the noise-heavy case to scan, not the
    # useful one — Boss asked the button/list to reflect who showed up.
    with connect() as c:
        return c.execute("""
            SELECT st.roll_no, st.name
            FROM attendance_records r
            JOIN students st ON st.roll_no = r.roll_no
            WHERE r.session_id=%s AND r.status='Absent'
            ORDER BY st.roll_no
        """, (session_id,)).fetchall()


def present_students_for_session(session_id):
    # — P0-P1 req 5, flipped per Boss's request: click present count -> list
    # of students who attended, not who didn't.
    with connect() as c:
        return c.execute("""
            SELECT st.roll_no, st.name
            FROM attendance_records r
            JOIN students st ON st.roll_no = r.roll_no
            WHERE r.session_id=%s AND r.status='Present'
            ORDER BY st.roll_no
        """, (session_id,)).fetchall()


def student_subject_attendance(roll_no):
    # — P2 req 8/9: subject-wise % per student, computed from real sessions
    # (attendance_records), never a manually entered number. Threshold coloring
    # is applied by the caller (view layer) so this stays pure data.
    with connect() as c:
        return c.execute("""
            SELECT s.id AS subject_id, s.code AS subject_code, s.name AS subject_name,
                   COUNT(r.id) AS total_sessions,
                   SUM(CASE WHEN r.status='Present' THEN 1 ELSE 0 END) AS present_sessions
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            JOIN subjects s ON s.id=a.subject_id
            WHERE r.roll_no=%s
            GROUP BY s.id
            ORDER BY s.name
        """, (roll_no,)).fetchall()


def student_subject_attendance_for_semester(roll_no, semester_id):
    # — Same shape as student_subject_attendance, but scoped to one semester
    # so a student's track record can show the subject-wise breakdown that
    # was actually taught in that term, not a lifetime total mislabeled as
    # a single semester's numbers.
    with connect() as c:
        return c.execute("""
            SELECT s.id AS subject_id, s.code AS subject_code, s.name AS subject_name,
                   COUNT(r.id) AS total_sessions,
                   SUM(CASE WHEN r.status='Present' THEN 1 ELSE 0 END) AS present_sessions
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            JOIN subjects s ON s.id=a.subject_id
            WHERE r.roll_no=%s AND a.semester_id=%s
            GROUP BY s.id
            ORDER BY s.name
        """, (roll_no, semester_id)).fetchall()


def student_subject_session_history(roll_no, subject_id):
    # — STUDENT Home, "tapping a subject shows session history for that
    # subject only (present/absent per date)" (SPEC.md §3).
    with connect() as c:
        return c.execute("""
            SELECT a.attendance_date, a.session_type, a.duration_hours, r.status
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            WHERE r.roll_no=%s AND a.subject_id=%s
            ORDER BY a.attendance_date DESC
        """, (roll_no, subject_id)).fetchall()


def attendance_pct_band(present, total):
    """P2 req 9 thresholds: >=75 green/NORMAL, 50-74 amber/LOW, <50 red/CRITICAL."""
    if not total:
        return None, "muted"
    pct = present * 100 / total
    if pct >= 75:
        band = "green"
    elif pct >= 50:
        band = "yellow"
    else:
        band = "red"
    return round(pct, 1), band


def faculty_teaching_hours(faculty_username=None):
    # — P0-P1 req 7: computed from saved sessions, never manually entered.
    # 1hr class -> 1 session/1 hour. Lab (fixed 3hr) -> 1 session/3 hours.
    with connect() as c:
        sql = """
            SELECT a.faculty_username, u.full_name,
                   COUNT(*) AS sessions_taken,
                   SUM(a.duration_hours) AS teaching_hours,
                   SUM(CASE WHEN a.session_type='CLASS' THEN 1 ELSE 0 END) AS classes,
                   SUM(CASE WHEN a.session_type='LAB' THEN 1 ELSE 0 END) AS labs
            FROM attendance_sessions a
            LEFT JOIN users u ON u.username=a.faculty_username
        """
        args = []
        if faculty_username:
            sql += " WHERE a.faculty_username=%s"
            args.append(faculty_username)
        sql += " GROUP BY a.faculty_username, u.full_name ORDER BY teaching_hours DESC"
        return c.execute(sql, args).fetchall()


def recent_audit_logs(limit=100, entity=None):
    # — P0-P1 req 6: faculty audit trail visible to HOD. Read-only surface over
    # the existing audit_logs table; every write path already calls audit().
    # Filtered to actions performed by FACULTY users: this page exists so HOD
    # can review what faculty did (create/edit attendance, change topic, etc),
    # not to show the HOD's own login/logout/status-toggle activity back to
    # itself. audit() still writes every actor's actions to audit_logs
    # unfiltered — the filtering happens only at this read surface.
    with connect() as c:
        sql = (
            "SELECT a.username, a.action, a.entity, a.details, a.created_at "
            "FROM audit_logs a JOIN users u ON LOWER(u.username) = LOWER(a.username) "
            "WHERE u.role = 'FACULTY'"
        )
        args = []
        if entity:
            sql += " AND a.entity=%s"
            args.append(entity)
        sql += " ORDER BY a.created_at DESC LIMIT %s"
        args.append(limit)
        return c.execute(sql, args).fetchall()


def save_register(*, session_id, attendance, actor, role, session_type, duration_hours, topic):
    session = session_details(session_id)
    if not session:
        raise ValueError("Attendance session was not found")
    # Revalidate at the actual database-write boundary. Every save path must pass this.
    normalized_type, normalized_hours, normalized_topic = validate_session_payload(
        attendance_date=session["attendance_date"], semester_id=session["semester_id"],
        subject_id=session["subject_id"], faculty_username=session["faculty_username"],
        session_type=session_type, duration_hours=duration_hours, topic=topic,
    )
    if not session_is_editable(session, role):
        raise PermissionError("The 24-hour faculty edit window has expired. Contact HOD for correction.")
    if normalized_type != session["session_type"]:
        raise ValueError("Session type changed. Reopen the attendance setup before saving")
    with connect() as c:
        c.execute("""
            UPDATE attendance_sessions
            SET duration_hours=%s, topic=%s, saved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (normalized_hours, normalized_topic, session_id))
        for roll_no, is_present in attendance.items():
            status = "Present" if is_present else "Absent"
            c.execute("""
                INSERT INTO attendance_records(session_id,roll_no,status,marked_by)
                VALUES(%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    status=VALUES(status),marked_by=VALUES(marked_by),updated_at=CURRENT_TIMESTAMP
            """, (session_id, roll_no, status, actor))
        present = sum(bool(v) for v in attendance.values())
        audit(c, actor, "SAVE", "attendance_session",
              f"session={session_id}; type={normalized_type}; hours={normalized_hours}; present={present}; absent={len(attendance)-present}")
    return present, len(attendance) - present