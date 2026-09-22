"""Group 3 — Attendance API. OPTION_B_REWRITE_PLAN.md §2 group 3 / §3.2.

Route mapping (old Jinja -> new JSON, per plan §3.2 pattern):
  GET  /attendance                              -> GET  /api/attendance/setup
  GET  /attendance/subjects-for-semester         -> GET  /api/attendance/subjects
  POST /attendance/open                          -> POST /api/attendance/sessions
  GET  /attendance/register/{id}                 -> GET  /api/attendance/sessions/{id}
  POST /attendance/register/{id}/save            -> POST /api/attendance/sessions/{id}/save
  POST /attendance/register/{id}/mark-all-present -> POST /api/attendance/sessions/{id}/mark-all-present
  GET  /attendance/register/{id}/pdf             -> GET  /api/attendance/sessions/{id}/pdf

Deliberately NOT ported (per Handoff 5 / plan §2's client-state-until-Save
decision, confirmed standing): the old app's per-tap server round trips —
/mark/{roll}/{status}, /toggle/{roll}, /quick-mark. In the JSON API, the
roster is fetched once (GET .../sessions/{id}), every tap/quick-mark/
mark-all-present is pure client-side React state, and only /save commits
to the DB. mark-all-present stays a real endpoint (not client-only)
because it doubles as a legitimate batch DB shortcut mirroring the old
app's own /mark-all-present — but note this version returns the *roster
with every row flipped present* rather than writing to the DB itself; the
actual DB write only ever happens through /save, same single-write-
boundary rule save_register() already enforces. See _serialize_roster's
docstring for why "mark all present" doesn't just call save_register
twice.

Reuses sms_app/services/attendance_service.py and sms_app/services/
sms_service.py unchanged, per plan §3.5 — no business logic rewritten,
only transport changed. Same CRITICAL role-check pattern as
webapp/routes/attendance.py's save() (RED_TEAM_FINDINGS.md): every
mutating route below re-checks role itself, not just relying on a
downstream ownership check, because that ownership check only ever
restricts FACULTY — it does not by itself block a non-FACULTY caller.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from sms_app.services.attendance_service import (
    delete_attendance_session,
    get_or_create_session,
    list_semesters,
    list_subjects,
    load_register,
    month_register,
    save_register,
    saved_sessions_for_user,
    session_details,
    session_is_editable,
    subject_details,
    validate_session_payload,
    list_all_semesters,
    upload_attendance_excel,
    build_attendance_template,
)
from sms_app.services.attendance_pdf import build_attendance_pdf
from sms_app.services.sms_service import queue_absentees_for_session
from database import connect

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok
from sms_app.services.timetable_service import faculty_subject_scheduled_today

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

_STAFF_ROLES = ("HOD", "FACULTY", "ADMIN")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _require_staff(user: CurrentUser) -> None:
    # — CRITICAL role-check (RED_TEAM_FINDINGS.md; see webapp/routes/attendance.py's
    # save() comment for why this can't be inferred from the ownership check
    # below). Every mutating route in this file calls this first, unconditionally.
    if user.role not in _STAFF_ROLES:
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")


def _load_session_or_404(session_id: int):
    session = session_details(session_id)
    if not session:
        raise ApiError("Attendance session was not found", status_code=404, code="NOT_FOUND")
    return session


def _require_owner_or_hod(user: CurrentUser, session) -> None:
    # Faculty own their own sessions. A HOD may only access sessions belonging
    # to that HOD's organizational scope. ADMIN remains the cross-scope role.
    # Physical college location is never used for authorization.
    if user.role == "ADMIN" or user.username == "admin":
        return
    if user.role == "FACULTY" and session["faculty_username"] != user.username:
        raise ApiError("You do not have access to this session", status_code=403, code="FORBIDDEN")
    if user.role == "HOD" and session.get("hod_username") != user.username:
        raise ApiError("This session belongs to another HOD scope", status_code=403, code="FORBIDDEN")
    if user.role == "HOD" and not session.get("hod_username"):
        raise ApiError("This session has no HOD ownership assigned", status_code=403, code="FORBIDDEN")


def _require_hod(user: CurrentUser) -> None:
    if user.role != "HOD":
        raise ApiError("HOD access only", status_code=403, code="FORBIDDEN")


def _parse_iso_date_or_400(value: str):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError("Select a valid date", status_code=400, code="VALIDATION_ERROR")


def _serialize_session(session) -> dict:
    return {
        "id":               session["id"],
        "attendance_date":  session["attendance_date"],
        "semester_id":      session["semester_id"],
        "subject_id":       session["subject_id"],
        "subject_code":     session["subject_code"],
        "subject_name":     session["subject_name"],
        "semester_code":    session["semester_code"],
        "semester_name":    session["semester_name"],
        "faculty_username": session["faculty_username"],
        "faculty_name":     session["faculty_name"],
        "session_type":     session["session_type"],
        "duration_hours":   session["duration_hours"],
        "topic":            session["topic"],
        "created_at":       session["created_at"],
        "saved_at":         session.get("saved_at"),
        "saved":            session.get("saved_at") is not None,
    }


def _serialize_roster(session_id: int, *, force_present: bool = False) -> list[dict]:
    """Shared by GET .../sessions/{id} and POST .../mark-all-present.

    force_present=True is the "Mark all present" case: it does NOT write
    anything — save_register() is the single DB-write boundary for
    attendance (validated by its own 24h/role checks), so a batch
    convenience endpoint that skipped straight to the DB would create a
    second write path with its own copy of those checks to keep in sync.
    Instead this just returns the roster shape with every row flipped
    present=True; the frontend holds that as client state exactly like any
    other tap, and it only becomes real when the user hits Save.
    """
    students, existing = load_register(session_id)
    return [
        {
            "roll_no": s["roll_no"],
            "name": s["name"],
            "present": True if force_present else existing.get(s["roll_no"]) == "Present",
        }
        for s in students
    ]


# ──────────────────────────────────────────────
# GET /api/attendance/setup — semesters + subjects + sensible defaults
# ──────────────────────────────────────────────

@router.get("/setup")
async def setup(user: CurrentUser = Depends(get_current_user)):
    """Everything the Mark Attendance setup screen needs in one call:
    semester list, subjects for a sensibly-defaulted semester, and today's
    date. Mirrors webapp/routes/attendance.py's attendance_setup() default
    logic: first semester that actually has subjects for this user, not
    just the first semester in sort order (which may be empty for them)."""
    _require_staff(user)

    semesters = list_semesters()
    sem_id = None
    for sem in semesters:
        if list_subjects(sem["id"], user.username, user.role):
            sem_id = sem["id"]
            break
    if sem_id is None and semesters:
        sem_id = semesters[0]["id"]

    subjects = list_subjects(sem_id, user.username, user.role) if sem_id else []

    return ok({
        "semesters": [{"id": s["id"], "code": s["code"], "name": s["name"]} for s in semesters],
        "subjects": [
            {"id": s["id"], "code": s["code"], "name": s["name"], "has_lab": bool(s["has_lab"])}
            for s in subjects
        ],
        "default_semester_id": sem_id,
        "today": date.today().isoformat(),
    })


@router.get("/subjects")
async def subjects_for_semester(
    semester_id: int = Query(...),
    user: CurrentUser = Depends(get_current_user),
):
    """Subject list refresh when the semester picker changes — JSON
    equivalent of the old HTMX partial /attendance/subjects-for-semester."""
    _require_staff(user)
    subjects = list_subjects(semester_id, user.username, user.role)
    return ok({
        "subjects": [
            {"id": s["id"], "code": s["code"], "name": s["name"], "has_lab": bool(s["has_lab"])}
            for s in subjects
        ],
    })


# ──────────────────────────────────────────────
# GET /api/attendance/register — monthly staff register
# ──────────────────────────────────────────────

@router.get("/register")
async def monthly_register(
    semester_id: int = Query(...),
    subject_id: int = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    faculty_username: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    target_faculty = user.username if user.role == "FACULTY" else (faculty_username or user.username)
    # HOD/ADMIN can inspect a faculty register explicitly; FACULTY cannot
    # impersonate another faculty account through a query parameter. HODs are
    # also scoped to their own organizational faculty accounts.
    if user.role == "HOD":
        from database import connect
        with connect() as c:
            target = c.execute(
                "SELECT username, role, hod_username, department, active FROM users WHERE username=%s",
                (target_faculty,),
            ).fetchone()
        if not target or not target["active"] or (
            target["username"] != user.username
            and target["role"] != "FACULTY"
            and target.get("hod_username") != user.username
        ):
            if target and target.get("department") != getattr(user, "department", "CSD") and target.get("hod_username") != user.username and target["username"] != user.username:
                raise ApiError("Faculty account is outside your HOD scope", 403, "FORBIDDEN")
    try:
        data = month_register(
            faculty_username=target_faculty,
            semester_id=semester_id, subject_id=subject_id, year=year, month=month,
        )
    except ValueError as exc:
        raise ApiError(str(exc), 400, "VALIDATION_ERROR")
    return ok(data)


@router.get("/register/pdf")
async def monthly_register_pdf(
    semester_id: int = Query(...),
    subject_id: int = Query(...),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    faculty_username: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    target_faculty = user.username if user.role == "FACULTY" else (faculty_username or user.username)
    if user.role == "HOD":
        from database import connect
        with connect() as c:
            target = c.execute(
                "SELECT username, role, hod_username, department, active FROM users WHERE username=%s",
                (target_faculty,),
            ).fetchone()
        if not target or not target["active"] or (
            target["username"] != user.username
            and target["role"] != "FACULTY"
            and target.get("hod_username") != user.username
        ):
            if target and target.get("department") != getattr(user, "department", "CSD") and target.get("hod_username") != user.username and target["username"] != user.username:
                raise ApiError("Faculty account is outside your HOD scope", 403, "FORBIDDEN")
    try:
        data = month_register(
            faculty_username=target_faculty,
            semester_id=semester_id, subject_id=subject_id, year=year, month=month,
        )
        from sms_app.services.attendance_pdf import build_monthly_attendance_pdf
        pdf = build_monthly_attendance_pdf(data)
    except ValueError as exc:
        raise ApiError(str(exc), 400, "VALIDATION_ERROR")
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="attendance-{data["subject"]["code"]}-{year}-{month:02d}.pdf"'},
    )


@router.get("/semester-summary")
async def semester_attendance_summary(
    semester_id: int = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    from database import connect
    from sms_app.services.attendance_service import attendance_pct_band

    with connect() as c:
        sem = c.execute("SELECT id, code, name FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not sem:
            raise ApiError("Semester not found", 404, "NOT_FOUND")

        # Historical semester views must retain subjects that were real for the
        # selected term even if they are now inactive. Current active subjects
        # remain included automatically.
        subjects = c.execute(
            """
            SELECT DISTINCT s.id, s.code, s.name, s.has_lab
            FROM subjects s
            WHERE s.semester_id=%s
              AND (s.active=1 OR EXISTS (
                    SELECT 1 FROM attendance_sessions ah
                    WHERE ah.subject_id=s.id AND ah.semester_id=%s
              ))
            ORDER BY s.name
            """,
            (semester_id, semester_id),
        ).fetchall()

        scope_sql = ""
        scope_params: list = [semester_id, semester_id]
        if user.role == "ADMIN":
            pass
        else:
            from api.routes_students import _get_user_hod_username
            hod_scope = user.username if user.role == "HOD" else _get_user_hod_username(user.username)
            if not hod_scope:
                return ok({"semester": dict(sem), "subjects": [dict(s) for s in subjects], "students": [], "year": year, "month": month})
            scope_sql = " AND LOWER(COALESCE(s.hod_username,''))=LOWER(%s)"
            scope_params.append(hod_scope)

        students = c.execute(
            f"""
            SELECT DISTINCT s.roll_no, s.name
            FROM students s
            WHERE s.department='CSD' AND s.active=1
              AND (s.current_semester_id=%s OR EXISTS (
                    SELECT 1
                    FROM attendance_records ar
                    JOIN attendance_sessions ah ON ah.id=ar.session_id
                    WHERE ar.roll_no=s.roll_no AND ah.semester_id=%s
              ))
              {scope_sql}
            ORDER BY s.roll_no
            """,
            tuple(scope_params),
        ).fetchall()

        # Fetch attendance session records grouped by student and subject
        where_extra = ""
        params = [semester_id]
        if year and month:
            import calendar
            from datetime import datetime
            first_day = datetime(int(year), int(month), 1).date().isoformat()
            last_day = datetime(int(year), int(month), calendar.monthrange(int(year), int(month))[1]).date().isoformat()
            where_extra = " AND a.attendance_date BETWEEN %s AND %s"
            params.extend([first_day, last_day])

        rows = c.execute(
            f"""
            SELECT r.roll_no, a.subject_id,
                   COUNT(r.id) AS total_sessions,
                   SUM(CASE WHEN r.status='Present' THEN 1 ELSE 0 END) AS present_sessions
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            WHERE a.semester_id=%s {where_extra}
            GROUP BY r.roll_no, a.subject_id
            """,
            params,
        ).fetchall()

        att_map = {
            (r["roll_no"], r["subject_id"]): (int(r["present_sessions"] or 0), int(r["total_sessions"] or 0))
            for r in rows
        }

    students_list = []
    for st in students:
        sub_list = []
        tot_all = 0
        pres_all = 0
        for sub in subjects:
            p, t = att_map.get((st["roll_no"], sub["id"]), (0, 0))
            tot_all += t
            pres_all += p
            pct, band = attendance_pct_band(p, t)
            sub_list.append({
                "subject_id": sub["id"],
                "subject_code": sub["code"],
                "subject_name": sub["name"],
                "present": p,
                "total": t,
                "absent": t - p,
                "pct": pct,
                "band": band,
            })
        overall_pct, overall_band = attendance_pct_band(pres_all, tot_all)
        students_list.append({
            "roll_no": st["roll_no"],
            "name": st["name"],
            "total_classes": tot_all,
            "present_classes": pres_all,
            "absent_classes": tot_all - pres_all,
            "overall_pct": overall_pct,
            "overall_band": overall_band,
            "subjects": sub_list,
        })

    return ok({
        "semester": dict(sem),
        "subjects": [dict(s) for s in subjects],
        "students": students_list,
        "year": year,
        "month": month,
    })


# ──────────────────────────────────────────────
# Historical attendance bulk import (HOD only)
# ──────────────────────────────────────────────

@router.get("/bulk-import/options")
async def attendance_bulk_import_options(user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    return ok({
        "semesters": [
            {"id": int(s["id"]), "code": s["code"], "name": s["name"], "active": bool(s["active"])}
            for s in list_all_semesters()
        ]
    })


@router.get("/bulk-import/template")
async def attendance_bulk_import_template(user: CurrentUser = Depends(get_current_user)):
    _require_hod(user)
    return Response(
        content=build_attendance_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="NextGen-attendance-template.xlsx"'},
    )


@router.post("/bulk-import")
async def attendance_bulk_import(
    semester_id: int = Query(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    _require_hod(user)
    try:
        raw = await file.read()
        result = upload_attendance_excel(
            raw=raw,
            filename=file.filename or "attendance.xlsx",
            semester_id=semester_id,
            hod_username=user.username,
        )
        return ok(result)
    except ValueError as exc:
        raise ApiError(str(exc), status_code=400, code="VALIDATION_ERROR")


# ──────────────────────────────────────────────
# POST /api/attendance/sessions — open (get-or-create) a session
# ──────────────────────────────────────────────

class OpenSessionBody(BaseModel):
    attendance_date: str
    semester_id: int
    subject_id: int
    session_type: str
    duration_hours: int
    topic: str


@router.get("/student/{roll_no}/subject/{subject_id}/dates")
async def student_subject_attendance_dates(
    roll_no: str,
    subject_id: int,
    semester_id: int = Query(...),
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    roll_no = roll_no.strip()
    if not roll_no:
        raise ApiError("Roll number is required", status_code=400, code="VALIDATION_ERROR")

    with connect() as c:
        subject = c.execute(
            "SELECT id, code, name, semester_id FROM subjects WHERE id=%s",
            (subject_id,),
        ).fetchone()
        if not subject:
            raise ApiError("Subject not found", status_code=404, code="NOT_FOUND")
        if int(subject["semester_id"]) != int(semester_id):
            raise ApiError("Subject does not belong to the selected semester", status_code=400, code="VALIDATION_ERROR")

        student = c.execute(
            "SELECT roll_no, name, department, hod_username FROM students WHERE roll_no=%s AND active=1",
            (roll_no,),
        ).fetchone()
        if not student:
            raise ApiError("Student not found", status_code=404, code="NOT_FOUND")
        if str(student.get("department") or "CSD").upper() != str(getattr(user, "department", "CSD") or "CSD").upper():
            raise ApiError("Student is outside your department scope", status_code=403, code="FORBIDDEN")

        if user.role == "HOD":
            owner = str(student.get("hod_username") or "").casefold()
            if not owner or owner != user.username.casefold():
                raise ApiError("Student is outside your HOD scope", status_code=403, code="FORBIDDEN")
        elif user.role == "FACULTY":
            assigned = c.execute(
                "SELECT 1 FROM subject_faculty WHERE subject_id=%s AND faculty_username=%s",
                (subject_id, user.username),
            ).fetchone()
            if not assigned:
                raise ApiError("This subject is not assigned to the selected faculty account", status_code=403, code="FORBIDDEN")
            faculty = c.execute(
                "SELECT hod_username FROM users WHERE username=%s AND role='FACULTY' AND active=1",
                (user.username,),
            ).fetchone()
            faculty_hod = str((faculty or {}).get("hod_username") or "").casefold()
            if not faculty_hod or str(student.get("hod_username") or "").casefold() != faculty_hod:
                raise ApiError("Student is outside your faculty scope", status_code=403, code="FORBIDDEN")

        rows = c.execute(
            """
            SELECT a.attendance_date, a.session_type, a.duration_hours, r.status
            FROM attendance_records r
            JOIN attendance_sessions a ON a.id=r.session_id
            WHERE r.roll_no=%s AND a.subject_id=%s AND a.semester_id=%s
            ORDER BY a.attendance_date ASC, a.id ASC
            """,
            (roll_no, subject_id, semester_id),
        ).fetchall()

    return ok({
        "student": {"roll_no": student["roll_no"], "name": student["name"]},
        "subject": {"id": int(subject["id"]), "code": subject["code"], "name": subject["name"]},
        "semester_id": int(semester_id),
        "dates": [
            {
                "attendance_date": str(row["attendance_date"]),
                "session_type": row["session_type"],
                "duration_hours": int(row["duration_hours"] or 1),
                "status": row["status"],
            }
            for row in rows
        ],
    })


@router.post("/sessions")
async def open_session(
    body: OpenSessionBody,
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)

    subject = subject_details(body.subject_id)
    if not subject:
        raise ApiError("Select a valid subject", status_code=400, code="VALIDATION_ERROR")
    if int(subject["semester_id"]) != int(body.semester_id):
        raise ApiError("Selected subject does not belong to the selected semester", status_code=400, code="VALIDATION_ERROR")
    sess_type = body.session_type.upper()
    duration_hours = 3 if sess_type == "LAB" else body.duration_hours

    try:
        if user.role == "FACULTY":
            target_date = _parse_iso_date_or_400(body.attendance_date)
            if not faculty_subject_scheduled_today(
                faculty_username=user.username, subject_id=body.subject_id, target_date=target_date
            ):
                raise ValueError("This subject is not scheduled for the selected date")
        validate_session_payload(
            attendance_date=body.attendance_date, semester_id=body.semester_id,
            subject_id=body.subject_id, faculty_username=user.username,
            session_type=sess_type, duration_hours=duration_hours, topic=body.topic,
        )
        created = get_or_create_session(
            attendance_date=body.attendance_date, semester_id=body.semester_id,
            subject_id=body.subject_id, faculty_username=user.username,
            session_type=sess_type, duration_hours=duration_hours,
            topic=body.topic, actor=user.username,
        )
    except ValueError as exc:
        raise ApiError(str(exc), status_code=400, code="VALIDATION_ERROR")

    # WHY re-fetch via session_details() instead of serializing `created`
    # directly: get_or_create_session() returns the raw attendance_sessions
    # row (has subject_id but not the JOINed subject_code/subject_name/
    # semester_code/faculty_name columns _serialize_session expects).
    # session_details() does that JOIN -- same function every other route
    # in this file uses to build the response shape. Caught by the Group 3
    # TestClient run (IndexError: No item with that key), not assumed.
    session = session_details(created["id"])
    return ok(_serialize_session(session), status_code=201)


# ──────────────────────────────────────────────
# GET /api/attendance/sessions/{id} — session + roster (register screen)
# ──────────────────────────────────────────────

@router.get("/sessions/saved")
async def saved_sessions(
    limit: int = Query(default=30, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    rows = saved_sessions_for_user(role=user.role, username=user.username, limit=limit)
    return ok({"sessions": [
        {
            "id": r["id"], "attendance_date": r["attendance_date"],
            "session_type": r["session_type"], "duration_hours": r["duration_hours"],
            "topic": r["topic"], "created_at": r["created_at"], "saved_at": r["saved_at"],
            "saved": True, "editable": session_is_editable(r, user.role),
            "subject_name": r["subject_name"], "subject_code": r["subject_code"],
            "semester_code": r["semester_code"], "semester_name": r["semester_name"],
            "faculty_name": r["faculty_name"], "faculty_username": r["faculty_username"],
            "present_count": int(r["present_count"] or 0), "absent_count": int(r["absent_count"] or 0),
            "total_marked": int(r["total_marked"] or 0),
        } for r in rows
    ]})


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    roster = _serialize_roster(session_id)
    present = sum(r["present"] for r in roster)
    return ok({
        "session":  _serialize_session(session),
        "editable": session_is_editable(session, user.role),
        "roster":   roster,
        "present":  present,
        "absent":   len(roster) - present,
    })


# ──────────────────────────────────────────────
# POST /api/attendance/sessions/{id}/mark-all-present
# ──────────────────────────────────────────────

@router.post("/sessions/{session_id}/mark-all-present")
async def mark_all_present(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    """Batch convenience only — see _serialize_roster's docstring. Does not
    touch the DB; returns the roster with every row flipped present=True
    for the frontend to hold as client state until Save."""
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    editable = session_is_editable(session, user.role)
    roster = _serialize_roster(session_id, force_present=editable)
    present = sum(r["present"] for r in roster)
    return ok({
        "editable": editable,
        "roster":   roster,
        "present":  present,
        "absent":   len(roster) - present,
    })


# ──────────────────────────────────────────────
# POST /api/attendance/sessions/{id}/save — the single DB-write boundary
# ──────────────────────────────────────────────

class SaveRegisterBody(BaseModel):
    present_roll_nos: list[str]


@router.post("/sessions/{session_id}/save")
async def save(
    session_id: int,
    body: SaveRegisterBody,
    user: CurrentUser = Depends(get_current_user),
):
    # — CRITICAL role-check, duplicated from _require_staff intentionally
    # inline-obvious here (not just via the helper) because this is the
    # actual write boundary the RED_TEAM_FINDINGS.md regression happened
    # on — see webapp/routes/attendance.py's save() comment for the full
    # story. Do not remove thinking _require_owner_or_hod below covers it;
    # it doesn't (it only ever restricts FACULTY, never blocks a
    # non-FACULTY caller by itself).
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    students, _ = load_register(session_id)
    present_set = set(body.present_roll_nos)
    attendance = {s["roll_no"]: (s["roll_no"] in present_set) for s in students}

    try:
        save_register(
            session_id=session_id, attendance=attendance, actor=user.username, role=user.role,
            session_type=session["session_type"], duration_hours=session["duration_hours"],
            topic=session["topic"],
        )
    except PermissionError as exc:
        raise ApiError(str(exc), status_code=403, code="EDIT_WINDOW_EXPIRED")
    except ValueError as exc:
        raise ApiError(str(exc), status_code=400, code="VALIDATION_ERROR")

    absent_rolls = [roll for roll, is_present in attendance.items() if not is_present]
    queued_count = 0
    if absent_rolls:
        try:
            queue_result = queue_absentees_for_session(session_id, absent_rolls, actor=user.username)
            queued_count = int(queue_result.get("queued_count", 0)) if isinstance(queue_result, dict) else int(queue_result)
        except Exception as exc:
            # Attendance itself has already been committed successfully. SMS
            # routing problems are recorded by the queue service and must not
            # turn a valid attendance save into a failed attendance operation.
            print(f"[Automated SMS Queue] Notice: {exc}")

    roster = _serialize_roster(session_id)
    present = sum(r["present"] for r in roster)
    return ok({
        "session": _serialize_session(_load_session_or_404(session_id)),
        "roster":  roster,
        "present": present,
        "absent":  len(roster) - present,
        "sms_queued": queued_count,
    })


# ──────────────────────────────────────────────
# GET /api/attendance/sessions/{id}/pdf
# ──────────────────────────────────────────────

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    _require_staff(user)
    if user.role != "ADMIN":
        raise ApiError("Only ADMIN can delete attendance sessions", status_code=403, code="FORBIDDEN")
    try:
        deleted = delete_attendance_session(session_id=session_id, actor=user.username)
    except ValueError as exc:
        raise ApiError(str(exc), status_code=404, code="NOT_FOUND")
    return ok({"deleted": True, "session_id": int(deleted["id"])})


@router.get("/sessions/{session_id}/pdf")
async def register_pdf(
    session_id: int,
    kind: str | None = Query(default=None, description="present | absent | omit for full roster"),
    user: CurrentUser = Depends(get_current_user),
):
    """Not gated by the 24h edit lock — printing/viewing an already-saved
    register isn't editing it, same as the old Jinja route."""
    _require_staff(user)
    session = _load_session_or_404(session_id)
    _require_owner_or_hod(user, session)

    roster = _serialize_roster(session_id)
    if kind == "present":
        roster = [r for r in roster if r["present"]]
    elif kind == "absent":
        roster = [r for r in roster if not r["present"]]

    pdf_bytes = build_attendance_pdf(session, roster)
    filename = f"attendance-{session['subject_code']}-{session['attendance_date']}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
