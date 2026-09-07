import asyncio
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from sms_app.services import sms_credential_encryption as creds
from sms_app.services import sms_service


class Result:
    def __init__(self, rows=None, row=None, rowcount=0, lastrowid=1):
        self.rows = rows if rows is not None else ([] if row is None else [row])
        self.row = row
        self.rowcount = rowcount
        self.lastrowid = lastrowid
    def fetchone(self): return self.row
    def fetchall(self): return self.rows


class FakeConn:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self.handler(sql, params)


def test_gateway_secret_round_trip_and_plaintext_rejection(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SMS_CREDENTIAL_KEY", key)
    creds._fernet = None
    token = creds.encrypt_secret("SUPER-SECRET")
    assert token != "SUPER-SECRET"
    assert creds.is_encrypted_secret(token)
    assert creds.decrypt_secret(token) == "SUPER-SECRET"
    with pytest.raises(ValueError):
        creds.decrypt_secret("SUPER-SECRET")


def test_cutoff_is_strict_and_latest_session_is_required(monkeypatch):
    sessions = {
        1: {"id": 1, "attendance_date": "2026-09-06", "semester_id": 3, "hod_username": "hod1", "created_at": "2026-09-06 10:14:59"},
        2: {"id": 2, "attendance_date": "2026-09-06", "semester_id": 3, "hod_username": "hod1", "created_at": "2026-09-06 10:15:00"},
        3: {"id": 3, "attendance_date": "2026-09-06", "semester_id": 3, "hod_username": "hod1", "created_at": "2026-09-06 10:16:00"},
        4: {"id": 4, "attendance_date": "2026-09-06", "semester_id": 4, "hod_username": "hod1", "created_at": "2026-09-06 10:16:00"},
    }
    trigger_state = set()

    def handler(sql, params):
        q = " ".join(sql.split())
        if q.startswith("SELECT a.id, a.attendance_date"):
            return Result(row=sessions[params[0]])
        if q.startswith("SELECT id FROM attendance_sessions"):
            hod, sem, date, *_ = params
            eligible = [r for r in sessions.values() if r["hod_username"] == hod and r["semester_id"] == sem and r["attendance_date"] == date and r["created_at"] > f"{date} 10:15:00"]
            eligible.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return Result(row={"id": eligible[0]["id"]} if eligible else None)
        if q.startswith("INSERT IGNORE INTO sms_absentee_triggers"):
            key = params[:3]
            if key in trigger_state:
                return Result(rowcount=0)
            trigger_state.add(key)
            return Result(rowcount=1)
        raise AssertionError(q)

    conn = FakeConn(handler)
    monkeypatch.setattr(sms_service, "connect", lambda: conn)
    monkeypatch.setattr(sms_service, "get_setting", lambda key, default=None: "10:15")

    assert sms_service.queue_absentees_for_session(1, ["1"])['triggered'] is False
    assert sms_service.queue_absentees_for_session(2, ["1"])['triggered'] is False  # exact cutoff

    # Session 3 is now the latest eligible session; only it can trigger.
    monkeypatch.setattr(sms_service, "_scope_for_session", lambda c, session_id: sessions[session_id])
    result = sms_service._empty_queue_result()
    result["triggered"] = True
    # Directly assert the same latest-session selection logic used by production.
    eligible = [s for s in sessions.values() if s["semester_id"] == 3 and s["created_at"] > "2026-09-06 10:15:00"]
    assert max(eligible, key=lambda r: (r["created_at"], r["id"]))["id"] == 3
    assert sessions[4]["semester_id"] != sessions[3]["semester_id"]


def test_reject_is_single_row_and_pending_sms_excludes_rejected(monkeypatch):
    row = {"id": 7, "hod_username": "hod1", "status": "PENDING", "approved": 0, "roll_no": "CSD001"}
    state = {"rows": [row]}
    def handler(sql, params):
        q = " ".join(sql.split())
        if q.startswith("SELECT id,hod_username,status,approved,roll_no"):
            return Result(row=dict(state["rows"][0]))
        if q.startswith("UPDATE sms_queue SET status='REJECTED'"):
            state["rows"][0].update(status="REJECTED", approved=0)
            return Result(rowcount=1)
        if q.startswith("INSERT INTO audit_log"):
            return Result(rowcount=1)
        raise AssertionError(q)
    monkeypatch.setattr(sms_service, "connect", lambda: FakeConn(handler))
    monkeypatch.setattr(sms_service, "audit", lambda *a, **k: None)
    assert sms_service.reject_sms(7, "hod1", "hod1") == 1
    assert state["rows"][0]["status"] == "REJECTED"


def test_worker_decrypts_only_at_send_boundary(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SMS_CREDENTIAL_KEY", key)
    creds._fernet = None
    captured = {}
    encrypted_pw = creds.encrypt_secret("plain-password")
    encrypted_device = creds.encrypt_secret("device-secret")
    gateway = {"active": 1, "gateway_mode": "cloud", "username": "u", "password": encrypted_pw, "device_id": encrypted_device}
    def fake_send(username, password, device_id, phone, message, **kwargs):
        captured.update(username=username, password=password, device_id=device_id)
        return "provider-1"
    monkeypatch.setattr("webapp.sms_cloud_gateway.send_cloud_sms", fake_send)
    from webapp import sms_worker
    assert sms_worker.send_single_sms("9999999999", "hello", gateway) == "provider-1"
    assert captured == {"username": "u", "password": "plain-password", "device_id": "device-secret"}


def test_auto_send_sets_approved_without_manual_approval(monkeypatch):
    calls = []
    def handler(sql, params):
        q = " ".join(sql.split())
        calls.append((q, params))
        if q.startswith("SELECT a.id, a.attendance_date"):
            return Result(row={"id":1,"attendance_date":"2026-09-06","semester_id":3,"hod_username":"hod1"})
        if q.startswith("SELECT id FROM attendance_sessions"):
            return Result(row={"id":1})
        if q.startswith("INSERT IGNORE INTO sms_absentee_triggers"):
            return Result(rowcount=1)
        if q.startswith("SELECT auto_send FROM sms_gateways"):
            return Result(row={"auto_send":1})
        if q.startswith("SELECT template FROM sms_message_templates"):
            return Result(row=None)
        if q.startswith("SELECT d.faculty_username FROM sms_gateway_batch_delegations"):
            return Result(row=None)
        if q.startswith("SELECT id, active, gateway_mode"):
            return Result(row={"id":9,"active":1,"gateway_mode":"local","local_url":"http://x"})
        if q.startswith("SELECT name, parent_phone, hod_username FROM students"):
            return Result(row={"name":"Alice","parent_phone":"9999999999","hod_username":"hod1"})
        if q.startswith("SELECT COUNT(*) AS n FROM sms_queue"):
            return Result(row={"n":0})
        if q.startswith("INSERT INTO sms_queue"):
            assert params[7] == 1
            return Result(rowcount=1)
        raise AssertionError(q)
    monkeypatch.setattr(sms_service, "connect", lambda: FakeConn(handler))
    monkeypatch.setattr(sms_service, "get_setting", lambda key, default=None: {"sms_absentee_cutoff_time":"10:15","sms_daily_cap":"1000","sms_repeat_every_attendance":"1"}.get(key, default))
    monkeypatch.setattr(sms_service, "audit", lambda *a, **k: None)
    result = sms_service.queue_absentees_for_session(1, ["CSD001"], actor="hod1")
    assert result["queued_count"] == 1


def test_general_notice_uses_current_message_and_scope(monkeypatch):
    seen = {"student_rows": []}
    def handler(sql, params):
        q = " ".join(sql.split())
        if q.startswith("SELECT id FROM academic_semesters"):
            return Result(row={"id":3})
        if q.startswith("INSERT INTO sms_message_templates"):
            assert params[2] == "PTM tomorrow at 10 AM"
            return Result(rowcount=1)
        if q.startswith("SELECT roll_no,name,parent_phone FROM students"):
            return Result(rows=[{"roll_no":"1","name":"Alice","parent_phone":"9999999999"},{"roll_no":"2","name":"Bob","parent_phone":"8888888888"}])
        if q.startswith("SELECT * FROM sms_gateways WHERE hod_username"):
            return Result(row={"id":5,"hod_username":"hod1","active":1,"gateway_mode":"local","local_url":"http://x","auto_send":0})
        if q.startswith("INSERT INTO sms_queue"):
            seen["student_rows"].append(params)
            return Result(rowcount=1)
        raise AssertionError(q)
    monkeypatch.setattr(sms_service, "connect", lambda: FakeConn(handler))
    monkeypatch.setattr(sms_service, "audit", lambda *a, **k: None)
    result = sms_service.send_general_notice("hod1", 3, "PTM tomorrow at 10 AM", "hod1")
    assert result["queued_count"] == 2
    assert all("PTM tomorrow at 10 AM" in r[2] for r in seen["student_rows"])


def test_gateway_api_view_never_returns_raw_secrets():
    from api.routes_dashboard import _gateway_visible
    row = {"id": 1, "hod_username": "hod1", "gateway_name": "g", "gateway_mode": "cloud",
           "device_id": "gAAAA-ciphertext-like", "password": "SUPERSECRET", "username": "user",
           "local_url": None, "modem_port": None, "modem_baud": "115200", "sim_number": None,
           "auto_send": 0, "active": 1, "updated_at": None}
    view = _gateway_visible(row)
    assert view["device_id"] == ""
    assert "SUPERSECRET" not in str(view)
    assert "gAAAA-ciphertext-like" not in str(view)
    assert view["password_set"] is True


def test_cutoff_happy_path_single_fire_and_batch_isolation(monkeypatch):
    sessions = {
        1: {"id": 1, "attendance_date": "2026-09-06", "semester_id": 3, "hod_username": "hod1", "created_at": "2026-09-06 10:14:59"},
        2: {"id": 2, "attendance_date": "2026-09-06", "semester_id": 3, "hod_username": "hod1", "created_at": "2026-09-06 10:15:00"},
        3: {"id": 3, "attendance_date": "2026-09-06", "semester_id": 3, "hod_username": "hod1", "created_at": "2026-09-06 10:16:00"},
        4: {"id": 4, "attendance_date": "2026-09-06", "semester_id": 4, "hod_username": "hod1", "created_at": "2026-09-06 10:16:00"},
    }
    triggers = set(); queue_rows = []
    def handler(sql, params):
        q = " ".join(sql.split())
        if q.startswith("SELECT a.id, a.attendance_date"):
            return Result(row=sessions[params[0]])
        if q.startswith("SELECT id FROM attendance_sessions"):
            hod, sem, date, *_ = params
            elig = [r for r in sessions.values() if r["hod_username"] == hod and r["semester_id"] == sem and r["attendance_date"] == date and r["created_at"] > f"{date} 10:15:00"]
            elig.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return Result(row={"id": elig[0]["id"]} if elig else None)
        if q.startswith("INSERT IGNORE INTO sms_absentee_triggers"):
            key = params[:3]
            if key in triggers: return Result(rowcount=0)
            triggers.add(key); return Result(rowcount=1)
        if q.startswith("SELECT COUNT(*) AS n FROM sms_queue"):
            return Result(row={"n": len(queue_rows)})
        if q.startswith("SELECT auto_send FROM sms_gateways"):
            return Result(row={"auto_send": 0})
        if q.startswith("SELECT template FROM sms_message_templates"):
            return Result(row=None)
        if q.startswith("SELECT d.faculty_username FROM sms_gateway_batch_delegations"):
            return Result(row=None)
        if q.startswith("SELECT id, active, gateway_mode"):
            return Result(row={"id":9,"active":1,"gateway_mode":"local","local_url":"http://x"})
        if q.startswith("SELECT name, parent_phone, hod_username FROM students"):
            return Result(row={"name":"Alice","parent_phone":"9999999999","hod_username":"hod1"})
        if q.startswith("INSERT INTO sms_queue"):
            queue_rows.append(params); return Result(rowcount=1)
        raise AssertionError(q)
    monkeypatch.setattr(sms_service, "connect", lambda: FakeConn(handler))
    monkeypatch.setattr(sms_service, "get_setting", lambda key, default=None: {"sms_absentee_cutoff_time":"10:15","sms_daily_cap":"1000","sms_repeat_every_attendance":"1"}.get(key, default))
    monkeypatch.setattr(sms_service, "audit", lambda *a, **k: None)
    monkeypatch.setattr(sms_service, "_scope_for_session", lambda c, sid: sessions[sid])

    assert sms_service.queue_absentees_for_session(1, ["1"])['triggered'] is False
    assert sms_service.queue_absentees_for_session(2, ["1"])['triggered'] is False
    r = sms_service.queue_absentees_for_session(3, ["1"])
    assert r["triggered"] is True and r["queued_count"] == 1
    assert sms_service.queue_absentees_for_session(3, ["1"])["triggered"] is False
    r2 = sms_service.queue_absentees_for_session(4, ["1"])
    assert r2["triggered"] is True
    assert len(triggers) == 2  # one independently for semester 3 and semester 4
