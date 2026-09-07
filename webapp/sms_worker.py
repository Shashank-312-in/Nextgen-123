"""Background SMS sender.

Dispatch is resolved per queue row. The worker never uses one global gateway
for absentee messages and never falls back from one HOD's gateway to another.
"""
from __future__ import annotations

import asyncio
import logging
import os

from database import connect, get_setting
from sms_app.services.sms_service import mark_failed, mark_sent, pending_sms, sms_enabled
from sms_app.services.sms_access import validate_delegated_queue_row
from sms_app.services.sms_credential_encryption import decrypt_secret
from webapp.sms_modem import ModemError, send_sms
from webapp.sms_android_gateway import AndroidGatewayError, send_android_sms
from webapp.sms_cloud_gateway import CloudGatewayError, send_cloud_sms

logger = logging.getLogger("sms_worker")
POLL_SECONDS = 10


class GatewayConfigurationError(Exception):
    pass


def _normalize_phone(phone: str) -> str:
    cleaned = "".join(c for c in str(phone or "") if c.isdigit() or c == "+")
    if cleaned.startswith("+"):
        return cleaned
    if len(cleaned) == 10:
        return f"+91{cleaned}"
    return cleaned


def _gateway_for_row(row):
    gateway_id = row.get("gateway_id")
    if not gateway_id:
        raise GatewayConfigurationError("No SMS gateway was assigned to this queued message")
    with connect() as c:
        gateway = c.execute("SELECT * FROM sms_gateways WHERE id=%s", (gateway_id,)).fetchone()
    if not gateway:
        raise GatewayConfigurationError(f"Assigned SMS gateway {gateway_id} no longer exists")
    if not gateway["active"]:
        raise GatewayConfigurationError("Assigned SMS gateway is inactive")
    return gateway


def _validate_gateway_owner(row, gateway):
    if row.get("hod_username") and gateway.get("hod_username") != row["hod_username"]:
        raise GatewayConfigurationError("SMS gateway ownership does not match the queued HOD scope")
    from sms_app.services.sms_access import validate_delegated_queue_row
    with connect() as c:
        reason = validate_delegated_queue_row(c, row, gateway)
    if reason:
        raise GatewayConfigurationError(reason)
    owner = str(gateway.get("owner_username") or "").strip().lower()
    hod = str(gateway.get("hod_username") or "").strip().lower()
    if owner and owner != hod:
        with connect() as c:
            reason = validate_delegated_queue_row(c, row, gateway)
        if reason:
            raise GatewayConfigurationError(reason)


def send_single_sms(phone, message, gateway=None, *, message_id=None):
    """Send one manually requested SMS through one explicitly selected gateway."""
    phone = _normalize_phone(phone)
    if not phone:
        raise GatewayConfigurationError("Invalid recipient phone number")
    if not gateway:
        raise GatewayConfigurationError("An explicit SMS gateway is required for a test SMS")
    if not gateway.get("active"):
        raise GatewayConfigurationError("Selected SMS gateway is inactive")

    mode = (gateway.get("gateway_mode") or "").strip().lower()
    # Decrypt gateway secrets only at the transport boundary. API responses,
    # queue records, logs, and UI state never receive the plaintext values.
    runtime_password = decrypt_secret(gateway.get("password")) if gateway.get("password") else None
    runtime_device_id = decrypt_secret(gateway.get("device_id")) if gateway.get("device_id") else None
    runtime_gateway = dict(gateway)
    runtime_gateway["password"] = runtime_password
    runtime_gateway["device_id"] = runtime_device_id
    if mode == "cloud":
        return send_cloud_sms(
            runtime_gateway.get("username"), runtime_gateway.get("password"), runtime_gateway.get("device_id"),
            phone, message,
            sim_number=gateway.get("sim_number"),
            message_id=message_id,
        )
    if mode == "local":
        return send_android_sms(
            runtime_gateway.get("local_url"), runtime_gateway.get("username") or "", runtime_gateway.get("password") or "",
            phone, message,
        )
    if mode == "modem":
        port = gateway.get("modem_port")
        baud = gateway.get("modem_baud") or "115200"
        if not port:
            raise GatewayConfigurationError("Modem port is not configured")
        if str(port).startswith("/dev/") and os.name == "nt":
            port = "COM3"
        return send_sms(port, baud, phone, message)
    raise GatewayConfigurationError(f"Unsupported SMS gateway mode: {mode or 'empty'}")


def process_pending_sms_now(hod_username=None):
    """Process approved absentee rows with per-row gateway routing."""
    if not sms_enabled():
        return 0, 0
    sent_count, failed_count = 0, 0
    rows = pending_sms(limit=25, hod_username=hod_username)
    for row in rows:
        try:
            gateway = _gateway_for_row(row)
            _validate_gateway_owner(row, gateway)
            provider_id = send_single_sms(
                row["parent_phone"],
                row["message"],
                gateway,
                message_id=f"nextgen-sms-{row['id']}",
            )
            mark_sent(row["id"], provider_message_id=str(provider_id) if provider_id and provider_id is not True else None)
            sent_count += 1
        except GatewayConfigurationError as exc:
            mark_failed(row["id"], str(exc), retryable=False)
            failed_count += 1
        except CloudGatewayError as exc:
            mark_failed(row["id"], str(exc), retryable=exc.retryable)
            failed_count += 1
        except (AndroidGatewayError, ModemError) as exc:
            mark_failed(row["id"], str(exc), retryable=True)
            failed_count += 1
        except Exception as exc:
            logger.exception("Unexpected SMS transport error for queue row %s", row["id"])
            mark_failed(row["id"], str(exc), retryable=True)
            failed_count += 1
    return sent_count, failed_count


async def run_forever():
    while True:
        try:
            await _poll_once()
        except Exception:
            logger.exception("sms_worker: unexpected error in poll cycle")
        await asyncio.sleep(POLL_SECONDS)


async def _poll_once():
    if not sms_enabled():
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, process_pending_sms_now)
