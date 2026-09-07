"""Group 5 — Faculty API (§7.5).

Source: webapp/routes/faculty.py — ported to JSON API shape.
HOD-only for every route per spec §7.5.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import (
    audit, connect, create_user, reset_student_password,
    get_all_role_permissions, update_role_permissions,
    get_user_permissions, update_user_permissions, IntegrityError
)
from sms_app.services.attendance_service import faculty_teaching_hours, subject_faculty_map

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError, ok

router = APIRouter(prefix="/api/faculty", tags=["faculty"])


def _require_hod_or_admin(user: CurrentUser):
    if user.role not in ("HOD", "ADMIN"):
        raise ApiError("HOD or Admin access required", 403, "FORBIDDEN")

def _require_admin(user: CurrentUser):
    if user.role != "ADMIN":
        raise ApiError("Admin access required", 403, "FORBIDDEN")

def _can_manage_target(user: CurrentUser, row) -> bool:
    if user.role == "ADMIN":
        return row["role"] != "ADMIN" and row["username"] != user.username
    if row["role"] == "FACULTY":
        return (row["hod_username"] or "").lower() == user.username.lower()
    if row["role"] == "STUDENT":
        return (row["hod_username"] or "").lower() == user.username.lower()
    return False


@router.get("")
async def faculty_page(user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    hours = faculty_teaching_hours()
    subject_map = subject_faculty_map()
    # The service groups subjects by semester, while the frontend contract
    # expects a flat subject-code -> faculty-list mapping. Normalize it here.
    by_subject = {}
    for semester in subject_map:
        for subject in semester.get("subjects", []):
            by_subject[subject["subject_code"]] = list(subject.get("faculty", []))
    with connect() as c:
        if user.role == "ADMIN":
            accounts = c.execute(
                "SELECT id, username, full_name, role, department, hod_username, designation, email, phone, active, must_change_password, student_roll_no FROM users WHERE role IN ('HOD','FACULTY') ORDER BY (role='HOD') DESC, username ASC"
            ).fetchall()
        else:
            accounts = c.execute(
                "SELECT id, username, full_name, role, department, hod_username, designation, email, phone, active, must_change_password, student_roll_no FROM users WHERE role='FACULTY' AND LOWER(COALESCE(hod_username,''))=LOWER(%s) ORDER BY username ASC",
                (user.username,),
            ).fetchall()
            scoped_usernames = {a["username"].lower() for a in accounts}
            hours = [h for h in hours if (dict(h).get("faculty_username") or "").lower() in scoped_usernames]
            by_subject = {
                code: [
                    f for f in faculty
                    if (f.get("faculty_username") or "").lower() in scoped_usernames
                ]
                for code, faculty in by_subject.items()
            }
    visible_permissions = get_all_role_permissions() if user.role == "ADMIN" else [p for p in get_all_role_permissions() if p.get("role") == "FACULTY"]
    return ok({
        "hours": [dict(h) for h in hours],
        "by_subject": by_subject,
        "accounts": [dict(a) for a in accounts],
        "permissions": visible_permissions,
    })


@router.get("/permissions")
async def get_permissions(user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    permissions = get_all_role_permissions()
    if user.role == "HOD":
        permissions = [p for p in permissions if p.get("role") == "FACULTY"]
    return ok({"permissions": permissions})


class PermissionUpdateBody(BaseModel):
    role: str
    can_view_student_phone: bool = True
    can_edit_students: bool = False
    can_delete_students: bool = False
    can_view_audit_logs: bool = False
    can_view_sms_logs: bool = False
    can_manage_calendar: bool = True
    can_manage_subjects: bool = True


@router.post("/permissions")
async def save_permissions(body: PermissionUpdateBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    if body.role not in ("HOD", "FACULTY"):
        raise ApiError("Only HOD or FACULTY role permissions can be managed here", 400, "VALIDATION_ERROR")
    if user.role == "HOD" and body.role != "FACULTY":
        raise ApiError("HOD may manage Faculty permissions only", 403, "FORBIDDEN")
    update_role_permissions(body.role, body.dict())
    with connect() as c:
        audit(c, user.username, "UPDATE_PERMISSIONS", "role", body.role)
    return ok({"ok": True, "permissions": get_all_role_permissions()})


class UserPermissionUpdateBody(BaseModel):
    can_view_students: bool = True
    can_edit_students: bool = False
    can_delete_students: bool = False
    can_manage_attendance: bool = True
    can_manage_subjects: bool = True
    can_manage_calendar: bool = True
    can_view_sms_logs: bool = False
    can_view_audit_logs: bool = False


@router.get("/accounts/{username}/permissions")
async def get_account_permissions(username: str, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    with connect() as c:
        target = c.execute("SELECT username, role, hod_username FROM users WHERE username=%s", (username,)).fetchone()
    if not target or not _can_manage_target(user, target):
        raise ApiError("You cannot manage permissions for this account", 403 if target else 404, "FORBIDDEN" if target else "NOT_FOUND")
    if target["role"] == "ADMIN":
        raise ApiError("ADMIN permissions are protected from subordinate changes", 403, "FORBIDDEN")
    perms = get_user_permissions(username)
    return ok({"username": username, "permissions": perms})


@router.post("/accounts/{username}/permissions")
async def save_account_permissions(username: str, body: UserPermissionUpdateBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    with connect() as c:
        target = c.execute("SELECT username, role, hod_username FROM users WHERE username=%s", (username,)).fetchone()
    if not target or not _can_manage_target(user, target) or target["role"] == "ADMIN":
        raise ApiError("You cannot manage permissions for this account", 403 if target else 404, "FORBIDDEN" if target else "NOT_FOUND")
    update_user_permissions(username, body.dict())
    with connect() as c:
        audit(c, user.username, "UPDATE_USER_PERMISSIONS", "user", username)
    return ok({"ok": True, "username": username, "permissions": get_user_permissions(username)})


class CreateAccountBody(BaseModel):
    username: str
    full_name: str | None = ""
    password: str
    role: str
    student_roll_no: str | None = ""


@router.post("/create-account", status_code=201)
async def create_account(body: CreateAccountBody, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    if body.role not in ("ADMIN", "HOD", "FACULTY"):
        raise ApiError("Only ADMIN, HOD, or FACULTY accounts can be created here", 400, "VALIDATION_ERROR")
    if user.role == "HOD" and body.role != "FACULTY":
        raise ApiError("HOD can create Faculty accounts only", 403, "FORBIDDEN")
    try:
        create_user(
            body.username, body.password, body.role,
            (body.full_name or "").strip(), (body.student_roll_no or "").strip() or None,
            user.username,
        )
        with connect() as c:
            new_row = c.execute("SELECT id FROM users WHERE username=?", (body.username.strip(),)).fetchone()
        return ok({"id": new_row["id"] if new_row else None, "username": body.username.strip()})
    except (ValueError, IntegrityError) as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.post("/accounts/{account_id}/toggle-status")
async def toggle_account_status(account_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise ApiError("Account not found", 404, "NOT_FOUND")
        if row["username"].lower() == user.username.lower() or row["role"] == "ADMIN":
            raise ApiError("This account cannot be deactivated", 400, "SELF_DEACTIVATE")
        if not _can_manage_target(user, row):
            raise ApiError("You cannot change this account's status", 403, "FORBIDDEN")
        new_active = 0 if row["active"] else 1
        c.execute("UPDATE users SET active=?, auth_version=auth_version+1 WHERE id=?", (new_active, account_id))
        audit(c, user.username, "STATUS", "user", f"{row['username']} -> {new_active}")
    return ok({"active": bool(new_active)})


@router.post("/accounts/{account_id}/reset-password")
async def reset_password(account_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
    if not row or row["role"] != "STUDENT" or not row["student_roll_no"]:
        raise ApiError("Only linked STUDENT accounts can have their password reset", 400, "VALIDATION_ERROR")
    if not _can_manage_target(user, row):
        raise ApiError("You cannot manage this student account", 403, "FORBIDDEN")
    try:
        username, password = reset_student_password(row["student_roll_no"], user.username)
        return ok({"username": username, "password": password})
    except ValueError as e:
        raise ApiError(str(e), 400, "VALIDATION_ERROR")


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, user: CurrentUser = Depends(get_current_user)):
    _require_hod_or_admin(user)
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise ApiError("Account not found", 404, "NOT_FOUND")
        username = row["username"]
        if username.lower() == user.username.lower() or row["role"] == "ADMIN":
            raise ApiError("You cannot delete this account", 400, "CANNOT_DELETE_ADMIN")
        if not _can_manage_target(user, row):
            raise ApiError("You cannot delete this account", 403, "FORBIDDEN")

        # 1. Clean individual user permissions
        c.execute("DELETE FROM user_permissions WHERE username=?", (username,))
        # 2. Clean subject-faculty mappings
        c.execute("DELETE FROM subject_faculty WHERE faculty_username=?", (username,))
        # 3. Clean problem reports submitted by this user
        c.execute("DELETE FROM problem_reports WHERE username=?", (username,))
        # 4. Clean SMS gateways assigned to this user
        c.execute("DELETE FROM sms_gateways WHERE hod_username=?", (username,))
        # 5. Reassign attendance sessions created by this faculty to the current admin
        c.execute("UPDATE attendance_sessions SET faculty_username=? WHERE faculty_username=?", (user.username, username))
        c.execute("UPDATE attendance_sessions SET hod_username=? WHERE hod_username=?", (user.username, username))
        # 6. Reassign institutional references (holidays, bonafide, etc.)
        c.execute("UPDATE academic_holidays SET created_by=? WHERE created_by=?", (user.username, username))
        c.execute("UPDATE bonafide_issues SET generated_by=? WHERE generated_by=?", (user.username, username))
        c.execute("UPDATE institution_profile SET updated_by=? WHERE updated_by=?", (user.username, username))
        c.execute("UPDATE student_semester_history SET changed_by=? WHERE changed_by=?", (user.username, username))
        c.execute("UPDATE students SET hod_username=? WHERE hod_username=?", (user.username, username))
        c.execute("UPDATE users SET hod_username=? WHERE hod_username=?", (user.username, username))

        # 7. Permanently delete the user record
        c.execute("DELETE FROM users WHERE id=?", (account_id,))
        audit(c, user.username, "DELETE", "user", username)
    return ok({"deleted": True, "id": account_id, "username": username})
