"""Group 7 — Protected file serving (§7.7).

Auth-gated file serving — ported from webapp/routes/protected_files.py.
DO NOT add uploads to any public static mount. This is the ONLY way
to reach uploaded files. See §7.7 for the historical data-exposure gap
this route fixes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from api.deps import CurrentUser, get_current_user
from api.envelope import ApiError
from database import connect

# Derive from the same UPLOADS_DIR that writes the files — never a separate
# Path chain that might count directories wrong (§7.7 rationale).
from webapp.photo_upload import UPLOADS_DIR as _UPLOADS_DIR

router = APIRouter(tags=["files"])

# WHY .resolve(): traversal guard compares against an already-resolved target;
# if root is unresolved, the membership check silently never matches.
UPLOADS_ROOT = _UPLOADS_DIR.resolve()


def _authorize(user: CurrentUser, subdir: str, filename: str) -> None:
    """Raise 403 if this user shouldn't see this file.

    HOD/FACULTY: always allowed, any subdir.
    WHY uppercase comparison (§7.7): role is stored/compared uppercase everywhere
    in this app matching the CHECK constraint. A lowercase comparison here would
    silently 403 all staff on certificates, because staff accounts have
    student_roll_no = NULL and would fall through to the certificates check.
    """
    if user.role in ("HOD", "FACULTY", "ADMIN"):
        return

    if subdir in ("students", "users") and user.role == "STUDENT" and user.student_roll_no:
        if filename.lower().startswith(user.student_roll_no.lower() + "-"):
            return
        raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")

    if subdir == "academic_calendar" and user.role == "STUDENT":
        with connect() as c:
            student = c.execute(
                "SELECT current_semester_id FROM students WHERE roll_no=%s", (user.student_roll_no,)
            ).fetchone()
            semester_row = c.execute(
                "SELECT code FROM academic_semesters WHERE id=%s",
                (student["current_semester_id"],),
            ).fetchone() if student and student.get("current_semester_id") else None
        semester_code = "".join(
            ch for ch in (semester_row["code"] if semester_row else "").lower()
            if ch.isalnum() or ch in ("-", "_")
        )
        if semester_code and filename.lower().startswith(semester_code + "-"):
            return
        raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")

    if subdir == "certificates":
        if not user.student_roll_no:
            raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")
        own_stem = user.student_roll_no.lower()
        if not filename.lower().startswith(own_stem + "-"):
            raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")
        return

    # Unknown subdir — default deny (§7.7)
    raise ApiError("Not authorized to view this file", 403, "FORBIDDEN")


@router.get("/api/files/{subdir}/{filename}")
async def serve_file(
    subdir: str,
    filename: str,
    user: CurrentUser = Depends(get_current_user),
):
    # Path traversal guard — must use .resolve() on target AND root
    try:
        target = (UPLOADS_ROOT / subdir / filename).resolve()
    except ValueError:
        raise ApiError("Not found", 404, "NOT_FOUND")
    if UPLOADS_ROOT not in target.parents and target != UPLOADS_ROOT:
        raise ApiError("Not found", 404, "NOT_FOUND")
    if not target.is_file():
        raise ApiError("Not found", 404, "NOT_FOUND")

    _authorize(user, subdir, filename)
    return FileResponse(target)
