"""SMS-only faculty delegation rules.

This module deliberately does not alter ordinary Faculty permissions. It owns
only the HOD -> Faculty -> SMS Gateway -> allowed batch relationship.
"""
from __future__ import annotations


def _norm(value: str | None) -> str:
    return str(value or "").strip().lower()


def get_faculty_scope(c, faculty_username: str):
    return c.execute(
        """
        SELECT username, full_name, role, department, hod_username, active
        FROM users
        WHERE username=%s AND role='FACULTY'
        """,
        (faculty_username,),
    ).fetchone()


def get_faculty_sms_access(c, faculty_username: str):
    return c.execute(
        "SELECT faculty_username, hod_username, enabled FROM sms_gateway_access WHERE faculty_username=%s",
        (faculty_username,),
    ).fetchone()


def faculty_sms_enabled(c, faculty_username: str) -> bool:
    row = get_faculty_sms_access(c, faculty_username)
    return bool(row and row.get("enabled"))


def allowed_batch_ids(c, faculty_username: str) -> set[int]:
    rows = c.execute(
        """
        SELECT d.semester_id
        FROM sms_gateway_batch_delegations d
        JOIN sms_gateway_access a
          ON a.faculty_username=d.faculty_username AND a.enabled=1
        WHERE d.faculty_username=%s AND d.active=1
        """,
        (faculty_username,),
    ).fetchall()
    return {int(r["semester_id"]) for r in rows}


def faculty_can_use_batch(c, faculty_username: str, semester_id: int) -> bool:
    return bool(
        c.execute(
            """
            SELECT 1
            FROM sms_gateway_access a
            JOIN sms_gateway_batch_delegations d
              ON d.faculty_username=a.faculty_username
             AND d.hod_username=a.hod_username
             AND d.semester_id=%s
             AND d.active=1
            WHERE a.faculty_username=%s AND a.enabled=1
            LIMIT 1
            """,
            (semester_id, faculty_username),
        ).fetchone()
    )


def batches_for_hod(c, hod_username: str):
    return c.execute(
        """
        SELECT sem.id, sem.name, sem.code, COUNT(st.roll_no) AS student_count
        FROM academic_semesters sem
        JOIN students st
          ON st.current_semester_id=sem.id
         AND st.active=1
         AND LOWER(COALESCE(st.hod_username,''))=LOWER(%s)
        GROUP BY sem.id, sem.name, sem.code, sem.sort_order
        ORDER BY sem.sort_order, sem.id
        """,
        (hod_username,),
    ).fetchall()


def batches_for_faculty(c, faculty_username: str):
    return c.execute(
        """
        SELECT sem.id, sem.name, sem.code, COUNT(st.roll_no) AS student_count
        FROM sms_gateway_batch_delegations d
        JOIN sms_gateway_access a
          ON a.faculty_username=d.faculty_username
         AND a.hod_username=d.hod_username
         AND a.enabled=1
        JOIN academic_semesters sem ON sem.id=d.semester_id
        JOIN students st
          ON st.current_semester_id=sem.id
         AND st.active=1
         AND LOWER(COALESCE(st.hod_username,''))=LOWER(d.hod_username)
        WHERE d.faculty_username=%s AND d.active=1
        GROUP BY sem.id, sem.name, sem.code, sem.sort_order
        ORDER BY sem.sort_order, sem.id
        """,
        (faculty_username,),
    ).fetchall()


def list_hod_sms_access(c, hod_username: str):
    rows = c.execute(
        """
        SELECT u.username, u.full_name, u.active, COALESCE(a.enabled,0) AS enabled
        FROM users u
        LEFT JOIN sms_gateway_access a
          ON a.faculty_username=u.username AND a.hod_username=u.hod_username
        WHERE u.role='FACULTY'
          AND LOWER(COALESCE(u.hod_username,''))=LOWER(%s)
        ORDER BY u.full_name, u.username
        """,
        (hod_username,),
    ).fetchall()

    batches = batches_for_hod(c, hod_username)
    by_faculty = {r["username"]: [] for r in rows}
    delegated_rows = c.execute(
        """
        SELECT d.faculty_username, sem.id, sem.name, sem.code
        FROM sms_gateway_batch_delegations d
        JOIN sms_gateway_access a
          ON a.faculty_username=d.faculty_username
         AND a.hod_username=d.hod_username
         AND a.enabled=1
        JOIN academic_semesters sem ON sem.id=d.semester_id
        WHERE LOWER(d.hod_username)=LOWER(%s) AND d.active=1
        ORDER BY sem.sort_order, sem.id
        """,
        (hod_username,),
    ).fetchall()
    for r in delegated_rows:
        by_faculty.setdefault(r["faculty_username"], []).append({
            "id": r["id"], "name": r["name"], "code": r["code"],
        })

    for row in rows:
        row["enabled"] = bool(row["enabled"])
        row["allowed_batches"] = by_faculty.get(row["username"], [])

    return rows, batches


def set_faculty_sms_access(c, *, hod_username: str, faculty_username: str, enabled: bool, batch_ids: list[int], actor: str):
    target = get_faculty_scope(c, faculty_username)
    if not target:
        raise ValueError("Faculty account not found")
    if not bool(target.get("active")):
        raise ValueError("Faculty account is inactive")
    if _norm(target.get("hod_username")) != _norm(hod_username):
        raise ValueError("You cannot delegate SMS Gateway access outside your HOD scope")

    requested: list[int] = []
    seen: set[int] = set()
    for raw in batch_ids or []:
        try:
            item = int(raw)
        except (TypeError, ValueError):
            raise ValueError("Invalid batch selected")
        if item not in seen:
            requested.append(item)
            seen.add(item)

    if requested:
        placeholders = ",".join(["%s"] * len(requested))
        rows = c.execute(
            f"""
            SELECT sem.id
            FROM academic_semesters sem
            WHERE sem.id IN ({placeholders})
              AND EXISTS (
                    SELECT 1 FROM students st
                    WHERE st.current_semester_id=sem.id
                      AND st.active=1
                      AND LOWER(COALESCE(st.hod_username,''))=LOWER(%s)
              )
            """,
            (*requested, hod_username),
        ).fetchall()
        allowed = {int(r["id"]) for r in rows}
        invalid = [x for x in requested if x not in allowed]
        if invalid:
            raise ValueError("One or more selected batches are outside your HOD scope")

    c.execute(
        """
        INSERT INTO sms_gateway_access(faculty_username,hod_username,enabled)
        VALUES(%s,%s,%s)
        ON DUPLICATE KEY UPDATE hod_username=%s, enabled=%s
        """,
        (faculty_username, hod_username, int(enabled), hod_username, int(enabled)),
    )
    # Clear every prior delegation for this Faculty. The user's HOD scope is
    # authoritative, so stale rows from a previous HOD must never reactivate.
    c.execute("DELETE FROM sms_gateway_batch_delegations WHERE faculty_username=%s", (faculty_username,))
    if enabled:
        for semester_id in requested:
            c.execute(
                """
                INSERT INTO sms_gateway_batch_delegations(faculty_username,hod_username,semester_id,active)
                VALUES(%s,%s,%s,1)
                """,
                (faculty_username, hod_username, semester_id),
            )
    from database import audit
    audit(
        c, actor, "SMS_ACCESS_UPDATED", "sms_gateway_access",
        f"faculty={faculty_username}; hod={hod_username}; enabled={int(enabled)}; batches={','.join(str(x) for x in requested) or '-'}",
    )


def faculty_gateway(c, faculty_username: str):
    return c.execute(
        """
        SELECT * FROM sms_gateways
        WHERE owner_username=%s
          AND hod_username=(SELECT hod_username FROM users WHERE username=%s)
        LIMIT 1
        """,
        (faculty_username, faculty_username),
    ).fetchone()


def validate_delegated_queue_row(c, row, gateway):
    """Return None when a queued faculty SMS is still authorized."""
    owner = _norm(gateway.get("owner_username"))
    hod = _norm(gateway.get("hod_username"))
    if not owner or owner == hod:
        return None

    access = c.execute(
        """
        SELECT a.enabled, a.hod_username, st.current_semester_id, u.active AS faculty_active
        FROM sms_gateway_access a
        JOIN users u ON u.username=a.faculty_username AND u.role='FACULTY'
        LEFT JOIN students st ON st.roll_no=%s
        WHERE a.faculty_username=%s
        """,
        (row.get("roll_no"), owner),
    ).fetchone()
    if not access or not bool(access.get("enabled")) or not bool(access.get("faculty_active")):
        return "Faculty SMS Gateway access has been revoked or the Faculty account is inactive"
    if _norm(access.get("hod_username")) != hod:
        return "Faculty SMS Gateway HOD scope no longer matches the queued message"
    semester_id = access.get("current_semester_id")
    if semester_id is None or not faculty_can_use_batch(c, owner, int(semester_id)):
        return "The selected student batch is no longer delegated to this Faculty"
    return None
