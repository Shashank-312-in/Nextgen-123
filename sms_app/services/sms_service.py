"""Database-backed absentee SMS queue and approval lifecycle.

SMS routing is owned by HOD scope, never by physical college block/location.
Each queue row snapshots both the responsible HOD and the exact gateway selected
at queue time. The worker therefore never has to guess which phone should send.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

from database import audit, connect, get_setting
from sms_app.services.sms_credential_encryption import is_encrypted_secret

ABSENTEE_TEMPLATE = "Dear Parent, {student} has not attended college today ({date}). - VCET CSD Dept"
GENERAL_TEMPLATE = "Dear Parent, {student}, VCET CSD Dept has an important notice: {message}"
MESSAGE_TEMPLATE = ABSENTEE_TEMPLATE  # compatibility alias; new sends load the saved per-scope template.
MAX_ATTEMPTS = 3
PROCESSING_LEASE_MINUTES = 15


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sms_enabled() -> bool:
    return _env_bool("SMS_ENABLED", get_setting("sms_enabled", "1") == "1")


def repeat_every_attendance() -> bool:
    return _env_bool("SMS_REPEAT_EVERY_ATTENDANCE", get_setting("sms_repeat_every_attendance", "1") == "1")


def _empty_queue_result():
    return {
        "queued_count": 0, "blocked_count": 0, "duplicate_count": 0,
        "skipped_no_phone": 0, "cap_blocked": 0, "repeat_every_attendance": repeat_every_attendance(),
        "triggered": False,
    }


def _scope_for_session(c, session_id):
    return c.execute("""
        SELECT a.id, a.attendance_date, a.semester_id, a.hod_username, a.created_at,
               s.name AS subject_name
        FROM attendance_sessions a
        LEFT JOIN subjects s ON s.id=a.subject_id
        WHERE a.id=%s
    """, (session_id,)).fetchone()


def _cutoff_time():
    raw = str(get_setting("sms_absentee_cutoff_time", "10:15") or "10:15").strip()
    try:
        hour, minute = [int(x) for x in raw.split(":", 1)]
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except Exception as exc:
        raise ValueError("sms_absentee_cutoff_time must be HH:MM") from exc
    return f"{hour:02d}:{minute:02d}"


def _gateway_ready_without_decrypt(gateway):
    mode = (gateway.get("gateway_mode") or "").lower()
    if mode == "cloud":
        return bool(gateway.get("device_id") and gateway.get("username") and gateway.get("password") and
                    is_encrypted_secret(gateway.get("device_id")) and is_encrypted_secret(gateway.get("password"))), "Cloud gateway is missing encrypted device ID or credentials; re-enter the gateway credentials."
    if mode == "local":
        return bool(gateway.get("local_url")), "Local gateway URL is missing."
    if mode == "modem":
        return bool(gateway.get("modem_port")), "Modem port is missing."
    return False, f"Unsupported SMS gateway mode: {mode or 'empty'}."


def _auto_send_enabled(c, hod_username):
    row = c.execute("SELECT auto_send FROM sms_gateways WHERE hod_username=%s AND owner_username=%s AND active=1", (hod_username, hod_username)).fetchone()
    return bool(row and row.get("auto_send"))


def _template_for_scope(c, hod_username, message_type):
    row = c.execute(
        "SELECT template FROM sms_message_templates WHERE hod_username=%s AND message_type=%s",
        (hod_username, message_type),
    ).fetchone()
    if row:
        return row["template"]
    return ABSENTEE_TEMPLATE if message_type == "ABSENTEE_ALERT" else "Dear Parent, {student}: {message} - VCET CSD Dept"




def _gateway_for_sms_batch(c, hod_username: str, semester_id: int):
    """Resolve the active SMS handler for one batch inside one HOD scope."""
    delegated = c.execute("""
        SELECT d.faculty_username
        FROM sms_gateway_batch_delegations d
        JOIN sms_gateway_access a
          ON a.faculty_username=d.faculty_username
         AND a.hod_username=d.hod_username
         AND a.enabled=1
        JOIN users u
          ON u.username=d.faculty_username AND u.role='FACULTY' AND u.active=1
        WHERE d.hod_username=%s AND d.semester_id=%s AND d.active=1
        ORDER BY d.updated_at DESC, d.faculty_username
        LIMIT 1
    """, (hod_username, semester_id)).fetchone()
    if delegated:
        faculty_username = delegated.get("faculty_username")
        gateway = c.execute(
            "SELECT * FROM sms_gateways WHERE hod_username=%s AND owner_username=%s AND active=1",
            (hod_username, faculty_username),
        ).fetchone()
        if gateway:
            return gateway
    # Keep the HOD fallback projection compatible with older deployments/tests.
    # Real rows carry owner_username, while the old test double may not.
    return c.execute(
        "SELECT id, active, gateway_mode, device_id, username, password, local_url, modem_port, auto_send, owner_username FROM sms_gateways WHERE hod_username=%s AND owner_username=%s",
        (hod_username, hod_username),
    ).fetchone()

def queue_absentees_for_session(session_id, absent_roll_nos, actor="system"):
    """Gate absentee SMS on the post-cutoff latest session and single-fire scope."""
    result = _empty_queue_result()
    if not absent_roll_nos:
        return result

    with connect() as c:
        session = _scope_for_session(c, session_id)
        if not session:
            return result
        hod_username = session.get("hod_username")
        send_date = session["attendance_date"]
        semester_id = session["semester_id"]
        cutoff = _cutoff_time()

        # The current session qualifies only when it is strictly after the cutoff
        # and is the most recently posted qualifying session for this batch/day.
        latest = c.execute("""
            SELECT id
            FROM attendance_sessions
            WHERE hod_username=%s AND semester_id=%s AND attendance_date=%s
              AND created_at > CONCAT(%s, ' ', %s)
              AND created_at < DATE_ADD(CONCAT(%s, ' 00:00:00'), INTERVAL 1 DAY)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """, (hod_username, semester_id, send_date, send_date, cutoff, send_date)).fetchone()
        if not hod_username or not latest or int(latest["id"]) != int(session_id):
            return result

        # INSERT IGNORE gives a real DB-unique single-fire boundary under races.
        trigger_cur = c.execute("""
            INSERT IGNORE INTO sms_absentee_triggers(hod_username,semester_id,attendance_date,session_id)
            VALUES(%s,%s,%s,%s)
        """, (hod_username, semester_id, send_date, session_id))
        if trigger_cur.rowcount != 1:
            return result
        result["triggered"] = True

        cap = int(get_setting("sms_daily_cap", "1000") or 1000)
        already_today = c.execute(
            "SELECT COUNT(*) AS n FROM sms_queue WHERE send_date=%s", (send_date,)
        ).fetchone()["n"]
        repeat_mode = repeat_every_attendance()
        auto_send = False
        template = _template_for_scope(c, hod_username, "ABSENTEE_ALERT")
        queued = blocked = duplicate = skipped_no_phone = cap_blocked = 0

        for roll_no in absent_roll_nos:
            student = c.execute("""
                SELECT name, parent_phone, hod_username
                FROM students WHERE roll_no=%s AND active=1 AND current_semester_id=%s
            """, (roll_no, semester_id)).fetchone()
            if not student:
                blocked += 1
                continue
            if not repeat_mode:
                existing = c.execute(
                    "SELECT id,status FROM sms_queue WHERE roll_no=%s AND send_date=%s ORDER BY id DESC LIMIT 1",
                    (roll_no, send_date),
                ).fetchone()
                if existing:
                    duplicate += 1
                    continue
            if already_today + queued >= cap:
                cap_blocked += 1
                continue

            phone = (student.get("parent_phone") or "").strip()
            routing_error = None
            gateway_id = None
            gateway = _gateway_for_sms_batch(c, hod_username, semester_id)
            if not student.get("hod_username") or student.get("hod_username") != hod_username:
                routing_error = "Attendance/student HOD ownership mismatch; SMS is blocked until ownership is corrected."
            elif not phone:
                routing_error = "Parent phone number is missing for this student."
            elif not gateway:
                routing_error = "No active SMS gateway is configured for this batch or HOD."
            elif not gateway["active"]:
                routing_error = "The assigned SMS gateway is inactive."
            else:
                gateway_id = gateway["id"]
                ready, reason = _gateway_ready_without_decrypt(gateway)
                if not ready:
                    routing_error = reason
                else:
                    # Faculty gateways use their own saved auto-send flag.
                    # The HOD test double may omit owner_username/auto_send, so
                    # consult the HOD gateway setting only for an identifiable
                    # HOD-owned fallback.
                    selected_auto_send = bool(gateway.get("auto_send"))
                    owner = gateway.get("owner_username")
                    if owner in (None, "", hod_username):
                        selected_auto_send = _auto_send_enabled(c, hod_username)
                    if selected_auto_send:
                        auto_send = True

            try:
                message = template.format(student=student["name"], date=send_date, message="")
            except Exception as exc:
                raise ValueError(f"Invalid saved absentee template: {exc}") from exc

            approved = int(
                bool(gateway and (
                    gateway.get("auto_send")
                    or (gateway.get("owner_username") in (None, "", hod_username) and _auto_send_enabled(c, hod_username))
                ))
                and not routing_error
            )
            status = "PENDING"
            cur = c.execute("""
                INSERT INTO sms_queue(
                    roll_no,parent_phone,message,attendance_session_id,send_date,
                    hod_username,gateway_id,approved,message_type,status,error
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'ABSENTEE_ALERT','PENDING',%s)
                ON DUPLICATE KEY UPDATE id=id
            """, (roll_no, phone, message, session_id, send_date, hod_username, gateway_id, approved, routing_error))
            if cur.rowcount == 1:
                if routing_error:
                    blocked += 1
                    audit(c, actor, "SMS_BLOCKED", "sms_queue", f"roll={roll_no}; {routing_error}")
                else:
                    queued += 1
                already_today += 1
            else:
                duplicate += 1

        if queued or blocked or result["triggered"]:
            audit(c, actor, "SMS_QUEUED", "attendance_session",
                  f"session={session_id}; queued={queued}; blocked={blocked}; duplicate={duplicate}; cap_blocked={cap_blocked}; repeat_mode={int(repeat_mode)}; auto_send={int(auto_send)}; hod={hod_username}")
        result.update({
            "queued_count": queued, "blocked_count": blocked, "duplicate_count": duplicate,
            "skipped_no_phone": skipped_no_phone, "cap_blocked": cap_blocked,
            "repeat_every_attendance": repeat_mode,
        })
        return result


def pending_approval_for_hod(hod_username: str, send_date: str | None = None):
    with connect() as c:
        if send_date:
            return c.execute("""
                SELECT q.*, s.name AS student_name, g.gateway_name, g.gateway_mode, g.active AS gateway_active
                FROM sms_queue q
                LEFT JOIN students s ON s.roll_no=q.roll_no
                LEFT JOIN sms_gateways g ON g.id=q.gateway_id
                WHERE q.hod_username=%s AND q.send_date=%s AND q.status='PENDING' AND q.approved=0
                ORDER BY q.created_at, q.id
            """, (hod_username, send_date)).fetchall()
        return c.execute("""
            SELECT q.*, s.name AS student_name, g.gateway_name, g.gateway_mode, g.active AS gateway_active
            FROM sms_queue q
            LEFT JOIN students s ON s.roll_no=q.roll_no
            LEFT JOIN sms_gateways g ON g.id=q.gateway_id
            WHERE q.hod_username=%s AND q.status='PENDING' AND q.approved=0
            ORDER BY q.send_date DESC, q.created_at, q.id
            LIMIT 200
        """, (hod_username,)).fetchall()


def approve_sms_batch(hod_username: str, send_date: str, actor: str):
    """Approve a whole HOD/day batch only after every row is actually sendable.

    The existing gateway snapshot is retained. A missing snapshot may be filled
    only from the active gateway of the same HOD; rows never cross HOD scopes.
    Missing recipient numbers and ownership problems remain blocked.
    """
    with connect() as c:
        rows = c.execute("""
            SELECT q.*, s.name AS student_name, s.parent_phone AS current_parent_phone,
                   s.hod_username AS student_hod_username
            FROM sms_queue q
            LEFT JOIN students s ON s.roll_no=q.roll_no
            WHERE q.hod_username=%s AND q.send_date=%s
              AND q.status='PENDING' AND q.approved=0
            FOR UPDATE
        """, (hod_username, send_date)).fetchall()
        if not rows:
            return 0

        active_gateway = c.execute(
            "SELECT * FROM sms_gateways WHERE hod_username=%s AND owner_username=%s AND active=1",
            (hod_username, hod_username),
        ).fetchone()

        updates = []
        for row in rows:
            parent_phone = (row.get("current_parent_phone") or row.get("parent_phone") or "").strip()
            if not parent_phone:
                raise ValueError(f"Cannot approve {row['roll_no']}: parent phone number is missing.")
            if row.get("student_hod_username") != hod_username:
                raise ValueError(f"Cannot approve {row['roll_no']}: student HOD ownership does not match this approval scope.")

            gateway = None
            if row.get("gateway_id"):
                gateway = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (row["gateway_id"],)).fetchone()
            if gateway is None:
                gateway = active_gateway
                if gateway:
                    c.execute("UPDATE sms_queue SET gateway_id=%s WHERE id=%s", (gateway["id"], row["id"]))
            if not gateway or not gateway["active"] or gateway.get("hod_username") != hod_username:
                raise ValueError(f"Cannot approve {row['roll_no']}: no active gateway is assigned to this HOD.")

            mode = (gateway.get("gateway_mode") or "").lower()
            if mode == "cloud":
                valid = bool(gateway.get("device_id") and gateway.get("username") and gateway.get("password") and
                             is_encrypted_secret(gateway.get("device_id")) and is_encrypted_secret(gateway.get("password")))
                reason = "Cloud gateway credentials are missing or require re-entry for secure storage."
            elif mode == "local":
                valid = bool(gateway.get("local_url"))
                reason = "Local gateway URL is missing."
            elif mode == "modem":
                valid = bool(gateway.get("modem_port"))
                reason = "Modem port is missing."
            else:
                valid = False
                reason = f"Unsupported SMS gateway mode: {mode or 'empty'}."
            if not valid:
                c.execute("UPDATE sms_queue SET error=%s WHERE id=%s", (reason, row["id"]))
                raise ValueError(f"Cannot approve this batch: {reason}")
            updates.append((row["id"], parent_phone, gateway["id"]))

        for row_id, parent_phone, gateway_id in updates:
            c.execute("""
                UPDATE sms_queue
                SET parent_phone=%s, gateway_id=%s, approved=1, error=NULL
                WHERE id=%s AND status='PENDING' AND approved=0
            """, (parent_phone, gateway_id, row_id))
        audit(c, actor, "SMS_BATCH_APPROVED", "sms_queue", f"hod={hod_username}; date={send_date}; count={len(updates)}")
        return len(updates)


def approve_sms(queue_id: int, hod_username: str, actor: str):
    """Approve one queue row inside one HOD scope."""
    with connect() as c:
        row = c.execute("""
            SELECT q.*, s.parent_phone AS current_parent_phone, s.hod_username AS student_hod_username
            FROM sms_queue q LEFT JOIN students s ON s.roll_no=q.roll_no
            WHERE q.id=%s AND q.hod_username=%s AND q.status='PENDING' AND q.approved=0
            FOR UPDATE
        """, (queue_id, hod_username)).fetchone()
        if not row:
            raise ValueError("SMS queue row not found or not pending in your scope.")
        phone = (row.get("current_parent_phone") or row.get("parent_phone") or "").strip()
        if not phone:
            raise ValueError("Cannot approve: parent phone number is missing.")
        if row.get("student_hod_username") != hod_username:
            raise ValueError("Cannot approve: student HOD ownership does not match this approval scope.")
        gateway = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (row.get("gateway_id"),)).fetchone() if row.get("gateway_id") else None
        if not gateway:
            gateway = c.execute("SELECT * FROM sms_gateways WHERE hod_username=%s AND owner_username=%s AND active=1", (hod_username, hod_username)).fetchone()
        if not gateway or not gateway["active"] or gateway.get("hod_username") != hod_username:
            raise ValueError("Cannot approve: no active gateway is assigned to this HOD.")
        ready, reason = _gateway_ready_without_decrypt(gateway)
        if not ready:
            raise ValueError(reason)
        c.execute("UPDATE sms_queue SET parent_phone=%s,gateway_id=%s,approved=1,error=NULL WHERE id=%s AND status='PENDING' AND approved=0", (phone, gateway["id"], queue_id))
        audit(c, actor, "SMS_APPROVED", "sms_queue", f"id={queue_id}; hod={hod_username}")
        return 1


def reject_sms(queue_id: int, hod_username: str, actor: str):
    """Reject exactly one pending row, preserving the audit trail."""
    with connect() as c:
        row = c.execute("SELECT id,hod_username,status,approved,roll_no FROM sms_queue WHERE id=%s FOR UPDATE", (queue_id,)).fetchone()
        if not row:
            raise ValueError("SMS queue row not found")
        if row.get("hod_username") != hod_username:
            raise ValueError("You cannot reject another HOD's SMS")
        if row.get("status") != "PENDING" or int(row.get("approved") or 0) != 0:
            raise ValueError("Only a pending, unapproved SMS can be rejected")
        c.execute("UPDATE sms_queue SET status='REJECTED',approved=0,error=%s WHERE id=%s AND hod_username=%s AND status='PENDING' AND approved=0", ("Rejected by human reviewer", queue_id, hod_username))
        audit(c, actor, "SMS_REJECTED", "sms_queue", f"id={queue_id}; roll={row.get('roll_no')}; hod={hod_username}")
        return 1


def save_message_template(hod_username: str, message_type: str, template: str, actor: str):
    if message_type not in ("ABSENTEE_ALERT", "GENERAL_NOTICE"):
        raise ValueError("Unsupported message type")
    template = str(template or "").strip()
    if not template:
        raise ValueError("Message template cannot be empty")
    with connect() as c:
        c.execute("""
            INSERT INTO sms_message_templates(hod_username,message_type,template)
            VALUES(%s,%s,%s)
            ON DUPLICATE KEY UPDATE template=%s
        """, (hod_username, message_type, template, template))
        audit(c, actor, "SMS_TEMPLATE_SAVED", "sms_message_templates", f"hod={hod_username}; type={message_type}")
    return template


def send_general_notice_as_faculty(faculty_username: str, semester_id: int, message: str, actor: str):
    """Queue a General Notice only for a batch delegated to this Faculty.

    This is deliberately separate from the HOD path so the ordinary HOD queue
    and approval semantics remain unchanged. The faculty gateway is always
    resolved server-side from its owner_username; the client cannot choose a
    different gateway or HOD scope.
    """
    message = str(message or "").strip()
    if not message:
        raise ValueError("General Notice message cannot be empty")
    from sms_app.services.sms_access import faculty_can_use_batch, faculty_gateway, faculty_sms_enabled
    with connect() as c:
        access = c.execute(
            "SELECT hod_username,enabled FROM sms_gateway_access WHERE faculty_username=%s",
            (faculty_username,),
        ).fetchone()
        if not access or not bool(access.get("enabled")):
            raise ValueError("SMS Gateway access has been revoked by your HOD")
        hod_username = access["hod_username"]
        faculty = c.execute(
            "SELECT username,role,active,hod_username FROM users WHERE username=%s",
            (faculty_username,),
        ).fetchone()
        if not faculty or faculty.get("role") != "FACULTY" or not bool(faculty.get("active")):
            raise ValueError("Faculty account is inactive or unavailable")
        if (faculty.get("hod_username") or "").strip().lower() != (hod_username or "").strip().lower():
            raise ValueError("Faculty HOD scope no longer matches SMS delegation")
        if not faculty_can_use_batch(c, faculty_username, semester_id):
            raise ValueError("The selected batch is not delegated to you for SMS")

        semester = c.execute("SELECT id FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not semester:
            raise ValueError("Selected batch does not exist")
        gateway = faculty_gateway(c, faculty_username)
        if not gateway or not gateway.get("active"):
            raise ValueError("Configure an active SMS gateway before sending")
        ready, reason = _gateway_ready_without_decrypt(gateway)
        if not ready:
            raise ValueError(reason)

        students = c.execute("""
            SELECT roll_no,name,parent_phone
            FROM students
            WHERE active=1 AND hod_username=%s AND current_semester_id=%s
            ORDER BY roll_no
        """, (hod_username, semester_id)).fetchall()
        if not students:
            raise ValueError("The delegated batch has no active students")

        queued = 0
        blocked = 0
        for student in students:
            phone = (student.get("parent_phone") or "").strip()
            row_error = "Parent phone number is missing." if not phone else None
            try:
                msg = message.format(student=student["name"], date="", message=message)
            except Exception as exc:
                raise ValueError(f"Invalid SMS message template: {exc}") from exc
            c.execute("""
                INSERT INTO sms_queue(
                    roll_no,parent_phone,message,attendance_session_id,send_date,
                    hod_username,gateway_id,approved,message_type,status,error
                ) VALUES(%s,%s,%s,NULL,CURRENT_DATE,%s,%s,%s,'GENERAL_NOTICE','PENDING',%s)
            """, (student["roll_no"], phone, msg, hod_username, gateway["id"], int(not row_error), row_error))
            if row_error:
                blocked += 1
            else:
                queued += 1

        audit(
            c, actor, "GENERAL_NOTICE_QUEUED", "sms_queue",
            f"faculty={faculty_username}; hod={hod_username}; semester_id={semester_id}; gateway={gateway['id']}; queued={queued}; blocked={blocked}; auto_send=1",
        )
        return {"queued_count": queued, "blocked_count": blocked, "template": message}


def send_general_notice(hod_username: str, semester_id: int, message: str, actor: str):
    """Queue the same custom notice for every active student in one HOD batch."""
    message = str(message or "").strip()
    if not message:
        raise ValueError("General Notice message cannot be empty")
    with connect() as c:
        semester = c.execute("SELECT id FROM academic_semesters WHERE id=%s", (semester_id,)).fetchone()
        if not semester:
            raise ValueError("Selected batch does not exist")
        template = message
        c.execute("""
            INSERT INTO sms_message_templates(hod_username,message_type,template)
            VALUES(%s,'GENERAL_NOTICE',%s)
            ON DUPLICATE KEY UPDATE template=%s
        """, (hod_username, message, message))
        students = c.execute("""
            SELECT roll_no,name,parent_phone FROM students
            WHERE active=1 AND hod_username=%s AND current_semester_id=%s
            ORDER BY roll_no
        """, (hod_username, semester_id)).fetchall()
        gateway = c.execute("SELECT * FROM sms_gateways WHERE hod_username=%s AND owner_username=%s AND active=1", (hod_username, hod_username)).fetchone()
        ready, reason = _gateway_ready_without_decrypt(gateway or {})
        if not gateway:
            ready = False; reason = "No active SMS gateway is configured for this HOD."
        auto_send = bool(gateway and gateway.get("auto_send") and ready)
        queued = 0; blocked = 0
        for student in students:
            phone = (student.get("parent_phone") or "").strip()
            row_error = None if phone and ready else ("Parent phone number is missing." if not phone else reason)
            msg = template.format(student=student["name"], date="", message=message) if "{message}" in template or "{student}" in template else template
            c.execute("""
                INSERT INTO sms_queue(roll_no,parent_phone,message,attendance_session_id,send_date,hod_username,gateway_id,approved,message_type,status,error)
                VALUES(%s,%s,%s,NULL,CURRENT_DATE,%s,%s,%s,'GENERAL_NOTICE','PENDING',%s)
            """, (student["roll_no"], phone, msg, hod_username, gateway["id"] if gateway else None, int(auto_send and not row_error), row_error))
            if row_error: blocked += 1
            else: queued += 1
        audit(c, actor, "GENERAL_NOTICE_QUEUED", "sms_queue", f"hod={hod_username}; semester_id={semester_id}; queued={queued}; blocked={blocked}; auto_send={int(auto_send)}")
        return {"queued_count": queued, "blocked_count": blocked, "template": message}


def pending_sms(limit=25, hod_username=None):
    """Atomically claim approved queue rows so concurrent workers cannot send twice."""
    _recover_stale_processing()
    claimed = []
    with connect() as c:
        if hod_username:
            candidates = c.execute("""
                SELECT id FROM sms_queue
                WHERE status='PENDING' AND approved=1 AND hod_username=%s
                ORDER BY created_at, id
                LIMIT %s
            """, (hod_username, limit)).fetchall()
        else:
            candidates = c.execute("""
                SELECT id FROM sms_queue
                WHERE status='PENDING' AND approved=1
                ORDER BY created_at, id
                LIMIT %s
            """, (limit,)).fetchall()
        for candidate in candidates:
            cur = c.execute("""
                UPDATE sms_queue
                SET status='PROCESSING', attempt_count=attempt_count+1,
                    processing_started_at=CURRENT_TIMESTAMP
                WHERE id=%s AND status='PENDING' AND approved=1
            """, (candidate["id"],))
            if cur.rowcount:
                row = c.execute("SELECT * FROM sms_queue WHERE id=%s", (candidate["id"],)).fetchone()
                if row:
                    claimed.append(row)
    return claimed


def _recover_stale_processing():
    with connect() as c:
        c.execute("""
            UPDATE sms_queue
            SET status='PENDING', processing_started_at=NULL,
                error=COALESCE(error, 'Recovered stale worker lease')
            WHERE status='PROCESSING'
              AND processing_started_at IS NOT NULL
              AND processing_started_at < DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s MINUTE)
              AND attempt_count < %s
        """, (PROCESSING_LEASE_MINUTES, MAX_ATTEMPTS))


def mark_sent(sms_id, provider_message_id=None, actor="system"):
    with connect() as c:
        row=c.execute("SELECT q.roll_no,q.hod_username,q.gateway_id,g.owner_username,aq.semester_id FROM sms_queue q LEFT JOIN sms_gateways g ON g.id=q.gateway_id LEFT JOIN attendance_sessions aq ON aq.id=q.attendance_session_id WHERE q.id=%s",(sms_id,)).fetchone()
        c.execute("UPDATE sms_queue SET status='SENT',sent_at=CURRENT_TIMESTAMP,error=NULL,processing_started_at=NULL,provider_message_id=COALESCE(%s,provider_message_id) WHERE id=%s AND status='PROCESSING'",(provider_message_id,sms_id))
        if row:
            d=[f"roll={row['roll_no']}","count=1"]; [d.append(f"{k}={row[k]}") for k in ("hod_username","gateway_id","owner_username","semester_id") if row.get(k)]; audit(c,actor,"SMS_SENT","student","; ".join(x.replace("hod_username=","hod=").replace("gateway_id=","gateway=").replace("owner_username=","owner=").replace("semester_id=","batch=") for x in d))


def mark_failed(sms_id, error, *, retryable=True, actor="system"):
    with connect() as c:
        row=c.execute("SELECT q.roll_no,q.hod_username,q.gateway_id,g.owner_username,aq.semester_id,q.attempt_count FROM sms_queue q LEFT JOIN sms_gateways g ON g.id=q.gateway_id LEFT JOIN attendance_sessions aq ON aq.id=q.attendance_session_id WHERE q.id=%s",(sms_id,)).fetchone()
        if not row:return
        terminal=(not retryable) or int(row.get("attempt_count") or 0)>=MAX_ATTEMPTS; status="FAILED" if terminal else "PENDING"; approved=0 if terminal else 1
        c.execute("UPDATE sms_queue SET status=%s,approved=%s,error=%s,processing_started_at=NULL WHERE id=%s AND status='PROCESSING'",(status,approved,str(error)[:500],sms_id))
        d=[f"roll={row['roll_no']}","count=1"]; [d.append(f"{k}={row[k]}") for k in ("hod_username","gateway_id","owner_username","semester_id") if row.get(k)]; d.append(f"error={str(error)[:200]}"); audit(c,actor,"SMS_FAILED" if terminal else "SMS_RETRY_SCHEDULED","student","; ".join(x.replace("hod_username=","hod=").replace("gateway_id=","gateway=").replace("owner_username=","owner=").replace("semester_id=","batch=") for x in d))


def retry_failed_sms(sms_id: int, hod_username: str | None = None, actor="system"):
    """Put one terminally failed row back into the approved queue.

    Routing is never changed here. The existing gateway_id/HOD snapshot is
    retained, so retry cannot accidentally switch a message to another HOD's
    phone.
    """
    with connect() as c:
        row = c.execute(
            "SELECT id,hod_username,gateway_id,status,attempt_count FROM sms_queue WHERE id=%s",
            (sms_id,),
        ).fetchone()
        if not row:
            raise ValueError("SMS queue row not found")
        if hod_username and row.get("hod_username") != hod_username:
            raise ValueError("You cannot retry another HOD's SMS")
        if row.get("status") != "FAILED":
            raise ValueError("Only failed SMS rows can be retried")
        if not row.get("gateway_id"):
            raise ValueError("This SMS has no assigned gateway and cannot be retried")
        c.execute("""
            UPDATE sms_queue
            SET status='PENDING', approved=1, error=NULL, processing_started_at=NULL,
                attempt_count=0
            WHERE id=%s AND status='FAILED'
        """, (sms_id,))
        audit(c, actor, "SMS_RETRY_REQUESTED", "sms_queue", f"id={sms_id}; hod={row.get('hod_username')}")
        return True


def recent_sms(limit=100, hod_username=None, owner_username=None):
    with connect() as c:
        where = ""
        params = [limit]
        if owner_username:
            where = "WHERE g.owner_username=%s"
            params = [owner_username, limit]
        elif hod_username:
            where = "WHERE q.hod_username=%s"
            params = [hod_username, limit]
        return c.execute(f"""
            SELECT q.*, s.name AS student_name, g.gateway_name, g.gateway_mode,
                   g.owner_username AS gateway_owner_username, u.full_name AS gateway_owner_name
            FROM sms_queue q
            LEFT JOIN students s ON s.roll_no=q.roll_no
            LEFT JOIN sms_gateways g ON g.id=q.gateway_id
            LEFT JOIN users u ON u.username=g.owner_username
            {where}
            ORDER BY q.created_at DESC LIMIT %s
        """, params).fetchall()
