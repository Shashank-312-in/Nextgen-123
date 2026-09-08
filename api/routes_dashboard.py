"""Group 2 — Dashboard API. OPTION_B_REWRITE_PLAN.md §2 group 2.

Route mapping (old -> new, per plan §3.2 pattern):
  GET /dashboard           -> GET /api/dashboard          (role-aware)
  GET /attendance-session/{id}/present -> GET /api/dashboard/session/{id}/present
  GET /attendance-session/{id}/absent  -> GET /api/dashboard/session/{id}/absent
  GET /audit-log           -> GET /api/dashboard/audit-log
  GET /sms-log             -> GET /api/dashboard/sms-log
  (new, STUDENT-only)      -> GET /api/dashboard/student/subject/{id}/history
"""

from __future__ import annotations

import os
from fastapi import APIRouter, Depends, Query

import ipaddress
import socket
import threading
from urllib.parse import urlparse

from database import connect, set_setting
from sms_app.services.sms_credential_encryption import encrypt_secret, is_encrypted_secret
from sms_app.services.sms_access import faculty_gateway, faculty_sms_enabled, faculty_can_use_batch, batches_for_faculty
from sms_app.services.attendance_service import (
    absent_students_for_session,
    attendance_pct_band,
    present_students_for_session,
    session_details,
    sessions_last_n_days,
    student_subject_attendance,
    student_subject_session_history,
)

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok
from sms_app.services.sms_access import faculty_sms_enabled, batches_for_faculty, faculty_gateway

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
_gateway_test_locks: dict[int, threading.Lock] = {}
_gateway_test_locks_guard = threading.Lock()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _serialize_session_row(r) -> dict:
    """Convert a row from sessions_last_n_days() to a JSON-safe dict."""
    return {
        "id":             r["id"],
        "attendance_date": r["attendance_date"],
        "session_type":   r["session_type"],
        "duration_hours": r["duration_hours"],
        "created_at":     r["created_at"],
        "topic":          r["topic"] if "topic" in r.keys() else None,
        "subject_name":   r["subject_name"],
        "subject_code":   r["subject_code"],
        "faculty_name":   r["faculty_name"],
        "faculty_username": r["faculty_username"],
        "semester_code":  r["semester_code"] if "semester_code" in r.keys() else None,
        "semester_name":  r["semester_name"] if "semester_name" in r.keys() else None,
        "absent_count":   r["absent_count"],
        "present_count":  r["present_count"],
        "total_marked":   r["total_marked"],
    }


# ──────────────────────────────────────────────
# GET /api/dashboard
# ──────────────────────────────────────────────

@router.get("")
async def dashboard(
    date: str | None = Query(default=None, description="YYYY-MM-DD — filter HOD view to a single day"),
    semester_id: int | None = Query(default=None, description="Filter HOD view to a single semester"),
    year: str | None = Query(default=None, description="Academic year: 1, 2, 3, or 4"),
    user: CurrentUser = Depends(get_current_user),
):
    """Role-aware dashboard root."""
    if user.role == "FACULTY":
        return ok({"role": "FACULTY", "redirect": "/attendance"})

    if user.role == "STUDENT":
        return await _student_dashboard(user)

    # HOD / ADMIN
    return await _hod_dashboard(user, picked_date=date, picked_semester_id=semester_id, picked_year=year)


async def _hod_dashboard(user: CurrentUser, picked_date: str | None, picked_semester_id: int | None = None, picked_year: str | None = None) -> dict:
    grouped_raw = sessions_last_n_days(15, on_date=picked_date, semester_id=picked_semester_id, year=picked_year, hod_username=user.username if user.role == "HOD" else None)
    days: dict[str, list[dict]] = {
        date_str: [_serialize_session_row(r) for r in rows]
        for date_str, rows in grouped_raw.items()
    }
    return ok({
        "role":               user.role,
        "scope_hod_username": user.username if user.role == "HOD" else None,
        "days":               days,
        "picked_date":        picked_date,
        "picked_semester_id": picked_semester_id,
        "picked_year":        picked_year,
    })


async def _student_dashboard(user: CurrentUser) -> dict:
    with connect() as c:
        s = c.execute(
            "SELECT roll_no, name, department FROM students WHERE roll_no=?",
            (user.student_roll_no,),
        ).fetchone()

    if not s:
        raise ApiError(
            "Your student record was not found. Contact HOD.",
            status_code=404,
            code="STUDENT_NOT_FOUND",
        )

    rows = student_subject_attendance(user.student_roll_no)
    subjects = []
    for r in rows:
        pct, band = attendance_pct_band(r["present_sessions"], r["total_sessions"])
        subjects.append({
            "subject_id":   r["subject_id"],
            "code":         r["subject_code"],
            "name":         r["subject_name"],
            "pct":          pct,
            "band":         band,
            "total":        r["total_sessions"],
            "present":      r["present_sessions"],
        })

    return ok({
        "role":    "STUDENT",
        "student": {"roll_no": s["roll_no"], "name": s["name"], "department": s["department"]},
        "subjects": subjects,
    })


# ──────────────────────────────────────────────
# Session drill-downs (HOD / FACULTY)
# ──────────────────────────────────────────────

@router.get("/session/{session_id}/present")
async def session_present(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    sess = session_details(session_id)
    if not sess:
        raise ApiError("Session not found", status_code=404, code="NOT_FOUND")
    rows = present_students_for_session(session_id)
    return ok({
        "session": {
            "id":              sess["id"],
            "subject_name":    sess["subject_name"],
            "attendance_date": sess["attendance_date"],
            "session_type":    sess["session_type"],
        },
        "students": [{"roll_no": r["roll_no"], "name": r["name"]} for r in rows],
        "kind": "present",
    })


@router.get("/session/{session_id}/absent")
async def session_absent(
    session_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    sess = session_details(session_id)
    if not sess:
        raise ApiError("Session not found", status_code=404, code="NOT_FOUND")
    rows = absent_students_for_session(session_id)
    return ok({
        "session": {
            "id":              sess["id"],
            "subject_name":    sess["subject_name"],
            "attendance_date": sess["attendance_date"],
            "session_type":    sess["session_type"],
        },
        "students": [{"roll_no": r["roll_no"], "name": r["name"]} for r in rows],
        "kind": "absent",
    })


# ──────────────────────────────────────────────
# Student subject session history
# ──────────────────────────────────────────────

@router.get("/student/subject/{subject_id}/history")
async def student_subject_history(
    subject_id: int,
    user: CurrentUser = Depends(get_current_user),
):
    if user.role != "STUDENT":
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    if not user.student_roll_no:
        raise ApiError(
            "Your student record was not found. Contact HOD.",
            status_code=404,
            code="STUDENT_NOT_FOUND",
        )
    rows = student_subject_session_history(user.student_roll_no, subject_id)
    return ok({
        "subject_id": subject_id,
        "sessions": [
            {
                "attendance_date": r["attendance_date"],
                "session_type":   r["session_type"],
                "duration_hours": r["duration_hours"],
                "status":         r["status"],
            }
            for r in rows
        ],
    })


# ──────────────────────────────────────────────
# Audit Log & SMS Log (HOD only)
# ──────────────────────────────────────────────

@router.get("/audit-log")
async def audit_log_endpoint(
    actor_type: str = Query(default="ALL", pattern="^(ALL|STUDENT|FACULTY|HOD|ADMIN)$"),
    activity: str = Query(default="ACTIONS", pattern="^(ACTIONS|AUTH|ALL)$"),
    admin_username: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access required", status_code=403, code="FORBIDDEN")
    if actor_type == "ADMIN" and user.role != "ADMIN":
        raise ApiError("Admin audit is restricted to Admin users", status_code=403, code="FORBIDDEN")
    if admin_username and user.role != "ADMIN":
        raise ApiError("Admin audit filters are restricted to Admin users", status_code=403, code="FORBIDDEN")

    from sms_app.services.audit_service import format_audit_description, is_auth_event
    from database import connect

    sql = """
        SELECT a.id, a.username, a.actor_role, a.action, a.entity, a.details, a.created_at
        FROM audit_logs a
        WHERE 1=1
    """
    args = []

    if actor_type == "ADMIN":
        sql += " AND a.actor_role='ADMIN'"
        if admin_username:
            sql += " AND LOWER(a.username)=LOWER(%s)"
            args.append(admin_username)
    else:
        sql += " AND a.actor_role IN ('STUDENT','FACULTY','HOD')"
        if actor_type != "ALL":
            sql += " AND a.actor_role=%s"
            args.append(actor_type)
        if user.role == "HOD":
            sql += " AND (LOWER(a.username)=LOWER(%s) OR EXISTS (SELECT 1 FROM users u WHERE LOWER(u.username)=LOWER(a.username) AND u.hod_username=%s))"
            args.extend([user.username, user.username])

    if activity == "ACTIONS":
        sql += " AND UPPER(a.action) NOT IN ('LOGIN','LOGOUT')"
    elif activity == "AUTH":
        sql += " AND UPPER(a.action) IN ('LOGIN','LOGOUT')"

    sql += " ORDER BY a.created_at DESC, a.id DESC LIMIT 250"
    with connect() as c:
        rows = c.execute(sql, args).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["description"] = format_audit_description(item)
            item["is_auth_event"] = is_auth_event(item.get("action"))
            result.append(item)
        return ok(result)


@router.get("/sms-access/me")
async def get_my_sms_access(user: CurrentUser = Depends(get_current_user)):
    if user.role != "FACULTY":
        raise ApiError("Faculty access required", 403, "FORBIDDEN")
    from sms_app.services.sms_access import faculty_sms_enabled, batches_for_faculty, faculty_gateway
    with connect() as c:
        access = c.execute("SELECT hod_username,enabled FROM sms_gateway_access WHERE faculty_username=%s", (user.username,)).fetchone()
        enabled = bool(access and access.get("enabled"))
        allowed = batches_for_faculty(c, user.username) if enabled else []
        gw = faculty_gateway(c, user.username) if enabled else None
    return ok({
        "enabled": enabled,
        "hod_username": access.get("hod_username") if access else None,
        "allowed_batches": [dict(r) for r in allowed],
        "gateway_configured": bool(gw),
    })


def _parse_audit_details(details: str | None) -> dict[str, str]:
    out={}
    for part in str(details or "").split(";"):
        if "=" in part:
            k,v=part.split("=",1); out[k.strip()]=v.strip()
    return out

def _activity_action(action: str, d: dict[str,str]) -> str:
    a=(action or "").upper()
    return {"SMS_SENT":"SMS sent","SMS_FAILED":"SMS failed","SMS_RETRY_SCHEDULED":"SMS retry scheduled","SMS_QUEUED":"SMS queued","GENERAL_NOTICE_QUEUED":"SMS queued","SMS_BLOCKED":"SMS blocked","SMS_APPROVED":"SMS approved","SMS_REJECTED":"SMS rejected","SMS_BATCH_APPROVED":"SMS batch approved","SMS_TEMPLATE_SAVED":"Template used","GATEWAY_TESTED":"Gateway tested","SMS_ACCESS_UPDATED":("Handler assigned" if d.get("enabled")=="1" else "Handler removed")}.get(a, "Gateway updated" if a=="UPDATE" and d.get("gateway") else ("Gateway created" if a=="CREATE" and d.get("gateway") else a.replace("_"," ").title()))

def _activity_status(action: str, d: dict[str,str]) -> str:
    a=(action or "").upper()
    return d.get("status") or {"SMS_SENT":"SENT","SMS_FAILED":"FAILED","SMS_BLOCKED":"BLOCKED","SMS_RETRY_SCHEDULED":"RETRY","SMS_REJECTED":"REJECTED"}.get(a,"RECORDED")

@router.get("/sms-activity")
async def sms_activity_endpoint(user: CurrentUser = Depends(get_current_user), limit: int = Query(default=500, ge=1, le=1000)):
    if user.role not in ("HOD","ADMIN","FACULTY"): raise ApiError("SMS Gateway access required",403,"FORBIDDEN")
    with connect() as c:
        sql="""SELECT id,username,actor_role,action,entity,details,created_at FROM audit_logs WHERE (action LIKE 'SMS\\_%' ESCAPE '\\\\' OR action='GATEWAY_TESTED' OR (entity='sms_gateway' AND action IN ('CREATE','UPDATE')))"""
        args=[]
        if user.role=="HOD": sql+=" AND (LOWER(username)=LOWER(%s) OR details LIKE %s)"; args += [user.username,f"%hod={user.username}%"]
        elif user.role=="FACULTY": sql+=" AND (LOWER(username)=LOWER(%s) OR details LIKE %s)"; args += [user.username,f"%owner={user.username}%"]
        sql+=" ORDER BY created_at DESC,id DESC LIMIT %s"; args.append(limit)
        rows=c.execute(sql,args).fetchall()
        gids=set(); bids=set(); parsed=[]
        for r in rows:
            d=_parse_audit_details(r.get("details")); parsed.append((r,d))
            if d.get("gateway","").isdigit(): gids.add(int(d["gateway"]))
            x=d.get("batch") or d.get("semester_id");
            if x and str(x).isdigit(): bids.add(int(x))
        gm={}; bm={}
        if gids:
            ph=','.join(['%s']*len(gids)); gm={int(x["id"]):x["gateway_name"] for x in c.execute(f"SELECT id,gateway_name FROM sms_gateways WHERE id IN ({ph})",tuple(sorted(gids))).fetchall()}
        if bids:
            ph=','.join(['%s']*len(bids)); bm={int(x["id"]):(x.get("code") or x.get("name")) for x in c.execute(f"SELECT id,code,name FROM academic_semesters WHERE id IN ({ph})",tuple(sorted(bids))).fetchall()}
        out=[]
        for r,d in parsed:
            gid=int(d["gateway"]) if d.get("gateway","").isdigit() else None
            bid=int(d["batch"]) if d.get("batch","").isdigit() else (int(d["semester_id"]) if d.get("semester_id","").isdigit() else None)
            raw=d.get("count") or d.get("queued") or "1"
            try: count=int(raw)
            except: count=1
            if (r.get("action") or "").upper() in {"SMS_FAILED","SMS_RETRY_SCHEDULED"}: count=1
            out.append({"id":r["id"],"timestamp":r["created_at"],"actor":r.get("username") or "system","role":r.get("actor_role") or "SYSTEM","action":_activity_action(r.get("action"),d),"gateway_id":gid,"gateway":gm.get(gid) if gid else (d.get("gateway") or "—"),"batch":bm.get(bid) if bid else (d.get("batch") or "—"),"sms_count":count,"status":_activity_status(r.get("action"),d),"details":r.get("details") or ""})
        return ok(out)

@router.get("/sms-log")
async def sms_log_endpoint(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN", "FACULTY"):
        raise ApiError("SMS Gateway access required", status_code=403, code="FORBIDDEN")
    from sms_app.services.sms_service import recent_sms
    if user.role == "FACULTY":
        with connect() as c:
            if not faculty_sms_enabled(c, user.username):
                raise ApiError("SMS Gateway access has not been granted by your HOD", 403, "SMS_ACCESS_REQUIRED")
        rows = recent_sms(150, owner_username=user.username)
    elif user.role == "HOD":
        rows = recent_sms(250, hod_username=user.username)
    else:
        rows = recent_sms(500)
    return ok([dict(r) for r in rows])


from datetime import datetime
from pydantic import BaseModel, Field

from database import (
    get_setting,
    is_student_self_edit_enabled,
    set_setting,
    set_student_self_edit_enabled,
)


class StudentSelfEditSettingBody(BaseModel):
    student_self_edit_enabled: bool | str | int


class SmsSettingsBody(BaseModel):
    sms_enabled: str = "1"
    sms_daily_cap: str = "1000"
    sms_repeat_every_attendance: str = "1"
    sms_absentee_cutoff_time: str = "10:15"


class SmsTestBody(BaseModel):
    phone: str
    message: str = "Dear Parent, Student has not attended college today (2026-08-21). - VCET CSD Dept"
    gateway_id: int | None = None


class SmsGatewayBody(BaseModel):
    hod_username: str | None = None
    gateway_name: str = "SMSGate Phone"
    gateway_mode: str = "cloud"
    device_id: str | None = None
    local_url: str | None = None
    username: str | None = None
    password: str | None = None
    modem_port: str | None = None
    modem_baud: str = "115200"
    sim_number: int | None = Field(default=None, ge=1, le=3)
    active: bool = True


class SmsApprovalBody(BaseModel):
    send_date: str


class SmsQueueActionBody(BaseModel):
    queue_id: int


class SmsTemplateBody(BaseModel):
    message_type: str
    template: str


class SmsGeneralNoticeBody(BaseModel):
    semester_id: int
    message: str


def _mask_secret(value: str | None) -> str:
    value = str(value or "")
    return ("••••" + value[-4:]) if len(value) >= 4 else ("••••" if value else "")


def _gateway_visible(row, *, admin_safe: bool = False) -> dict:
    owner_username = row.get("owner_username")
    return {
        "id": row["id"], "hod_username": row["hod_username"], "owner_username": owner_username,
        "gateway_name": row["gateway_name"], "gateway_mode": row["gateway_mode"],
        "device_id": "", "device_id_masked": "" if admin_safe else _mask_secret(row.get("device_id")),
        "device_id_configured": bool(row.get("device_id")),
        "local_url": "" if admin_safe else (row.get("local_url") or ""),
        "username": "" if admin_safe else (row.get("username") or ""),
        "password_set": bool(row.get("password")),
        "modem_port": "" if admin_safe else (row.get("modem_port") or ""),
        "modem_baud": "" if admin_safe else (row.get("modem_baud") or "115200"),
        "sim_number": None if admin_safe else row.get("sim_number"),
        "auto_send": bool(row.get("auto_send")), "active": bool(row["active"]),
        "is_hod_gateway": bool(owner_username and owner_username == row.get("hod_username")),
        "credentials_migrated": (is_encrypted_secret(row.get("device_id")) and is_encrypted_secret(row.get("password"))) if row.get("gateway_mode") == "cloud" else (not row.get("password") or is_encrypted_secret(row.get("password"))),
        "owner_name": row.get("owner_name") or owner_username, "owner_role": row.get("owner_role"),
        "owner_department": row.get("owner_department"), "hod_name": row.get("hod_name") or row.get("hod_username"),
        "hod_department": row.get("hod_department"), "connection_status": row.get("connection_status") or "NOT_TESTED",
        "last_connection_test": row.get("last_connection_test"), "assigned_batches": row.get("assigned_batches") or [],
        "updated_at": row.get("updated_at"),
    }

def _gateway_test_lock(gateway_id: int) -> threading.Lock:
    with _gateway_test_locks_guard:
        return _gateway_test_locks.setdefault(gateway_id, threading.Lock())


def _encrypt_gateway_secret(value: str | None) -> str | None:
    """Encrypt a gateway secret and turn missing key config into a safe API error."""
    try:
        return encrypt_secret(value)
    except RuntimeError as exc:
        raise ApiError(
            "SMS credential encryption is not configured on the backend. Set SMS_CREDENTIAL_KEY and restart the API.",
            503,
            "SMS_CREDENTIAL_KEY_MISSING",
        ) from exc


def _validate_gateway_body(body: SmsGatewayBody) -> None:
    mode = body.gateway_mode.strip().lower()
    if mode not in ("cloud", "local", "modem"):
        raise ApiError("Gateway mode must be cloud, local, or modem", 400, "VALIDATION_ERROR")
    if mode == "cloud":
        if not body.device_id or not body.device_id.strip():
            raise ApiError("Cloud gateway requires a device ID", 400, "VALIDATION_ERROR")
        if not body.username or not body.username.strip():
            raise ApiError("Cloud gateway requires a username", 400, "VALIDATION_ERROR")
        if not body.password or not body.password.strip():
            raise ApiError("Cloud gateway requires a password", 400, "VALIDATION_ERROR")
    elif mode == "local" and not (body.local_url or "").strip():
        raise ApiError("Local gateway requires a local URL", 400, "VALIDATION_ERROR")
    elif mode == "modem" and not (body.modem_port or "").strip():
        raise ApiError("Modem gateway requires a serial port", 400, "VALIDATION_ERROR")


@router.get("/sms-gateways")
async def list_sms_gateways(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    with connect() as c:
        base = """SELECT g.*, ou.full_name AS owner_name, ou.role AS owner_role, ou.department AS owner_department, hu.full_name AS hod_name, hu.department AS hod_department FROM sms_gateways g LEFT JOIN users ou ON ou.username=g.owner_username LEFT JOIN users hu ON hu.username=g.hod_username """
        if user.role == "FACULTY":
            if not faculty_sms_enabled(c, user.username): raise ApiError("SMS Gateway access has not been granted by your HOD", 403, "SMS_ACCESS_REQUIRED")
            rows = c.execute(base + "WHERE g.owner_username=%s ORDER BY g.id", (user.username,)).fetchall()
        elif user.role == "HOD":
            rows = c.execute(base + "WHERE g.hod_username=%s ORDER BY (g.owner_username=%s) DESC, g.owner_username", (user.username, user.username)).fetchall()
        else:
            rows = c.execute(base + "ORDER BY g.hod_username, (g.owner_username=g.hod_username) DESC, g.owner_username").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            st=c.execute("SELECT action,details,created_at FROM audit_logs WHERE entity='sms_gateway' AND action='GATEWAY_TESTED' AND details LIKE %s ORDER BY created_at DESC,id DESC LIMIT 1", (f"gateway={row['id']};%",)).fetchone()
            if st:
                item["connection_status"]="CONNECTED" if "status=CONNECTED" in str(st.get("details") or "") else "NOT_CONNECTED"; item["last_connection_test"]=st.get("created_at")
            if row.get("owner_username") and row.get("owner_username") != row.get("hod_username"):
                bs=c.execute("""SELECT sem.id,sem.name,sem.code,(SELECT COUNT(*) FROM students st WHERE st.current_semester_id=sem.id AND st.hod_username=%s AND st.active=1) AS student_count FROM sms_gateway_batch_delegations d JOIN academic_semesters sem ON sem.id=d.semester_id WHERE d.faculty_username=%s AND d.hod_username=%s AND d.active=1 ORDER BY sem.sort_order""", (row.get("hod_username"),row.get("owner_username"),row.get("hod_username"))).fetchall()
                item["assigned_batches"]=[dict(b) for b in bs]
            result.append(_gateway_visible(item, admin_safe=user.role=="ADMIN"))
    return ok(result)


@router.post("/sms-gateways")
async def create_sms_gateway(body: SmsGatewayBody, user: CurrentUser = Depends(get_current_user)):
    if user.role == "ADMIN":
        raise ApiError("Admin accounts cannot create personal SMS gateways", 403, "FORBIDDEN")
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    _validate_gateway_body(body)
    if user.role == "FACULTY":
        with connect() as c:
            access = c.execute("SELECT hod_username,enabled FROM sms_gateway_access WHERE faculty_username=%s", (user.username,)).fetchone()
            if not access or not bool(access.get("enabled")):
                raise ApiError("SMS Gateway access has not been granted by your HOD", 403, "SMS_ACCESS_REQUIRED")
            hod_username = access["hod_username"]
            existing = c.execute("SELECT id FROM sms_gateways WHERE owner_username=%s", (user.username,)).fetchone()
            if existing:
                raise ApiError("You already have an SMS gateway. Edit the existing gateway instead.", 409, "GATEWAY_EXISTS")
            cur = c.execute("""
                INSERT INTO sms_gateways(
                    hod_username,owner_username,gateway_name,gateway_mode,device_id,local_url,username,password,
                    modem_port,modem_baud,sim_number,auto_send,active
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                hod_username, user.username, body.gateway_name.strip() or "SMSGate Phone", body.gateway_mode.strip().lower(),
                _encrypt_gateway_secret(body.device_id), body.local_url, body.username, _encrypt_gateway_secret(body.password),
                body.modem_port, body.modem_baud, body.sim_number, 0, int(body.active),
            ))
            from database import audit
            audit(c, user.username, "CREATE", "sms_gateway", f"owner={user.username}; hod={hod_username}; gateway={cur.lastrowid}")
            row = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (cur.lastrowid,)).fetchone()
        return ok(_gateway_visible(row), status_code=201)

    hod_username = user.username if user.role == "HOD" else (body.hod_username or "").strip()
    if not hod_username:
        raise ApiError("A responsible HOD is required", 400, "VALIDATION_ERROR")
    with connect() as c:
        hod = c.execute("SELECT username FROM users WHERE username=%s AND role='HOD' AND active=1", (hod_username,)).fetchone()
        if not hod:
            raise ApiError("Responsible HOD is not an active HOD account", 400, "VALIDATION_ERROR")
        existing = c.execute("SELECT id FROM sms_gateways WHERE owner_username=%s", (hod_username,)).fetchone()
        if existing:
            raise ApiError("This HOD already has an SMS gateway. Edit the existing gateway instead.", 409, "GATEWAY_EXISTS")
        cur = c.execute("""
            INSERT INTO sms_gateways(
                hod_username,owner_username,gateway_name,gateway_mode,device_id,local_url,username,password,
                modem_port,modem_baud,sim_number,auto_send,active
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            hod_username, hod_username, body.gateway_name.strip() or "SMSGate Phone", body.gateway_mode.strip().lower(),
            _encrypt_gateway_secret(body.device_id), body.local_url, body.username, _encrypt_gateway_secret(body.password),
            body.modem_port, body.modem_baud, body.sim_number, 0, int(body.active),
        ))
        from database import audit
        audit(c, user.username, "CREATE", "sms_gateway", f"hod={hod_username}; gateway={cur.lastrowid}")
        row = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (cur.lastrowid,)).fetchone()
    return ok(_gateway_visible(row), status_code=201)


@router.patch("/sms-gateways/{gateway_id}")
async def update_sms_gateway(gateway_id: int, body: SmsGatewayBody, user: CurrentUser = Depends(get_current_user)):
    if user.role == "ADMIN":
        raise ApiError("Admin gateway details are read-only", 403, "FORBIDDEN")
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (gateway_id,)).fetchone()
    if not row:
        raise ApiError("SMS gateway not found", 404, "NOT_FOUND")
    if user.role == "HOD" and row["hod_username"] != user.username:
        raise ApiError("You cannot edit another HOD's SMS gateway", 403, "FORBIDDEN")
    if user.role == "FACULTY":
        with connect() as c:
            if not faculty_sms_enabled(c, user.username):
                raise ApiError("SMS Gateway access has been revoked by your HOD", 403, "SMS_ACCESS_REVOKED")
        if row.get("owner_username") != user.username:
            raise ApiError("You cannot edit another Faculty's SMS gateway", 403, "FORBIDDEN")

    # Blank password on edit means keep the current password.
    mode = body.gateway_mode.strip().lower()
    if mode not in ("cloud", "local", "modem"):
        raise ApiError("Gateway mode must be cloud, local, or modem", 400, "VALIDATION_ERROR")
    if row.get("password") and not is_encrypted_secret(row.get("password")) and not (body.password or "").strip():
        raise ApiError("Re-enter the gateway password to complete the SMS credential security migration.", 400, "CREDENTIAL_REENTRY_REQUIRED")

    if mode == "cloud":
        if not (body.device_id or row.get("device_id")):
            raise ApiError("Cloud gateway requires a device ID", 400, "VALIDATION_ERROR")
        if not (body.username or row.get("username")):
            raise ApiError("Cloud gateway requires a username", 400, "VALIDATION_ERROR")
        if not (body.password or row.get("password")):
            raise ApiError("Re-enter the gateway password to complete the SMS credential security migration.", 400, "CREDENTIAL_REENTRY_REQUIRED")
        if not body.device_id and not is_encrypted_secret(row.get("device_id")):
            raise ApiError("Re-enter the gateway device ID to complete the SMS credential security migration.", 400, "CREDENTIAL_REENTRY_REQUIRED")
        if not body.password and not is_encrypted_secret(row.get("password")):
            raise ApiError("Re-enter the gateway password to complete the SMS credential security migration.", 400, "CREDENTIAL_REENTRY_REQUIRED")
    elif mode == "local" and not (body.local_url or row.get("local_url")):
        raise ApiError("Local gateway requires a local URL", 400, "VALIDATION_ERROR")
    elif mode == "modem" and not (body.modem_port or row.get("modem_port")):
        raise ApiError("Modem gateway requires a serial port", 400, "VALIDATION_ERROR")

    with connect() as c:
        c.execute("""
            UPDATE sms_gateways SET
                gateway_name=%s,gateway_mode=%s,device_id=%s,local_url=%s,username=%s,
                password=%s,modem_port=%s,modem_baud=%s,sim_number=%s,active=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (
            body.gateway_name.strip() or row["gateway_name"], mode,
            _encrypt_gateway_secret(body.device_id if body.device_id is not None and body.device_id.strip() else row.get("device_id")),
            body.local_url if body.local_url is not None else row.get("local_url"),
            body.username if body.username is not None else row.get("username"),
            _encrypt_gateway_secret(body.password if body.password else row.get("password")),
            body.modem_port if body.modem_port is not None else row.get("modem_port"),
            body.modem_baud or row.get("modem_baud") or "115200",
            body.sim_number if body.sim_number is not None else row.get("sim_number"),
            int(body.active), gateway_id,
        ))
        from database import audit
        audit(c, user.username, "UPDATE", "sms_gateway", f"gateway={gateway_id}; hod={row['hod_username']}")
        updated = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (gateway_id,)).fetchone()
    return ok(_gateway_visible(updated))


def _is_safe_gateway_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


@router.post("/sms-gateways/{gateway_id}/test-connection")
async def test_sms_gateway_connection(gateway_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role == "ADMIN": raise ApiError("Admin gateway details are read-only", 403, "FORBIDDEN")
    if user.role not in ("HOD", "FACULTY"): raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    with connect() as c:
        gateway = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (gateway_id,)).fetchone()
    if not gateway:
        raise ApiError("SMS gateway not found", 404, "NOT_FOUND")
    if user.role == "HOD" and gateway["hod_username"] != user.username:
        raise ApiError("You cannot test another HOD's SMS gateway", 403, "FORBIDDEN")
    if user.role == "FACULTY":
        with connect() as c:
            if not faculty_sms_enabled(c, user.username):
                raise ApiError("SMS Gateway access has been revoked by your HOD", 403, "SMS_ACCESS_REVOKED")
        if gateway.get("owner_username") != user.username:
            raise ApiError("You cannot test another Faculty's SMS gateway", 403, "FORBIDDEN")
    lock=_gateway_test_lock(gateway_id)
    if not lock.acquire(blocking=False): raise ApiError("A gateway connection test is already running", 409, "GATEWAY_TEST_IN_PROGRESS")
    mode=(gateway.get("gateway_mode") or "").lower()
    try:
        try:
            if mode == "cloud":
                from webapp.sms_cloud_gateway import test_cloud_gateway
                from sms_app.services.sms_credential_encryption import decrypt_secret
                test_cloud_gateway(gateway.get("username"), decrypt_secret(gateway.get("password")), decrypt_secret(gateway.get("device_id")))
                result={"ok":True,"mode":"cloud"}
            elif mode == "local":
                import urllib.request
                raw=(gateway.get("local_url") or "").strip(); parsed=urlparse(raw)
                if parsed.scheme not in ("http","https"): raise ApiError("Unsupported gateway URL scheme",400,"VALIDATION_ERROR")
                if parsed.username or parsed.password: raise ApiError("Gateway URL must not include credentials",400,"VALIDATION_ERROR")
                if not _is_safe_gateway_host(parsed.hostname): raise ApiError("That host cannot be reached",400,"VALIDATION_ERROR")
                with urllib.request.urlopen(raw.rstrip("/")+"/health", timeout=8) as resp:
                    if resp.getcode()!=200: raise RuntimeError(f"HTTP {resp.getcode()}")
                result={"ok":True,"mode":"local"}
            elif mode == "modem":
                if not gateway.get("modem_port"): raise RuntimeError("Modem port is not configured")
                result={"ok":True,"mode":"modem","message":"Serial port configuration is present. A test SMS was not sent."}
            else: raise RuntimeError("Unsupported gateway mode")
            with connect() as c:
                from database import audit; audit(c,user.username,"GATEWAY_TESTED","sms_gateway",f"gateway={gateway_id}; status=CONNECTED; mode={mode}")
            return ok(result)
        except ApiError: raise
        except RuntimeError as exc:
            with connect() as c:
                from database import audit; audit(c,user.username,"GATEWAY_TESTED","sms_gateway",f"gateway={gateway_id}; status=NOT_CONNECTED; mode={mode}; error=connection-test-failed")
            if "SMS_CREDENTIAL_KEY" in str(exc): raise ApiError("SMS credential encryption is not configured on the backend. Set SMS_CREDENTIAL_KEY and restart the API.",503,"SMS_CREDENTIAL_KEY_MISSING") from exc
            raise ApiError("Gateway connection test failed",400,"GATEWAY_TEST_FAILED") from exc
        except Exception as exc:
            with connect() as c:
                from database import audit; audit(c,user.username,"GATEWAY_TESTED","sms_gateway",f"gateway={gateway_id}; status=NOT_CONNECTED; mode={mode}; error=connection-test-failed")
            raise ApiError("Gateway connection test failed",400,"GATEWAY_TEST_FAILED") from exc
    finally:
        lock.release()


@router.post("/sms-gateways/{gateway_id}/auto-send")
async def set_gateway_auto_send(gateway_id: int, enabled: bool = Query(...), user: CurrentUser = Depends(get_current_user)):
    if user.role == "ADMIN": raise ApiError("Admin gateway details are read-only", 403, "FORBIDDEN")
    if user.role not in ("HOD", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT id,hod_username,owner_username FROM sms_gateways WHERE id=%s", (gateway_id,)).fetchone()
        if not row:
            raise ApiError("SMS gateway not found", 404, "NOT_FOUND")
        if user.role == "HOD" and row["hod_username"] != user.username:
            raise ApiError("You cannot change another HOD's auto-send setting", 403, "FORBIDDEN")
        if user.role == "FACULTY":
            if not faculty_sms_enabled(c, user.username):
                raise ApiError("SMS Gateway access has been revoked by your HOD", 403, "SMS_ACCESS_REVOKED")
            if row.get("owner_username") != user.username:
                raise ApiError("You cannot change another Faculty's gateway", 403, "FORBIDDEN")
        c.execute("UPDATE sms_gateways SET auto_send=%s WHERE id=%s", (int(enabled), gateway_id))
        from database import audit
        audit(c, user.username, "UPDATE", "sms_gateway", f"gateway={gateway_id}; auto_send={int(enabled)}")
    return ok({"auto_send": enabled})


@router.get("/sms-templates")
async def get_sms_templates(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    if user.role == "FACULTY":
        with connect() as c:
            access = c.execute("SELECT hod_username,enabled FROM sms_gateway_access WHERE faculty_username=%s", (user.username,)).fetchone()
        if not access or not bool(access.get("enabled")):
            raise ApiError("SMS Gateway access has not been granted by your HOD", 403, "SMS_ACCESS_REQUIRED")
        hod_username = access["hod_username"]
    else:
        hod_username = user.username
    with connect() as c:
        rows = c.execute("SELECT message_type,template FROM sms_message_templates WHERE hod_username=%s", (hod_username,)).fetchall()
    data = {r["message_type"]: r["template"] for r in rows}
    from sms_app.services.sms_service import ABSENTEE_TEMPLATE
    data.setdefault("ABSENTEE_ALERT", ABSENTEE_TEMPLATE)
    data.setdefault("GENERAL_NOTICE", "Dear Parent, {student}: {message} - VCET CSD Dept")
    return ok(data)


@router.post("/sms-templates")
async def save_sms_template(body: SmsTemplateBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    from sms_app.services.sms_service import save_message_template
    try:
        template = save_message_template(user.username, body.message_type, body.template, user.username)
    except ValueError as exc:
        raise ApiError(str(exc), 400, "VALIDATION_ERROR")
    return ok({"message_type": body.message_type, "template": template})


@router.get("/sms-batches")
async def get_sms_batches(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    with connect() as c:
        if user.role == "FACULTY":
            if not faculty_sms_enabled(c, user.username):
                raise ApiError("SMS Gateway access has not been granted by your HOD", 403, "SMS_ACCESS_REQUIRED")
            rows = batches_for_faculty(c, user.username)
            return ok([dict(r) for r in rows])
        if user.role == "HOD":
            rows = c.execute("""SELECT sem.id,sem.name,sem.code,COUNT(s.roll_no) AS student_count
                                FROM academic_semesters sem LEFT JOIN students s ON s.current_semester_id=sem.id AND s.active=1 AND s.hod_username=%s
                                GROUP BY sem.id,sem.name,sem.code ORDER BY sem.id""", (user.username,)).fetchall()
        else:
            rows = c.execute("""SELECT sem.id,sem.name,sem.code,COUNT(s.roll_no) AS student_count
                                FROM academic_semesters sem LEFT JOIN students s ON s.current_semester_id=sem.id AND s.active=1
                                GROUP BY sem.id,sem.name,sem.code ORDER BY sem.id""").fetchall()
    return ok([dict(r) for r in rows])


@router.post("/sms-general-notice")
async def create_general_notice(body: SmsGeneralNoticeBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN", "FACULTY"):
        raise ApiError("SMS Gateway access required", 403, "FORBIDDEN")
    from sms_app.services.sms_service import send_general_notice, send_general_notice_as_faculty
    try:
        if user.role == "HOD":
            result = send_general_notice(user.username, body.semester_id, body.message, user.username)
        elif user.role == "FACULTY":
            result = send_general_notice_as_faculty(user.username, body.semester_id, body.message, user.username)
        else:
            raise ApiError("General Notice must be sent from the responsible HOD scope", 400, "SCOPE_REQUIRED")
    except ValueError as exc:
        raise ApiError(str(exc), 400, "VALIDATION_ERROR")
    return ok(result)


@router.get("/sms-approval")
async def get_sms_approval(send_date: str | None = Query(default=None), user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    from sms_app.services.sms_service import pending_approval_for_hod
    if user.role == "HOD":
        hod_username = user.username
    else:
        # Admin sees all unapproved rows; this keeps the endpoint useful even
        # though the current DB seeds the maintainer account as HOD.
        with connect() as c:
            if send_date:
                rows = c.execute("""
                    SELECT q.*, s.name AS student_name, g.gateway_name, g.gateway_mode, g.active AS gateway_active
                    FROM sms_queue q LEFT JOIN students s ON s.roll_no=q.roll_no
                    LEFT JOIN sms_gateways g ON g.id=q.gateway_id
                    WHERE q.send_date=%s AND q.status='PENDING' AND q.approved=0
                    ORDER BY q.hod_username,q.created_at,q.id
                """, (send_date,)).fetchall()
            else:
                rows = c.execute("""
                    SELECT q.*, s.name AS student_name, g.gateway_name, g.gateway_mode, g.active AS gateway_active
                    FROM sms_queue q LEFT JOIN students s ON s.roll_no=q.roll_no
                    LEFT JOIN sms_gateways g ON g.id=q.gateway_id
                    WHERE q.status='PENDING' AND q.approved=0
                    ORDER BY q.send_date DESC,q.hod_username,q.created_at,q.id LIMIT 500
                """).fetchall()
    if user.role == "HOD":
        rows = pending_approval_for_hod(hod_username, send_date)
    return ok([{
        "id": r["id"], "roll_no": r["roll_no"], "student_name": r.get("student_name") or "",
        "parent_phone": r["parent_phone"], "message": r["message"], "send_date": r["send_date"],
        "hod_username": r.get("hod_username"), "gateway_id": r.get("gateway_id"),
        "gateway_name": r.get("gateway_name"), "gateway_mode": r.get("gateway_mode"),
        "gateway_active": bool(r.get("gateway_active")) if r.get("gateway_active") is not None else False,
        "message_type": r.get("message_type") or "ABSENTEE_ALERT",
        "status": r.get("status") or "PENDING",
        "error": r.get("error"),
    } for r in rows])


@router.post("/sms-approval/{queue_id}/approve")
async def approve_sms_row(queue_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    if user.role == "ADMIN":
        with connect() as c:
            row = c.execute("SELECT hod_username FROM sms_queue WHERE id=%s", (queue_id,)).fetchone()
        if not row or not row.get("hod_username"):
            raise ApiError("SMS queue row not found", 404, "NOT_FOUND")
        hod_username = row["hod_username"]
    else:
        hod_username = user.username
    from sms_app.services.sms_service import approve_sms
    try:
        count = approve_sms(queue_id, hod_username, user.username)
    except ValueError as exc:
        raise ApiError(str(exc), 400, "SMS_ROW_BLOCKED")
    return ok({"approved_count": count, "queue_id": queue_id})


@router.post("/sms-approval/{queue_id}/reject")
async def reject_sms_row(queue_id: int, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    with connect() as c:
        row = c.execute("SELECT hod_username FROM sms_queue WHERE id=%s", (queue_id,)).fetchone()
    if not row or not row.get("hod_username"):
        raise ApiError("SMS queue row not found", 404, "NOT_FOUND")
    if user.role == "HOD" and row["hod_username"] != user.username:
        raise ApiError("You cannot reject another HOD's SMS", 403, "FORBIDDEN")
    from sms_app.services.sms_service import reject_sms
    try:
        count = reject_sms(queue_id, row["hod_username"], user.username)
    except ValueError as exc:
        raise ApiError(str(exc), 400, "SMS_REJECT_FAILED")
    return ok({"rejected_count": count, "queue_id": queue_id})


@router.post("/sms-approval")
async def approve_sms(body: SmsApprovalBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", 403, "FORBIDDEN")
    try:
        datetime.strptime(body.send_date, "%Y-%m-%d")
    except ValueError:
        raise ApiError("send_date must be YYYY-MM-DD", 400, "VALIDATION_ERROR")
    from sms_app.services.sms_service import approve_sms_batch
    if user.role == "HOD":
        hod_username = user.username
        try:
            count = approve_sms_batch(hod_username, body.send_date, user.username)
        except ValueError as exc:
            raise ApiError(str(exc), 400, "SMS_BATCH_BLOCKED")
        return ok({"approved_count": count, "hod_username": hod_username, "send_date": body.send_date})

    # ADMIN can approve all HOD batches for a selected date, but each HOD batch
    # remains atomic and individually validated.
    with connect() as c:
        hods = c.execute("SELECT DISTINCT hod_username FROM sms_queue WHERE send_date=%s AND status='PENDING' AND approved=0 AND hod_username IS NOT NULL", (body.send_date,)).fetchall()
    total = 0
    for row in hods:
        try:
            total += approve_sms_batch(row["hod_username"], body.send_date, user.username)
        except ValueError as exc:
            raise ApiError(str(exc), 400, "SMS_BATCH_BLOCKED")
    return ok({"approved_count": total, "send_date": body.send_date})


@router.get("/sms-settings")
async def get_sms_settings(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", status_code=403, code="FORBIDDEN")
    env_enabled = os.environ.get("SMS_ENABLED")
    env_repeat = os.environ.get("SMS_REPEAT_EVERY_ATTENDANCE")
    return ok({
        "sms_enabled": env_enabled if env_enabled is not None else get_setting("sms_enabled", "1"),
        "sms_daily_cap": os.environ.get("SMS_DAILY_CAP") or get_setting("sms_daily_cap", "1000"),
        "sms_repeat_every_attendance": env_repeat if env_repeat is not None else get_setting("sms_repeat_every_attendance", "1"),
        "sms_absentee_cutoff_time": get_setting("sms_absentee_cutoff_time", "10:15"),
        "sms_enabled_env_override": env_enabled is not None,
        "sms_repeat_env_override": env_repeat is not None,
    })


@router.post("/sms-settings")
async def save_sms_settings(body: SmsSettingsBody, user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    if body.sms_enabled not in ("0", "1") or body.sms_repeat_every_attendance not in ("0", "1"):
        raise ApiError("SMS toggles must be 0 or 1", 400, "VALIDATION_ERROR")
    try:
        hh, mm = [int(x) for x in body.sms_absentee_cutoff_time.strip().split(":", 1)]
        if not (0 <= hh <= 23 and 0 <= mm <= 59): raise ValueError
        cutoff = f"{hh:02d}:{mm:02d}"
    except Exception:
        raise ApiError("Absentee cutoff time must be HH:MM", 400, "VALIDATION_ERROR")
    try:
        cap = int(body.sms_daily_cap)
    except ValueError:
        raise ApiError("Daily SMS cap must be a positive integer", 400, "VALIDATION_ERROR")
    if cap <= 0:
        raise ApiError("Daily SMS cap must be a positive integer", 400, "VALIDATION_ERROR")
    set_setting("sms_enabled", body.sms_enabled, actor=user.username)
    set_setting("sms_daily_cap", str(cap), actor=user.username)
    set_setting("sms_repeat_every_attendance", body.sms_repeat_every_attendance, actor=user.username)
    set_setting("sms_absentee_cutoff_time", cutoff, actor=user.username)
    return ok({"ok": True, "sms_absentee_cutoff_time": cutoff})


@router.get("/settings/student-self-edit")
@router.get("/student-self-edit")
async def get_student_self_edit_setting(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", status_code=403, code="FORBIDDEN")
    return ok({
        "student_self_edit_enabled": is_student_self_edit_enabled(),
    })


@router.patch("/settings/student-self-edit")
@router.patch("/student-self-edit")
@router.post("/settings/student-self-edit")
@router.post("/student-self-edit")
async def save_student_self_edit_setting(body: StudentSelfEditSettingBody, user: CurrentUser = Depends(get_current_user)):
    # — WHY this now matches the GET sibling's check
    # This previously required role == "ADMIN" (or the literal legacy
    # username "admin"), while the GET above it allows HOD or ADMIN. Since
    # the bootstrap flow (database.py's _bootstrap_admin) only ever creates
    # a role="HOD" account, and the codebase's own convention everywhere
    # else treats HOD and ADMIN as the two top-tier roles (see
    # api/routes_faculty.py's RBAC checks), the stricter PATCH check made
    # this setting readable but never actually changeable by the only
    # account bootstrap produces — a real live-verification finding
    # (test_admin_can_get_and_patch_setting), not a hypothetical.
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", status_code=403, code="FORBIDDEN")
    is_enabled = set_student_self_edit_enabled(body.student_self_edit_enabled, actor=user.username)
    return ok({
        "student_self_edit_enabled": is_enabled,
        "ok": True,
    })


@router.post("/sms-test")
async def test_sms_gateway(body: SmsTestBody, user: CurrentUser = Depends(get_current_user)):
    # Test SMS accepts an arbitrary phone number, so it is intentionally not part
    # of Faculty delegation. This prevents a Faculty account from bypassing the
    # batch-recipient rule with a direct API call.
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access only", status_code=403, code="FORBIDDEN")
    with connect() as c:
        if body.gateway_id:
            gateway = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (body.gateway_id,)).fetchone()
        elif user.role == "HOD":
            gateway = c.execute("SELECT * FROM sms_gateways WHERE hod_username=%s AND owner_username=%s AND active=1", (user.username, user.username)).fetchone()
        else:
            gateway = None
    if not gateway:
        raise ApiError("Select/configure an active SMS gateway before sending a test SMS", 400, "GATEWAY_NOT_CONFIGURED")
    if user.role == "HOD" and gateway["hod_username"] != user.username:
        raise ApiError("You cannot test another HOD's SMS gateway", 403, "FORBIDDEN")
    if user.role == "FACULTY":
        with connect() as c:
            if not faculty_sms_enabled(c, user.username):
                raise ApiError("SMS Gateway access has been revoked by your HOD", 403, "SMS_ACCESS_REVOKED")
        if gateway.get("owner_username") != user.username:
            raise ApiError("You cannot test another Faculty's SMS gateway", 403, "FORBIDDEN")
    from webapp.sms_worker import send_single_sms
    msg = body.message.strip() if body.message and body.message.strip() else "Dear Parent, Student has not attended college today (2026-08-21). - VCET CSD Dept"
    try:
        send_single_sms(body.phone, msg, gateway, message_id=None)
        return ok({"sent": True, "message": "Test SMS sent successfully."})
    except Exception as exc:
        raise ApiError(f"Test SMS failed: {exc}", status_code=400, code="SMS_SEND_FAILED")


@router.post("/sms-trigger")
async def trigger_sms_queue(user: CurrentUser = Depends(get_current_user)):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("Access denied", status_code=403, code="FORBIDDEN")
    from webapp.sms_worker import process_pending_sms_now
    sent, failed = process_pending_sms_now(hod_username=user.username if user.role == "HOD" else None)
    return ok({"sent_count": sent, "failed_count": failed})
