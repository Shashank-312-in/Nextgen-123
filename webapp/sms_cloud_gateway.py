"""SMSGate public Cloud Server transport.

The Android phone remains the actual SMS sender. This module only submits a
message to SMSGate's cloud API, explicitly targeting the configured deviceId.
No paid SMS provider is used.

API reference verified against SMSGate documentation on 2026-08-18:
POST https://api.sms-gate.app/3rdparty/v1/messages
Basic authentication is supported and deviceId explicitly targets one device.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://api.sms-gate.app/3rdparty/v1"


class CloudGatewayError(Exception):
    """Transport error with a retryability classification."""

    def __init__(self, message: str, *, retryable: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


def _basic_headers(username: str, password: str) -> dict[str, str]:
    credentials = f"{username}:{password}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "NextGen-SMS/2.0",
    }


def _request(url: str, *, username: str, password: str, method: str = "GET", payload: dict | None = None, timeout: int = 15):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_basic_headers(username, password), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}
            return resp.getcode(), data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw}
        raise CloudGatewayError(
            f"SMSGate Cloud HTTP {exc.code}: {str(data)[:300]}",
            retryable=exc.code in (408, 425, 429, 500, 502, 503, 504),
            status_code=exc.code,
        )
    except urllib.error.URLError as exc:
        raise CloudGatewayError(f"Cannot reach SMSGate Cloud: {exc.reason}", retryable=True)
    except TimeoutError as exc:
        raise CloudGatewayError(f"SMSGate Cloud request timed out: {exc}", retryable=True)
    except Exception as exc:
        raise CloudGatewayError(f"SMSGate Cloud request failed: {exc}", retryable=True)


def send_cloud_sms(
    username: str,
    password: str,
    device_id: str,
    phone: str,
    message: str,
    *,
    sim_number: int | None = None,
    message_id: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 15,
):
    """Queue one SMS on the explicitly selected SMSGate Cloud device.

    ``message_id`` is stable per NextGen queue row, so a retry after an
    uncertain network failure can reuse the same provider id rather than
    creating an unrelated second message.
    """
    username = str(username or "").strip()
    password = str(password or "")
    device_id = str(device_id or "").strip()
    phone = str(phone or "").strip()
    message = str(message or "")
    if not username or not password:
        raise CloudGatewayError("Cloud gateway username/password are required", retryable=False)
    if not device_id:
        raise CloudGatewayError("Cloud gateway device ID is required", retryable=False)
    if not phone:
        raise CloudGatewayError("Recipient phone number is required", retryable=False)
    if not message:
        raise CloudGatewayError("SMS message is empty", retryable=False)

    payload = {
        "textMessage": {"text": message},
        "deviceId": device_id,
        "phoneNumbers": [phone],
        "ttl": 3600,
        "withDeliveryReport": True,
    }
    if sim_number is not None:
        payload["simNumber"] = int(sim_number)
    if message_id:
        payload["id"] = message_id

    url = base_url.rstrip("/") + "/messages"
    try:
        status, data = _request(url, username=username, password=password, method="POST", payload=payload, timeout=timeout)
    except CloudGatewayError as exc:
        # If the provider says the stable message id already exists, verify it
        # before treating the request as successful. This protects against a
        # timeout after SMSGate accepted the message.
        if exc.status_code in (400, 409, 422) and message_id:
            try:
                get_status, existing = _request(
                    f"{url}/{urllib.parse.quote(message_id, safe='')}",
                    username=username,
                    password=password,
                    method="GET",
                    timeout=timeout,
                )
                if get_status == 200:
                    return existing.get("id") or message_id
            except CloudGatewayError:
                pass
        raise

    if status not in (200, 201, 202):
        raise CloudGatewayError(f"Unexpected SMSGate Cloud status {status}", retryable=status >= 500, status_code=status)
    provider_id = data.get("id") if isinstance(data, dict) else None
    return provider_id or message_id or True


def test_cloud_gateway(username: str, password: str, device_id: str, *, base_url: str = DEFAULT_BASE_URL, timeout: int = 10) -> dict:
    """Verify credentials and that the configured device exists in the account."""
    username = str(username or "").strip()
    password = str(password or "")
    device_id = str(device_id or "").strip()
    if not username or not password or not device_id:
        raise CloudGatewayError("Username, password and device ID are required", retryable=False)
    status, devices = _request(
        base_url.rstrip("/") + "/devices",
        username=username,
        password=password,
        method="GET",
        timeout=timeout,
    )
    if status != 200 or not isinstance(devices, list):
        raise CloudGatewayError("SMSGate Cloud returned an invalid device list", retryable=False, status_code=status)
    match = next((d for d in devices if str(d.get("id")) == device_id), None)
    if not match:
        raise CloudGatewayError("Configured device ID was not found in this SMSGate account", retryable=False, status_code=404)
    return match
