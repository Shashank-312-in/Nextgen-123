from __future__ import annotations

import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import connect

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT")
DAY_NAMES = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}


def app_timezone():
    """Return the configured application timezone.

    Windows does not ship the IANA timezone database used by ``zoneinfo``.
    The project therefore declares ``tzdata`` as a runtime dependency.
    Keep the failure explicit instead of silently falling back to the machine
    timezone/UTC, because timetable and notification cutoffs must remain in
    the configured application timezone (Asia/Kolkata by default).
    """
    key = os.environ.get("APP_TIMEZONE", "Asia/Kolkata").strip() or "Asia/Kolkata"
    try:
        return ZoneInfo(key)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"Application timezone '{key}' is unavailable. Install the 'tzdata' Python package "
            "and restart the backend (e.g. `py -m pip install tzdata`)."
        ) from exc


def local_now():
    return datetime.now(app_timezone())


def _period_map(period_config_json):
    try:
        raw = json.loads(period_config_json or "[]")
    except (TypeError, ValueError):
        return {}
    result = {}
    section_positions: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "MORNING").upper()
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        if not start or not end:
            continue
        position = section_positions.get(section, 0)
        section_positions[section] = position + 1
        result[(section, position)] = {
            "key": str(item.get("key") or f"slot-{position}"),
            "label": str(item.get("label") or f"P{position + 1}"),
            "start": start,
            "end": end,
            "section": section,
        }
    return result


def _parse_hhmm(value: str):
    return datetime.strptime(str(value), "%H:%M").time()


def resolve_effective_schedule(*, faculty_username: str, target_date: date | None = None):
    target_date = target_date or local_now().date()
    day = DAY_NAMES[target_date.weekday()]
    with connect() as c:
        rows = c.execute(
            """
            SELECT e.id AS timetable_entry_id, e.timetable_id, e.day_of_week, e.section,
                   e.start_slot, e.duration, e.block_type, e.subject_id, e.custom_label,
                   e.faculty_username AS regular_faculty_username, e.room,
                   t.semester_id, t.section_name, t.academic_year, t.hod_username, t.period_config_json,
                   s.code AS subject_code, s.name AS subject_name,
                   o.id AS override_id, o.substitute_faculty_username, o.reason, o.approved_by,
                   o.created_at AS override_created_at,
                   su.full_name AS substitute_faculty_name,
                   ru.full_name AS regular_faculty_name
            FROM timetable_entries e
            JOIN timetables t ON t.id=e.timetable_id
            LEFT JOIN subjects s ON s.id=e.subject_id
            LEFT JOIN timetable_overrides o ON o.timetable_entry_id=e.id AND o.override_date=%s
            LEFT JOIN users su ON su.username=o.substitute_faculty_username
            LEFT JOIN users ru ON ru.username=e.faculty_username
            WHERE t.department='CSD' AND t.status='PUBLISHED' AND e.day_of_week=%s
            ORDER BY t.semester_id, t.section_name, e.start_slot, e.id
            """,
            (target_date.isoformat(), day),
        ).fetchall()

    resolved = []
    for row in rows:
        assigned = row.get("substitute_faculty_username") or row.get("regular_faculty_username")
        if not assigned:
            continue
        periods = _period_map(row["period_config_json"])
        section_key = str(row["section"]).upper()
        start_slot = int(row["start_slot"])
        duration = max(1, int(row["duration"] or 1))
        period = periods.get((section_key, start_slot))
        end_period = periods.get((section_key, start_slot + duration - 1)) or period
        if not period or not end_period:
            # Invalid published timetable configuration should not crash every
            # consumer. It simply becomes non-resolvable for today's view.
            continue
        if row.get("regular_faculty_username") and row.get("substitute_faculty_username"):
            if str(row["substitute_faculty_username"]).lower() == str(row["regular_faculty_username"]).lower():
                # A self-substitution is meaningless but harmless; collapse it.
                assigned = row["regular_faculty_username"]
        resolved.append({
            "timetable_entry_id": int(row["timetable_entry_id"]),
            "timetable_id": int(row["timetable_id"]),
            "semester_id": int(row["semester_id"]),
            "section_name": row["section_name"],
            "academic_year": row["academic_year"],
            "hod_username": row["hod_username"],
            "day_of_week": row["day_of_week"],
            "section": row["section"],
            "start_slot": start_slot,
            "duration": duration,
            "block_type": row["block_type"],
            "subject_id": row["subject_id"],
            "subject_code": row.get("subject_code"),
            "subject_name": row.get("subject_name"),
            "custom_label": row.get("custom_label") or "",
            "room": row.get("room") or "",
            "faculty_username": assigned,
            "regular_faculty_username": row.get("regular_faculty_username"),
            "regular_faculty_name": row.get("regular_faculty_name"),
            "substitute_faculty_username": row.get("substitute_faculty_username"),
            "substitute_faculty_name": row.get("substitute_faculty_name"),
            "override_id": row.get("override_id"),
            "override_reason": row.get("reason"),
            "period": period,
            "start_time": period["start"],
            "end_time": end_period["end"],
            "target_date": target_date.isoformat(),
        })

    if faculty_username:
        needle = faculty_username.casefold()
        resolved = [r for r in resolved if str(r["faculty_username"]).casefold() == needle]
    return resolved


def faculty_subject_scheduled_today(*, faculty_username, subject_id, target_date):
    return any(
        int(row["subject_id"] or 0) == int(subject_id)
        for row in resolve_effective_schedule(faculty_username=faculty_username, target_date=target_date)
    )


def list_effective_today_for_hod(*, hod_username, target_date):
    with connect() as c:
        faculty_rows = c.execute(
            "SELECT username FROM users WHERE role='FACULTY' AND active=1 AND LOWER(COALESCE(hod_username,''))=LOWER(%s)",
            (hod_username,),
        ).fetchall()
    usernames = {str(r["username"]).casefold() for r in faculty_rows}
    usernames.add(str(hod_username).casefold())
    rows = resolve_effective_schedule(faculty_username="", target_date=target_date)
    return [r for r in rows if str(r["faculty_username"]).casefold() in usernames or str(r["hod_username"]).casefold() == str(hod_username).casefold()]


def create_override(*, timetable_entry_id, override_date: date, substitute_faculty_username, reason, approved_by, actor_role):
    if str(actor_role).upper() != "HOD":
        raise PermissionError("HOD approval is required for timetable overrides")
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("A reason is required for a timetable override")
    if len(reason) > 300:
        raise ValueError("Override reason must be 300 characters or fewer")
    substitute = str(substitute_faculty_username or "").strip()
    if not substitute:
        raise ValueError("Substitute faculty is required")

    with connect() as c:
        entry = c.execute(
            """
            SELECT e.*, t.semester_id, t.section_name, t.academic_year, t.hod_username, t.department, t.status,
                   t.period_config_json,
                   s.code AS subject_code, s.name AS subject_name
            FROM timetable_entries e JOIN timetables t ON t.id=e.timetable_id
            LEFT JOIN subjects s ON s.id=e.subject_id
            WHERE e.id=%s
            """,
            (timetable_entry_id,),
        ).fetchone()
        if not entry:
            raise ValueError("Timetable entry was not found")
        if entry["department"] != "CSD":
            raise ValueError("Unsupported department")
        if str(entry.get("status") or "").upper() != "PUBLISHED":
            raise ValueError("Only a published timetable can receive a day-specific faculty override")
        if str(entry["hod_username"]).casefold() != str(approved_by).casefold():
            raise PermissionError("You do not have access to this timetable")
        if str(entry["day_of_week"]).upper() != DAY_NAMES[override_date.weekday()]:
            raise ValueError("Override date must fall on the timetable entry's normal day")
        faculty = c.execute(
            "SELECT username, full_name, hod_username, department FROM users WHERE username=%s AND role='FACULTY' AND active=1",
            (substitute,),
        ).fetchone()
        if not faculty:
            raise ValueError("Substitute faculty is not an active faculty account")
        if str(faculty.get("department") or "").upper() != "CSD":
            raise ValueError("Substitute faculty is outside the CSD department scope")
        faculty_hod = str(faculty.get("hod_username") or "").casefold()
        if not faculty_hod or faculty_hod != str(approved_by).casefold():
            raise ValueError("Substitute faculty is outside your HOD scope")

        duplicate = c.execute(
            "SELECT id FROM timetable_overrides WHERE timetable_entry_id=%s AND override_date=%s",
            (timetable_entry_id, override_date.isoformat()),
        ).fetchone()
        if duplicate:
            raise ValueError("An override already exists for this timetable entry and date")

        period_map = _period_map(entry["period_config_json"])
        period = period_map.get((str(entry["section"]).upper(), int(entry["start_slot"])))
        if not period:
            raise ValueError("The timetable entry's period configuration is invalid")

        # A substitute cannot be double-booked by another effective entry at
        # the same time on the same date. We compare slot intervals in minutes
        # instead of relying only on identical start_slot because durations can
        # span multiple periods.
        existing = resolve_effective_schedule(faculty_username=substitute, target_date=override_date)
        def minutes(hhmm):
            t = _parse_hhmm(hhmm)
            return t.hour * 60 + t.minute
        new_start = minutes(period["start"])
        new_end = new_start
        end_period_key = (str(entry["section"]).upper(), int(entry["start_slot"]) + int(entry["duration"]) - 1)
        end_period = period_map.get(end_period_key) or period
        new_end = minutes(end_period["end"])
        for existing_row in existing:
            if int(existing_row["timetable_entry_id"]) == int(timetable_entry_id):
                continue
            old_start = minutes(existing_row["start_time"])
            old_end = minutes(existing_row["end_time"])
            if max(new_start, old_start) < min(new_end, old_end):
                raise ValueError("Substitute faculty is already scheduled during this period")

        cur = c.execute(
            """
            INSERT INTO timetable_overrides(
                timetable_entry_id, override_date, substitute_faculty_username, reason, approved_by
            ) VALUES(%s,%s,%s,%s,%s)
            """,
            (timetable_entry_id, override_date.isoformat(), faculty["username"], reason, approved_by),
        )
        # A notification that was queued for the regular faculty before the
        # override was approved must not leak a stale assignment.
        c.execute(
            """
            UPDATE faculty_class_notifications
            SET status='CANCELLED'
            WHERE timetable_entry_id=%s AND occurrence_date=%s AND status='PENDING'
              AND faculty_username<>%s
            """,
            (timetable_entry_id, override_date.isoformat(), faculty["username"]),
        )
        return c.execute("SELECT * FROM timetable_overrides WHERE id=%s", (cur.lastrowid,)).fetchone()


def delete_override(*, override_id, actor_username, actor_role):
    if str(actor_role).upper() != "HOD":
        raise PermissionError("HOD access required for timetable overrides")
    with connect() as c:
        row = c.execute(
            """
            SELECT o.*, t.hod_username, e.faculty_username
            FROM timetable_overrides o
            JOIN timetable_entries e ON e.id=o.timetable_entry_id
            JOIN timetables t ON t.id=e.timetable_id
            WHERE o.id=%s
            """,
            (override_id,),
        ).fetchone()
        if not row:
            raise ValueError("Timetable override not found")
        if str(row["hod_username"]).casefold() != str(actor_username).casefold():
            raise PermissionError("You do not have access to this override")
        c.execute("UPDATE faculty_class_notifications SET status='CANCELLED' WHERE timetable_entry_id=%s AND occurrence_date=%s AND status='PENDING'", (row["timetable_entry_id"], row["override_date"]))
        c.execute("DELETE FROM timetable_overrides WHERE id=%s", (override_id,))
        return row


def claim_due_notifications(*, faculty_username, limit=20):
    """Atomically claim reminders due for one faculty member.

    scheduled_for is stored in application-local wall-clock time, so the
    comparison and delivered_at update intentionally use the same local
    timezone-derived naive timestamp rather than MySQL's server timezone.
    """
    with connect() as c:
        local_cutoff = local_now().replace(tzinfo=None)
        rows = c.execute(
            """
            SELECT n.*, t.section_name, t.academic_year, s.code AS subject_code, s.name AS subject_name,
                   e.custom_label, e.room
            FROM faculty_class_notifications n
            JOIN timetable_entries e ON e.id=n.timetable_entry_id
            JOIN timetables t ON t.id=e.timetable_id
            LEFT JOIN subjects s ON s.id=e.subject_id
            WHERE LOWER(n.faculty_username)=LOWER(%s)
              AND n.status='PENDING'
              AND n.occurrence_date=%s
              AND n.scheduled_for BETWEEN %s AND %s
            ORDER BY n.scheduled_for ASC, n.id ASC
            LIMIT %s
            """,
            (
                faculty_username,
                local_cutoff.date(),
                local_cutoff - __import__('datetime').timedelta(minutes=3),
                local_cutoff,
                limit,
            ),
        ).fetchall()
        result = []
        for row in rows:
            cur = c.execute(
                "UPDATE faculty_class_notifications SET status='DELIVERED', delivered_at=%s WHERE id=%s AND status='PENDING'",
                (local_cutoff, row["id"]),
            )
            if cur.rowcount == 1:
                result.append(dict(row))
        return result
