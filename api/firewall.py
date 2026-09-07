"""API security firewall middleware.

Rate limits are backed by the same MySQL database used by the application so
they remain effective across restarts and multiple worker processes.
"""

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from database import connect

AUTH_LIMIT_PER_MINUTE = 15
GENERAL_LIMIT_PER_MINUTE = 120
FIREWALL_WINDOW_SECONDS = 60


def _bucket(now: float, window: int) -> int:
    return int(now // window)


def _allow(key: str, limit: int, window_seconds: int = FIREWALL_WINDOW_SECONDS) -> bool:
    """Atomically consume one request from a DB-backed bucket."""
    bucket = _bucket(time.time(), window_seconds)
    with connect() as c:
        c.execute(
            """INSERT INTO rate_limit_buckets(bucket_key,window_seconds,bucket_no,request_count)
               VALUES(%s,%s,%s,1)
               ON DUPLICATE KEY UPDATE request_count=request_count+1""",
            (key, window_seconds, bucket),
        )
        row = c.execute(
            "SELECT request_count FROM rate_limit_buckets WHERE bucket_key=%s AND window_seconds=%s AND bucket_no=%s",
            (key, window_seconds, bucket),
        ).fetchone()
    return bool(row and int(row["request_count"]) <= limit)


def _apply_security_headers(response: Response, path: str) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class SecurityFirewallMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "127.0.0.1"
        path = request.url.path.lower()
        auth_path = (
            path.startswith("/api/auth/login")
            or path.startswith("/api/auth/send-otp")
            or path.startswith("/api/auth/register")
            or path.startswith("/api/auth/reset-password")
        )

        limit = AUTH_LIMIT_PER_MINUTE if auth_path else GENERAL_LIMIT_PER_MINUTE
        key = f"firewall:{'auth' if auth_path else 'general'}:{client_ip}"
        if not _allow(key, limit):
            message = (
                "Too many authentication requests. Rate limit exceeded. Please try again in 1 minute."
                if auth_path
                else "Too many requests. Rate limit exceeded. Please wait a moment."
            )
            return _apply_security_headers(
                JSONResponse(
                    status_code=429,
                    content={"error": {"message": message, "code": "RATE_LIMIT_EXCEEDED"}},
                ),
                path,
            )

        response: Response = await call_next(request)
        return _apply_security_headers(response, path)
