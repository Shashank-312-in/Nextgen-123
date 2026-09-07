"""FastAPI dependencies for api/ routes — the JSON-API equivalent of
webapp/auth_session.py's get_current_user(). Same must_change_password
choke-point pattern (plan §3.3).

Supports:
1. Authorization: Bearer <access_token> header (JSON API requests via apiFetch)
2. token query parameter (direct browser downloads / tabs)
3. sms_refresh cookie (httpOnly cookie set during login / refresh)
"""

from __future__ import annotations

from fastapi import Cookie, Header, Query

from api.auth_token import REFRESH_COOKIE, read_access_token, read_refresh_token
from api.envelope import ApiError
from database import connect


class CurrentUser:
    """Mirrors webapp/auth_session.py's CurrentUser exactly."""

    def __init__(self, username: str, role: str, student_roll_no: str | None, must_change_password: bool = False):
        self.username = username
        self.role = role
        self.student_roll_no = student_roll_no
        self.must_change_password = must_change_password


def _extract_user_payload(
    authorization: str | None,
    token: str | None,
    sms_refresh: str | None,
) -> dict | None:
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
        data = read_access_token(raw_token)
        if data:
            return data

    if token:
        data = read_access_token(token) or read_refresh_token(token)
        if data:
            return data

    if sms_refresh:
        data = read_refresh_token(sms_refresh)
        if data:
            return data

    return None


def _validate_live_user(data: dict) -> CurrentUser:
    """Validate signed identity against the live users row.

    Signed tokens provide integrity, but account state is mutable. A database
    check on every authenticated request revokes sessions immediately when the
    password, active status, role, or linked student identity changes.
    """
    username = data.get("username")
    role = data.get("role")
    student_roll_no = data.get("student_roll_no")
    if not username or not role:
        raise ApiError("Invalid authentication token", status_code=401, code="TOKEN_INVALID")

    with connect() as c:
        row = c.execute(
            """SELECT username, role, student_roll_no, active, must_change_password, auth_version
               FROM users WHERE username=%s""",
            (username,),
        ).fetchone()

    if not row or not row["active"]:
        raise ApiError("Account is inactive or no longer exists", status_code=401, code="ACCOUNT_INACTIVE")
    if row["role"] != role:
        raise ApiError("Session role is no longer valid", status_code=401, code="TOKEN_INVALID")
    if (row["student_roll_no"] or None) != (student_roll_no or None):
        raise ApiError("Session identity is no longer valid", status_code=401, code="TOKEN_INVALID")
    if int(row.get("auth_version", 0)) != int(data.get("auth_version", 0)):
        raise ApiError("Session was invalidated by an account change", status_code=401, code="TOKEN_INVALID")

    return CurrentUser(
        username=row["username"],
        role=row["role"],
        student_roll_no=row["student_roll_no"],
        must_change_password=bool(row["must_change_password"]),
    )


def get_current_user(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    sms_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> CurrentUser:
    data = _extract_user_payload(authorization, token, sms_refresh)

    if not data:
        raise ApiError("Not authenticated", status_code=401, code="NOT_AUTHENTICATED")

    user = _validate_live_user(data)

    if user.must_change_password:
        raise ApiError(
            "Password change required before continuing",
            status_code=403,
            code="MUST_CHANGE_PASSWORD",
        )

    return user


def get_current_user_allow_pending(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    sms_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> CurrentUser:
    data = _extract_user_payload(authorization, token, sms_refresh)

    if not data:
        raise ApiError("Not authenticated", status_code=401, code="NOT_AUTHENTICATED")

    return _validate_live_user(data)


def get_optional_user(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    sms_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> CurrentUser | None:
    data = _extract_user_payload(authorization, token, sms_refresh)
    if not data:
        return None
    try:
        return _validate_live_user(data)
    except ApiError:
        return None

