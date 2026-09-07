"""Database-backed login credential rate limiter.

The bucket is stored in MySQL so the limit survives process restarts and is
shared by all API workers. Keys are constructed by callers as IP+identifier.
"""

import time

from database import connect

WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS = 5


def _bucket(now: float, window: int) -> int:
    return int(now // window)


# — is_locked
# WHY this is a cheap pre-check, not the authoritative lock decision: it lets
# an already-locked-out request short-circuit before paying auth()'s
# deliberately-slow PBKDF2 hashing cost (DoS-amplification concern). The
# authoritative "did THIS request cross the threshold" signal comes from
# record_failure()'s return value below, since that read is inside the same
# atomic increment — a prior separate SELECT here can be stale under
# concurrent requests (see record_failure docstring for the actual race).
def is_locked(key: str) -> bool:
    bucket = _bucket(time.time(), WINDOW_SECONDS)
    with connect() as c:
        row = c.execute(
            "SELECT request_count FROM rate_limit_buckets WHERE bucket_key=%s AND window_seconds=%s AND bucket_no=%s",
            (key, WINDOW_SECONDS, bucket),
        ).fetchone()
    return bool(row and int(row["request_count"]) > MAX_ATTEMPTS)


# — record_failure
# WHY this returns bool instead of None: the real race isn't in the upsert's
# atomicity (INSERT..ON DUPLICATE KEY UPDATE is already atomic per-row) — it's
# that a caller doing is_locked() THEN record_failure() as two separate steps
# lets N concurrent bad-login requests all read a stale pre-increment count,
# all see is_locked()==False, and all proceed past the boundary before any of
# their increments land. Folding the lock decision into the SAME transaction
# as the increment (upsert, then SELECT back the post-increment count, both
# inside one `with connect()` block) means the decision is made from a value
# no other concurrent request could also have observed pre-increment. This is
# safe because database.connect() gives each thread its own dedicated
# connection/transaction (threading.local pool, autocommit=False) — FastAPI's
# sync route handlers run in a threadpool, so concurrent requests really are
# concurrent transactions here, and InnoDB serializes the row-level write
# between them. Whichever transaction's increment reaches MAX_ATTEMPTS first
# is the one that observes it in its own post-increment SELECT.
def record_failure(key: str) -> bool:
    """Atomically increments the failure count and returns whether THIS call
    just crossed (or is at/above) the lockout threshold. Callers should use
    this return value — not a prior is_locked() read — to decide whether to
    react to a lockout on the failure path itself."""
    bucket = _bucket(time.time(), WINDOW_SECONDS)
    with connect() as c:
        c.execute(
            """INSERT INTO rate_limit_buckets(bucket_key,window_seconds,bucket_no,request_count)
               VALUES(%s,%s,%s,1)
               ON DUPLICATE KEY UPDATE request_count=request_count+1""",
            (key, WINDOW_SECONDS, bucket),
        )
        row = c.execute(
            "SELECT request_count FROM rate_limit_buckets WHERE bucket_key=%s AND window_seconds=%s AND bucket_no=%s",
            (key, WINDOW_SECONDS, bucket),
        ).fetchone()
    return bool(row and int(row["request_count"]) > MAX_ATTEMPTS)


def record_success(key: str) -> None:
    with connect() as c:
        c.execute(
            "DELETE FROM rate_limit_buckets WHERE bucket_key=%s AND window_seconds=%s",
            (key, WINDOW_SECONDS),
        )
