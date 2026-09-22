"""Timetable builder/viewer API.

HOD/Admin: compose and publish a structured timetable made of movable blocks.
Faculty/Student: read the published timetable only.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok
from database import connect, audit
from sms_app.services.timetable_service import create_override, delete_override, resolve_effective_schedule, list_effective_today_for_hod, local_now

router = APIRouter(prefix="/api/timetables", tags=["timetable"])

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT")
SESSIONS = ("MORNING", "AFTERNOON")
DEFAULT_PERIODS = [
    {"key": "m1", "label": "P1", "start": "09:15", "end": "10:05", "section": "MORNING"},
    {"key": "m2", "label": "P2", "start": "10:05", "end": "10:55", "section": "MORNING"},
    {"key": "m3", "label": "P3", "start": "10:55", "end": "11:45", "section": "MORNING"},
    {"key": "m4", "label": "P4", "start": "11:45", "end": "12:35", "section": "MORNING"},
    {"key": "a1", "label": "P5", "start": "13:20", "end": "14:10", "section": "AFTERNOON"},
    {"key": "a2", "label": "P6", "start": "14:10", "end": "15:00", "section": "AFTERNOON"},
    {"key": "a3", "label": "P7", "start": "15:10", "end": "15:50", "section": "AFTERNOON"},
]

BLOCK_TYPES = {
    "THEORY": "Theory",
    "LAB": "Lab",
    "PE": "Professional Elective",
    "OE": "Open Elective",
    "TUTORIAL": "Tutorial",
    "ACTIVITY": "Activity",
    "OTHER": "Other",
}


class TimetableEntryBody(BaseModel):
    id: str | None = None
    day: str = Field(min_length=3, max_length=3)
    section: str = Field(pattern="^(MORNING|AFTERNOON)$")
    start_slot: int = Field(ge=0, le=3)
    duration: int = Field(ge=1, le=4)
    block_type: str = "THEORY"
    subject_id: int | None = None
    custom_label: str = ""
    faculty_username: str | None = None
    room: str = ""


class TimetableSaveBody(BaseModel):
    id: int | None = None
    semester_id: int
    section_name: str = Field(default="A", min_length=1, max_length=32)
    academic_year: str = Field(default="2026-27", min_length=4, max_length=32)
    periods: list[dict[str, Any]] = Field(default_factory=lambda: DEFAULT_PERIODS.copy())
    entries: list[TimetableEntryBody] = Field(default_factory=list)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|PUBLISHED)$")


class TimetableOverrideBody(BaseModel):
    timetable_entry_id: int
    override_date: date
    substitute_faculty_username: str
    reason: str = Field(min_length=1, max_length=300)


def _require_hod_or_admin(user: CurrentUser):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access required", 403, "FORBIDDEN")

def _require_hod(user: CurrentUser):
    if user.role != "HOD":
        raise ApiError("HOD access required", 403, "FORBIDDEN")


def _require_builder(user: CurrentUser):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")


def _periods_for_section(section: str, periods: list[dict[str, Any]]):
    return [p for p in periods if p.get("section") == section]


def _period_count(section: str, periods: list[dict[str, Any]]) -> int:
    return len(_periods_for_section(section, periods))


def _normalize_periods(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    periods = raw or DEFAULT_PERIODS
    clean = []
    keys = set()
    for index, p in enumerate(periods):
        if not isinstance(p, dict):
            raise ApiError("Invalid period configuration", 400, "VALIDATION_ERROR")
        key = str(p.get("key") or f"slot-{index}").strip()
        label = str(p.get("label") or f"P{index + 1}").strip()
        start = str(p.get("start") or "").strip()
        end = str(p.get("end") or "").strip()
        section = str(p.get("section") or "MORNING").upper().strip()
        if section not in SESSIONS or not start or not end or key in keys:
            raise ApiError("Invalid period configuration", 400, "VALIDATION_ERROR")
        clean.append({"key": key, "label": label, "start": start, "end": end, "section": section})
        keys.add(key)
    if not clean:
        raise ApiError("At least one period is required", 400, "VALIDATION_ERROR")
    return clean


def _scope_faculty(c, user: CurrentUser):
    if user.role == "ADMIN":
        return c.execute(
            "SELECT username, full_name FROM users WHERE role='FACULTY' AND active=1 ORDER BY full_name, username"
        ).fetchall()
    return c.execute(
        "SELECT username, full_name FROM users WHERE role='FACULTY' AND active=1 AND LOWER(COALESCE(hod_username,''))=LOWER(%s) ORDER BY full_name, username",
        (user.username,),
    ).fetchall()


def _scope_timetable(c, user: CurrentUser, timetable_id: int):
    row = c.execute("SELECT * FROM timetables WHERE id=%s", (timetable_id,)).fetchone()
    if not row:
        raise ApiError("Timetable not found", 404, "NOT_FOUND")
    if user.role == "HOD" and str(row["hod_username"]).lower() != str(user.username).lower():
        raise ApiError("You do not have access to this timetable", 403, "FORBIDDEN")
    return row


def _validate_entries(c, user: CurrentUser, semester_id: int, periods: list[dict[str, Any]], entries: list[TimetableEntryBody]):
    valid_types = set(BLOCK_TYPES)
    period_counts = {"MORNING": _period_count("MORNING", periods), "AFTERNOON": _period_count("AFTERNOON", periods)}
    seen: set[tuple[str, str, int]] = set()
    subject_ids = {int(e.subject_id) for e in entries if e.subject_id is not None}
    subject_map = {}
    if subject_ids:
        placeholders = ",".join(["%s"] * len(subject_ids))
        rows = c.execute(
            f"SELECT id, code, name FROM subjects WHERE semester_id=%s AND active=1 AND id IN ({placeholders})",
            (semester_id, *subject_ids),
        ).fetchall()
        subject_map = {int(r["id"]): dict(r) for r in rows}
        missing = subject_ids - set(subject_map)
        if missing:
            raise ApiError("One or more selected subjects are not active in this semester", 400, "VALIDATION_ERROR")

    allowed_faculty = {str(r["username"]).lower(): dict(r) for r in _scope_faculty(c, user)}
    conflicts = []
    normalized = []
    for entry in entries:
        day = entry.day.upper()
        section = entry.section.upper()
        if day not in DAYS:
            raise ApiError(f"Invalid day: {entry.day}", 400, "VALIDATION_ERROR")
        if entry.block_type.upper() not in valid_types:
            raise ApiError(f"Invalid block type: {entry.block_type}", 400, "VALIDATION_ERROR")
        count = period_counts[section]
        if entry.start_slot + entry.duration > count:
            raise ApiError("A timetable block extends beyond the available periods", 400, "VALIDATION_ERROR")
        for slot in range(entry.start_slot, entry.start_slot + entry.duration):
            key = (day, section, slot)
            if key in seen:
                conflicts.append({"day": day, "section": section, "slot": slot})
            seen.add(key)
        subject = subject_map.get(int(entry.subject_id)) if entry.subject_id is not None else None
        custom_label = entry.custom_label.strip()
        if not subject and not custom_label:
            raise ApiError("Every timetable block needs a subject or a label", 400, "VALIDATION_ERROR")
        faculty = None
        if entry.faculty_username:
            faculty = allowed_faculty.get(entry.faculty_username.lower())
            if not faculty:
                raise ApiError("Selected faculty is not assigned to your department", 400, "VALIDATION_ERROR")
        normalized.append((entry, subject))
    if conflicts:
        raise ApiError("Some timetable blocks overlap. Move or resize the highlighted blocks.", 400, "TIMETABLE_CONFLICT")
    return normalized


def _serialize_timetable(c, row):
    entries = c.execute(
        """SELECT e.*, s.code AS subject_code, s.name AS subject_name, u.full_name AS faculty_name
           FROM timetable_entries e
           LEFT JOIN subjects s ON s.id=e.subject_id
           LEFT JOIN users u ON u.username=e.faculty_username
           WHERE e.timetable_id=%s ORDER BY e.day_of_week, e.section, e.start_slot, e.id""",
        (row["id"],),
    ).fetchall()
    return {
        "id": row["id"],
        "semester_id": row["semester_id"],
        "semester_code": row.get("semester_code"),
        "semester_name": row.get("semester_name"),
        "section_name": row["section_name"],
        "academic_year": row["academic_year"],
        "hod_username": row["hod_username"],
        "status": row["status"],
        "periods": json.loads(row["period_config_json"] or "[]"),
        "entries": [
            {
                "id": e["id"],
                "day": e["day_of_week"],
                "section": e["section"],
                "start_slot": e["start_slot"],
                "duration": e["duration"],
                "block_type": e["block_type"],
                "subject_id": e["subject_id"],
                "subject_code": e.get("subject_code"),
                "subject_name": e.get("subject_name"),
                "custom_label": e["custom_label"] or "",
                "faculty_username": e["faculty_username"],
                "faculty_name": e.get("faculty_name"),
                "room": e["room"] or "",
            }
            for e in entries
        ],
    }


@router.get("/today")
async def timetable_today(
    target_date: date | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    target = target_date or local_now().date()
    if user.role == "FACULTY":
        rows = resolve_effective_schedule(faculty_username=user.username, target_date=target)
    elif user.role == "HOD":
        rows = list_effective_today_for_hod(hod_username=user.username, target_date=target)
    elif user.role == "ADMIN":
        rows = resolve_effective_schedule(faculty_username="", target_date=target)
    else:
        raise ApiError("Staff access required", 403, "FORBIDDEN")
    return ok({"date": target.isoformat(), "entries": rows})


@router.get("/overrides")
async def timetable_overrides(
    target_date: date | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    _require_hod(user)
    target = target_date or local_now().date()
    with connect() as c:
        where = ["o.override_date=%s"]
        params = [target.isoformat()]
        if user.role == "HOD":
            where.append("LOWER(t.hod_username)=LOWER(%s)")
            params.append(user.username)
        rows = c.execute(
            f"""
            SELECT o.id,o.override_date,o.substitute_faculty_username,o.reason,o.approved_by,o.created_at,
                   e.timetable_id,e.start_slot,e.duration,e.section,e.day_of_week,e.block_type,e.subject_id,
                   s.code AS subject_code,s.name AS subject_name,t.semester_id,t.section_name,t.academic_year
            FROM timetable_overrides o
            JOIN timetable_entries e ON e.id=o.timetable_entry_id
            JOIN timetables t ON t.id=e.timetable_id
            LEFT JOIN subjects s ON s.id=e.subject_id
            WHERE {' AND '.join(where)}
            ORDER BY e.start_slot,o.id
            """,
            tuple(params),
        ).fetchall()
    return ok({"date": target.isoformat(), "overrides": [dict(r) for r in rows]})


@router.post("/overrides")
async def timetable_override_create(body: TimetableOverrideBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        row = create_override(
            timetable_entry_id=body.timetable_entry_id,
            override_date=body.override_date,
            substitute_faculty_username=body.substitute_faculty_username,
            reason=body.reason,
            approved_by=user.username,
            actor_role=user.role,
        )
    except PermissionError as exc:
        raise ApiError(str(exc), 403, "FORBIDDEN")
    except ValueError as exc:
        raise ApiError(str(exc), 400, "VALIDATION_ERROR")
    with connect() as c:
        audit(c, user.username, "CREATE", "timetable_override", f"id={row['id']}; entry={body.timetable_entry_id}; date={body.override_date.isoformat()}", actor_role=user.role)
    return ok({"override": dict(row)}, status_code=201)


@router.delete("/overrides/{override_id}")
async def timetable_override_delete(override_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    try:
        row = delete_override(override_id=override_id, actor_username=user.username, actor_role=user.role)
    except PermissionError as exc:
        raise ApiError(str(exc), 403, "FORBIDDEN")
    except ValueError as exc:
        raise ApiError(str(exc), 404, "NOT_FOUND")
    with connect() as c:
        audit(c, user.username, "DELETE", "timetable_override", f"id={override_id}", actor_role=user.role)
    return ok({"deleted": True, "id": int(row["id"])})


@router.get("")
async def timetable_list(
    semester_id: int | None = Query(default=None),
    section: str | None = Query(default=None),
    academic_year: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    with connect() as c:
        if user.role in ("HOD", "ADMIN"):
            semesters = c.execute(
                "SELECT id, code, name, sort_order, active FROM academic_semesters ORDER BY sort_order"
            ).fetchall()
            where = ["t.department='CSD'"]
            params: list[Any] = []
            if user.role == "HOD":
                where.append("LOWER(t.hod_username)=LOWER(%s)")
                params.append(user.username)
            if semester_id is not None:
                where.append("t.semester_id=%s"); params.append(semester_id)
            if section:
                where.append("LOWER(t.section_name)=LOWER(%s)"); params.append(section)
            if academic_year:
                where.append("t.academic_year=%s"); params.append(academic_year)
            rows = c.execute(
                f"""SELECT t.*, s.code AS semester_code, s.name AS semester_name
                    FROM timetables t JOIN academic_semesters s ON s.id=t.semester_id
                    WHERE {' AND '.join(where)} ORDER BY t.academic_year DESC, s.sort_order, t.section_name""",
                tuple(params),
            ).fetchall()
            faculty = _scope_faculty(c, user)
            subjects = []
            if semester_id is not None:
                subjects = c.execute(
                    "SELECT id, code, name, has_lab FROM subjects WHERE semester_id=%s AND active=1 ORDER BY code",
                    (semester_id,),
                ).fetchall()
            return ok({
                "mode": "builder",
                "periods_default": DEFAULT_PERIODS,
                "semesters": [dict(x) for x in semesters],
                "subjects": [dict(x) for x in subjects],
                "faculty": [dict(x) for x in faculty],
                "timetables": [_serialize_timetable(c, r) for r in rows],
            })

        # Viewer mode — students are anchored to their current semester; faculty can filter freely.
        if user.role == "STUDENT":
            student = c.execute(
                "SELECT current_semester_id FROM students WHERE roll_no=%s AND active=1",
                (user.student_roll_no,),
            ).fetchone()
            if student and student["current_semester_id"]:
                semester_id = semester_id or int(student["current_semester_id"])

        where = ["t.department='CSD'", "t.status='PUBLISHED'"]
        params = []
        if semester_id is not None:
            where.append("t.semester_id=%s"); params.append(semester_id)
        if section:
            where.append("LOWER(t.section_name)=LOWER(%s)"); params.append(section)
        if academic_year:
            where.append("t.academic_year=%s"); params.append(academic_year)
        rows = c.execute(
            f"""SELECT t.*, s.code AS semester_code, s.name AS semester_name
                FROM timetables t JOIN academic_semesters s ON s.id=t.semester_id
                WHERE {' AND '.join(where)} ORDER BY t.academic_year DESC, s.sort_order, t.section_name""",
            tuple(params),
        ).fetchall()
        semesters = c.execute("SELECT id, code, name, sort_order, active FROM academic_semesters WHERE active=1 ORDER BY sort_order").fetchall()
        return ok({
            "mode": "viewer",
            "periods_default": DEFAULT_PERIODS,
            "semesters": [dict(x) for x in semesters],
            "timetables": [_serialize_timetable(c, r) for r in rows],
        })


@router.post("")
async def timetable_save(body: TimetableSaveBody, user: CurrentUser = Depends(get_current_user)):
    _require_builder(user)
    periods = _normalize_periods(body.periods)
    if not body.section_name.strip():
        raise ApiError("Section is required", 400, "VALIDATION_ERROR")

    with connect() as c:
        normalized = _validate_entries(c, user, body.semester_id, periods, body.entries)
        hod_username = user.username
        if user.role == "ADMIN":
            if body.id:
                existing = c.execute("SELECT hod_username FROM timetables WHERE id=%s", (body.id,)).fetchone()
                if existing:
                    hod_username = existing["hod_username"]
            elif not hod_username:
                hod_username = user.username

        existing = None
        if body.id:
            existing = c.execute("SELECT id, hod_username FROM timetables WHERE id=%s", (body.id,)).fetchone()
            if not existing:
                raise ApiError("Timetable not found", 404, "NOT_FOUND")
            if user.role == "HOD" and str(existing["hod_username"]).lower() != str(user.username).lower():
                raise ApiError("You do not have access to this timetable", 403, "FORBIDDEN")
            c.execute(
                "UPDATE timetables SET semester_id=%s, section_name=%s, academic_year=%s, period_config_json=%s, status=%s, updated_by=%s, published_at=%s WHERE id=%s",
                (body.semester_id, body.section_name.strip(), body.academic_year.strip(), json.dumps(periods), body.status, user.username,
                 datetime.now() if body.status == "PUBLISHED" else None, body.id),
            )
            timetable_id = int(body.id)
            c.execute("DELETE FROM timetable_entries WHERE timetable_id=%s", (timetable_id,))
        else:
            dupe = c.execute(
                "SELECT id FROM timetables WHERE department='CSD' AND semester_id=%s AND section_name=%s AND academic_year=%s",
                (body.semester_id, body.section_name.strip(), body.academic_year.strip()),
            ).fetchone()
            if dupe:
                raise ApiError("A timetable already exists for this semester, section and academic year", 409, "TIMETABLE_EXISTS")
            insert_cursor = c.execute(
                "INSERT INTO timetables(department,hod_username,semester_id,section_name,academic_year,period_config_json,status,created_by,updated_by,published_at) VALUES('CSD',%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (hod_username, body.semester_id, body.section_name.strip(), body.academic_year.strip(), json.dumps(periods), body.status, user.username, user.username,
                 datetime.now() if body.status == "PUBLISHED" else None),
            )
            # `lastrowid` belongs to the cursor returned by execute(). The
            # connection wrapper intentionally does not expose it.
            timetable_id = int(insert_cursor.lastrowid)

        for entry, subject in normalized:
            c.execute(
                """INSERT INTO timetable_entries(timetable_id,day_of_week,section,start_slot,duration,block_type,subject_id,custom_label,faculty_username,room)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    timetable_id,
                    entry.day.upper(), entry.section.upper(), entry.start_slot, entry.duration,
                    entry.block_type.upper(), entry.subject_id,
                    entry.custom_label.strip() or (subject["name"] if subject else ""),
                    entry.faculty_username.strip() if entry.faculty_username else None,
                    entry.room.strip(),
                ),
            )

        action = "PUBLISH_TIMETABLE" if body.status == "PUBLISHED" else "SAVE_TIMETABLE_DRAFT"
        audit(c, user.username, action, "timetable", f"ID {timetable_id}; semester {body.semester_id}; section {body.section_name.strip().upper()}", actor_role=user.role)
        row = c.execute(
            """SELECT t.*, s.code AS semester_code, s.name AS semester_name
               FROM timetables t JOIN academic_semesters s ON s.id=t.semester_id WHERE t.id=%s""",
            (timetable_id,),
        ).fetchone()
        return ok({"timetable": _serialize_timetable(c, row)})


@router.delete("/{timetable_id}")
async def timetable_delete(timetable_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_builder(user)
    with connect() as c:
        row = _scope_timetable(c, user, timetable_id)
        c.execute("DELETE FROM timetables WHERE id=%s", (timetable_id,))
        audit(c, user.username, "DELETE_TIMETABLE", "timetable", f"ID {timetable_id}", actor_role=user.role)
        return ok({"deleted": True, "id": row["id"]})
