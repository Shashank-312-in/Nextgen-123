"""Read/format audit events for human-facing monitoring screens."""
from __future__ import annotations

AUTH_ACTIONS = {"LOGIN", "LOGOUT"}


def is_auth_event(action: str | None) -> bool:
    return (action or "").upper() in AUTH_ACTIONS


def actor_label(row: dict) -> str:
    role = (row.get("actor_role") or "").upper()
    username = row.get("username") or "System"
    if role == "ADMIN":
        return f"Admin {username}"
    if role == "HOD":
        return f"HOD {username}"
    if role == "FACULTY":
        return f"Faculty {username}"
    if role == "STUDENT":
        return f"Student {username}"
    return username


def _target_name(details: str | None) -> str:
    d = details or ""
    for prefix in ("Deleted user ", "user=", "target=", "roll=", "id="):
        if d.startswith(prefix):
            return d[len(prefix):].split(";", 1)[0].strip()
    return d.strip()


def format_audit_description(row: dict) -> str:
    actor = actor_label(row)
    action = (row.get("action") or "").upper()
    entity = (row.get("entity") or "").lower()
    details = row.get("details") or ""

    if action == "LOGIN":
        return f"{actor} signed in."
    if action == "LOGOUT":
        return f"{actor} signed out."
    if action in {"CREATE"}:
        noun = {"user": "an account", "student": "a student record", "student_login": "a student login", "subject": "a subject", "attendance_session": "an attendance session", "sms_gateway": "an SMS gateway"}.get(entity, f"a {entity.replace('_', ' ')}")
        return f"{actor} created {noun}."
    if action == "DELETE":
        noun = {"user": "an account", "student": "a student record", "subject": "a subject"}.get(entity, f"a {entity.replace('_', ' ')}")
        target = _target_name(details)
        return f"{actor} deleted {noun}{f' ({target})' if target else ''}."
    if action in {"STATUS"}:
        target = _target_name(details)
        state = "activated" if details.endswith("-> 1") or "-> active" in details else "deactivated"
        noun = {"user": "account", "student": "student account"}.get(entity, entity.replace('_', ' '))
        return f"{actor} {state} {noun}{f' ({target})' if target else ''}."
    if action in {"UPDATE_PERMISSIONS", "UPDATE_USER_PERMISSIONS"}:
        target = _target_name(details)
        noun = "permissions"
        return f"{actor} changed {noun}{f' for {target}' if target else ''}."
    if action in {"UPDATE", "UPSERT"}:
        noun = {"student": "a student record", "subject": "a subject", "settings": "system settings", "user": "an account", "marks": "academic marks", "academic_calendar": "the academic calendar", "subject_faculty": "faculty assignments"}.get(entity, f"{entity.replace('_', ' ')} information")
        return f"{actor} updated {noun}."
    if action.startswith("SMS_") or "SMS" in action:
        human = action.replace("SMS_", "").replace("_", " ").lower()
        return f"{actor} {human} in the SMS system."
    if action in {"MARK_ATTENDANCE", "SAVE"} and entity == "attendance_session":
        return f"{actor} recorded attendance."
    if action.startswith("PHOTO"):
        return f"{actor} changed a profile photo."
    if action == "CHANGE_PASSWORD" or action == "FORCED_PASSWORD_CHANGE":
        return f"{actor} changed a password."
    if action == "RESET_PASSWORD" or action == "RESET_PASSWORD_VIA_OTP":
        return f"{actor} reset a password."
    if action == "SUBMIT_PROBLEM_REPORT":
        return f"{actor} submitted a problem report."
    if action == "UPDATE_PROBLEM_REPORT":
        return f"{actor} updated a problem report."
    if action in {"UPLOAD", "DELETE_UPLOAD"}:
        verb = "uploaded" if action == "UPLOAD" else "removed"
        return f"{actor} {verb} academic calendar information."
    if action == "EXPORT":
        return f"{actor} exported a report."
    if action:
        human_action = action.replace("_", " ").lower()
        return f"{actor} {human_action}."
    return f"{actor} performed an administrative action."
