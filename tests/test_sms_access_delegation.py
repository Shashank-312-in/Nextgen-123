from __future__ import annotations

import pytest

from sms_app.services import sms_access


class _Result:
    rowcount = 1
    lastrowid = 1

    def __init__(self, rows=None, row=None):
        self._rows = rows or []
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, faculty=None, semesters=None):
        self.faculty = faculty or {}
        self.semesters = set(semesters or [])
        self.access = {}
        self.delegations = set()
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        q = " ".join(sql.split()).lower()
        if q.startswith("select username, full_name, role, department, hod_username, active from users"):
            return _Result(row=self.faculty.get(params[0]))
        if q.startswith("select sem.id from academic_semesters"):
            requested = {int(x) for x in params[:-1]}
            return _Result(rows=[{"id": x} for x in sorted(requested & self.semesters)])
        if q.startswith("insert into sms_gateway_access"):
            faculty, hod, enabled, _, _ = params
            self.access[faculty] = {"hod_username": hod, "enabled": enabled}
            return _Result()
        if q.startswith("delete from sms_gateway_batch_delegations"):
            faculty = params[0]
            self.delegations = {d for d in self.delegations if d[0] != faculty}
            return _Result()
        if q.startswith("insert into sms_gateway_batch_delegations"):
            faculty, hod, semester_id = params
            self.delegations.add((faculty, hod, int(semester_id)))
            return _Result()
        if q.startswith("select auto_send"):
            return _Result(row=None)
        raise AssertionError(f"Unhandled SQL: {sql}")


def test_hod_cannot_delegate_outside_faculty_scope(monkeypatch):
    conn = _Conn(faculty={"naveen": {"username": "naveen", "role": "FACULTY", "hod_username": "otherhod", "active": 1}})
    monkeypatch.setattr("database.audit", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="outside your HOD scope"):
        sms_access.set_faculty_sms_access(
            conn,
            hod_username="csdhod",
            faculty_username="naveen",
            enabled=True,
            batch_ids=[1],
            actor="csdhod",
        )
    assert conn.access == {}


def test_hod_can_delegate_only_batches_in_scope(monkeypatch):
    conn = _Conn(
        faculty={"naveen": {"username": "naveen", "role": "FACULTY", "hod_username": "csdhod", "active": 1}},
        semesters=[10],
    )
    monkeypatch.setattr("database.audit", lambda *args, **kwargs: None)
    sms_access.set_faculty_sms_access(
        conn,
        hod_username="csdhod",
        faculty_username="naveen",
        enabled=True,
        batch_ids=[10],
        actor="csdhod",
    )
    assert conn.access["naveen"] == {"hod_username": "csdhod", "enabled": 1}
    assert conn.delegations == {("naveen", "csdhod", 10)}

    with pytest.raises(ValueError, match="outside your HOD scope"):
        sms_access.set_faculty_sms_access(
            conn,
            hod_username="csdhod",
            faculty_username="naveen",
            enabled=True,
            batch_ids=[11],
            actor="csdhod",
        )


def test_revocation_removes_all_delegations(monkeypatch):
    conn = _Conn(faculty={"naveen": {"username": "naveen", "role": "FACULTY", "hod_username": "csdhod", "active": 1}})
    conn.access["naveen"] = {"hod_username": "csdhod", "enabled": 1}
    conn.delegations = {("naveen", "csdhod", 10), ("naveen", "csdhod", 11)}
    monkeypatch.setattr("database.audit", lambda *args, **kwargs: None)
    sms_access.set_faculty_sms_access(conn, hod_username="csdhod", faculty_username="naveen", enabled=False, batch_ids=[], actor="csdhod")
    assert conn.access["naveen"]["enabled"] == 0
    assert conn.delegations == set()


def test_worker_validation_denies_revoked_or_undelegated(monkeypatch):
    # The worker delegates its final authorization to this service immediately before send.
    gateway = {"owner_username": "naveen", "hod_username": "csdhod"}
    row = {"roll_no": "01", "hod_username": "csdhod"}

    monkeypatch.setattr(sms_access, "faculty_can_use_batch", lambda *_: False)

    class C:
        def execute(self, *args, **kwargs):
            return _Result(row={"enabled": 1, "hod_username": "csdhod", "current_semester_id": 10, "faculty_active": 1})

    reason = sms_access.validate_delegated_queue_row(C(), row, gateway)
    assert reason == "The selected student batch is no longer delegated to this Faculty"
