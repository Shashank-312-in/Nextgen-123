"""Minute-level materialization of faculty class reminders.

The first delivery tier is intentionally in-app polling rather than browser
Web Push: the codebase has no existing VAPID/service-worker infrastructure,
and this keeps the reminder scheduler deterministic and dependency-light.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from sms_app.services.timetable_service import app_timezone, resolve_effective_schedule, local_now
from database import connect

logger = logging.getLogger("notification_worker")
POLL_SECONDS = 60


def materialize_due_notifications(now: datetime | None = None) -> int:
    now = now or local_now()
    target_date = now.date()
    created = 0
    rows = resolve_effective_schedule(faculty_username="", target_date=target_date)
    with connect() as c:
        faculty_rows = c.execute(
            "SELECT username FROM users WHERE role='FACULTY' AND active=1"
        ).fetchall()
        active_faculty = {str(item["username"]).casefold() for item in faculty_rows}
        for row in rows:
            if not row.get("faculty_username") or not row.get("start_time"):
                continue
            if str(row["faculty_username"]).casefold() not in active_faculty:
                continue
            try:
                start = datetime.combine(target_date, datetime.strptime(row["start_time"], "%H:%M").time(), tzinfo=app_timezone())
            except ValueError:
                continue
            scheduled_for = start - timedelta(minutes=5)
            # Materialize only inside a narrow window. This prevents a worker
            # that was asleep for hours from flooding users with stale alerts.
            if not (scheduled_for <= now <= scheduled_for + timedelta(minutes=1, seconds=POLL_SECONDS)):
                continue
            try:
                cur = c.execute(
                    """
                    INSERT INTO faculty_class_notifications(
                        faculty_username, timetable_entry_id, occurrence_date, scheduled_for, status
                    ) VALUES(%s,%s,%s,%s,'PENDING')
                    ON DUPLICATE KEY UPDATE
                        scheduled_for=VALUES(scheduled_for),
                        status=CASE WHEN status='CANCELLED' THEN 'PENDING' ELSE status END
                    """,
                    (row["faculty_username"], row["timetable_entry_id"], target_date.isoformat(), scheduled_for.replace(tzinfo=None)),
                )
                # MySQL reports 2 for an update, 1 for an insert; count only
                # genuine inserts for the worker log.
                if cur.rowcount == 1:
                    created += 1
            except Exception:
                logger.exception("notification_worker: failed to materialize entry %s", row.get("timetable_entry_id"))
    return created


async def run_forever():
    while True:
        try:
            materialize_due_notifications()
        except Exception:
            logger.exception("notification_worker: unexpected error")
        await asyncio.sleep(POLL_SECONDS)
