import hashlib
import hmac
import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    import mysql.connector
    from mysql.connector import Error as DatabaseError, IntegrityError, OperationalError
    MYSQL_DRIVER = "mysql.connector"
except ImportError:
    try:
        import pymysql
        import pymysql.cursors
        from pymysql import Error as DatabaseError, IntegrityError, OperationalError
        MYSQL_DRIVER = "pymysql"
    except ImportError:
        MYSQL_DRIVER = None
        class DatabaseError(Exception): pass
        class IntegrityError(Exception): pass
        class OperationalError(Exception): pass


MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 3306))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "student_management")


ROLES = ("ADMIN", "HOD", "FACULTY", "STUDENT")
DEPARTMENTS = ("CSD",)
SUBJECTS = ("Data Structures", "Database Systems", "Operating Systems", "Computer Networks", "Software Engineering", "Web Technologies")
ATTENDANCE_STATUSES = ("Present", "Absent", "Late", "Excused")
from field_encryption import encrypt_field, looks_encrypted
from seed_data import CSD_STUDENTS


class DictRow(dict):
    def __init__(self, dictionary, keys=None):
        if dictionary:
            super().__init__(dictionary)
            self._keys = list(keys) if keys is not None else list(dictionary.keys())
        else:
            super().__init__()
            self._keys = []

    def __getitem__(self, item):
        if isinstance(item, int):
            if 0 <= item < len(self._keys):
                return super().__getitem__(self._keys[item])
            raise IndexError("tuple index out of range")
        return super().__getitem__(item)


class CursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        if MYSQL_DRIVER and isinstance(sql, str):
            sql = sql.replace("?", "%s")
        if params is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, params)
        return self

    def executemany(self, sql, seq_of_params):
        if MYSQL_DRIVER and isinstance(sql, str):
            sql = sql.replace("?", "%s")
        self._cursor.executemany(sql, seq_of_params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        keys = [d[0] for d in self._cursor.description] if getattr(self._cursor, "description", None) else None
        if isinstance(row, dict):
            return DictRow(row, keys=keys)
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        keys = [d[0] for d in self._cursor.description] if getattr(self._cursor, "description", None) else None
        if isinstance(rows[0], dict):
            return [DictRow(r, keys=keys) for r in rows]
        return rows

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def __iter__(self):
        rows = self.fetchall()
        for row in rows:
            yield row


class ConnectionWrapper:
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        if MYSQL_DRIVER == "mysql.connector":
            cur = self._conn.cursor(dictionary=True, buffered=True)
        elif MYSQL_DRIVER == "pymysql":
            cur = self._conn.cursor(pymysql.cursors.DictCursor)
        else:
            raise RuntimeError("No MySQL driver found. Please install mysql-connector-python or PyMySQL")
        return CursorWrapper(cur)


    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql, seq_of_params):
        cur = self.cursor()
        cur.executemany(sql, seq_of_params)
        return cur

    def executescript(self, script):
        cur = self.cursor()
        for statement in script.split(";"):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)
        return cur

    def commit(self):
        try:
            self._conn.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()



# ──────────────────────────────────────────────────────────────────────────────
# — HTTPProxy: drop-in DB client that ships execute() calls to db_proxy over
# HTTPS instead of talking to MySQL on a local socket. Activates only when
# DB_PROXY_URL is set (Render deployment, campus MySQL not directly reachable).
# When DB_PROXY_URL is absent, none of this code runs — direct-connect path
# below is untouched. See db_proxy/main.py for the server side of this.
# ──────────────────────────────────────────────────────────────────────────────
DB_PROXY_URL = os.environ.get("DB_PROXY_URL", "").rstrip("/")
DB_PROXY_KEY = os.environ.get("DB_PROXY_KEY", "")
DB_PROXY_TIMEOUT = float(os.environ.get("DB_PROXY_TIMEOUT", "15"))

if DB_PROXY_URL:
    import requests


class HTTPCursorWrapper:
    """Same interface as CursorWrapper, but backed by one /execute call
    against an already-open proxy session rather than a local cursor."""

    def __init__(self, conn: "HTTPConnectionWrapper", sql, params):
        result = conn._post(f"/v1/session/{conn._session_id}/execute", {"sql": sql, "params": params})
        self._rows = result["rows"]
        self._lastrowid = result["lastrowid"]
        self._rowcount = result["rowcount"]
        self._pos = 0

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return DictRow(row)

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return [DictRow(r) for r in rows]

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._rowcount

    def __iter__(self):
        for row in self.fetchall():
            yield row


class HTTPConnectionWrapper:
    """Drop-in replacement for ConnectionWrapper. Opens a proxy session on
    first use, runs statements through it, commits/rolls back on __exit__ —
    mirrors the "with connect() as c:" contract every route already uses.

    Error contract: any transport failure, auth failure, or SQL error from
    the proxy is re-raised as OperationalError/DatabaseError so existing
    `except` blocks in routes_*.py keep working unmodified.
    """

    def __init__(self):
        self._session_id = None

    def _headers(self):
        return {"X-Proxy-Key": DB_PROXY_KEY, "Content-Type": "application/json"}

    def _post(self, path, json_body=None):
        try:
            resp = requests.post(f"{DB_PROXY_URL}{path}", json=json_body, headers=self._headers(), timeout=DB_PROXY_TIMEOUT)
        except requests.RequestException as e:
            raise OperationalError(f"db_proxy unreachable: {e}") from e

        if resp.status_code == 401:
            raise OperationalError("db_proxy rejected X-Proxy-Key (check DB_PROXY_KEY)")
        if resp.status_code == 404:
            raise OperationalError(f"db_proxy: session expired or unknown ({resp.text})")
        if resp.status_code == 400:
            detail = resp.json().get("detail", {})
            raise DatabaseError(detail.get("message", resp.text))
        if resp.status_code >= 400:
            raise OperationalError(f"db_proxy error {resp.status_code}: {resp.text}")
        return resp.json()

    def _ensure_session(self):
        if self._session_id is None:
            result = self._post("/v1/session/begin")
            self._session_id = result["session_id"]

    def cursor(self):
        raise RuntimeError("HTTPConnectionWrapper has no standalone cursor() — use execute() directly")

    def execute(self, sql, params=None):
        self._ensure_session()
        if params is not None and not isinstance(params, (list, tuple)):
            params = [params]
        return HTTPCursorWrapper(self, sql, list(params) if params is not None else None)

    def executemany(self, sql, seq_of_params):
        self._ensure_session()
        last = None
        for params in seq_of_params:
            last = self.execute(sql, params)
        return last

    def executescript(self, script):
        self._ensure_session()
        last = None
        for statement in script.split(";"):
            stmt = statement.strip()
            if stmt:
                last = self.execute(stmt)
        return last

    def commit(self):
        if self._session_id is not None:
            self._post(f"/v1/session/{self._session_id}/commit")
            self._session_id = None

    def rollback(self):
        if self._session_id is not None:
            try:
                self._post(f"/v1/session/{self._session_id}/rollback")
            except Exception:
                pass
            self._session_id = None

    def close(self):
        # No persistent socket to close on this side — session lifecycle
        # is fully owned by commit()/rollback(). Nothing to do here.
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()


def ensure_database_exists():
    """Auto-creates the MySQL database if it doesn't exist yet."""
    try:
        if MYSQL_DRIVER == "mysql.connector":
            raw_conn = mysql.connector.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                autocommit=True
            )
        elif MYSQL_DRIVER == "pymysql":
            raw_conn = pymysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                autocommit=True
            )
        else:
            return
        cur = raw_conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
        cur.close()
        raw_conn.close()
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Connection pool (thread-local reuse)
# Creates ONE connection per thread and reuses it. On a broken connection
# (OperationalError / ping fail) it reconnects transparently. This eliminates
# the ~10-30 ms TCP + auth handshake overhead on every request.
# ──────────────────────────────────────────────────────────────────────────────
import threading

_thread_local = threading.local()
_db_exists_checked = False
_db_lock = threading.Lock()


def _ensure_db_once():
    global _db_exists_checked
    if not _db_exists_checked:
        with _db_lock:
            if not _db_exists_checked:
                ensure_database_exists()
                _db_exists_checked = True


import json

# Secondary recovery aid only. MySQL persistence is the source of truth;
# this file must never be treated as a replacement for a persistent DB.
CUSTOM_USERS_FILE = Path(__file__).parent / "custom_users.json"


def _save_custom_user_backup(username: str, password_hash: str, role: str, full_name: str = "", student_roll_no: str | None = None):
    users = []
    if CUSTOM_USERS_FILE.exists():
        try:
            with open(CUSTOM_USERS_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
        except Exception:
            users = []
    users = [u for u in users if u.get("username") != username]
    users.append({
        "username": username,
        "password": password_hash,
        "role": role,
        "full_name": full_name,
        "student_roll_no": student_roll_no,
    })
    try:
        with open(CUSTOM_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    except Exception:
        pass


def _restore_custom_users(c):
    if not CUSTOM_USERS_FILE.exists():
        return
    try:
        with open(CUSTOM_USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        for u in users:
            if not c.execute("SELECT 1 FROM users WHERE username=%s", (u["username"],)).fetchone():
                student_roll = u.get("student_roll_no")
                if student_roll and not c.execute("SELECT 1 FROM students WHERE roll_no=%s", (student_roll,)).fetchone():
                    continue
                c.execute(
                    "INSERT INTO users(username,password,role,student_roll_no,full_name) VALUES(%s,%s,%s,%s,%s)",
                    (u["username"], u["password"], u["role"], student_roll, u.get("full_name", "")),
                )
    except Exception as e:
        print(f"[DATABASE RECOVERY] Warning restoring custom users: {e}")


def _new_raw_connection(target_db: str):
    """Open a fresh MySQL connection. MySQL is the only supported application database."""
    if MYSQL_DRIVER == "mysql.connector":
        return mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=target_db,
            autocommit=False,
            connection_timeout=10,
            use_pure=False,
        )
    if MYSQL_DRIVER == "pymysql":
        return pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=target_db,
            autocommit=False,
            charset="utf8mb4",
            connect_timeout=10,
        )
    raise RuntimeError("No MySQL driver found. Please install mysql-connector-python or PyMySQL")



def connect(db_name=None):
    """Return a ConnectionWrapper backed by a thread-local pooled connection.

    The raw connection is kept alive across calls in the same thread and
    re-established transparently when the server has closed it (wait_timeout).
    Using a context manager (with connect() as c:) still works — __exit__
    commits/rolls back but no longer closes the underlying socket.
    """
    if DB_PROXY_URL:
        # Campus MySQL not directly reachable (e.g. Render) — route through
        # db_proxy over HTTPS instead. db_name override is intentionally
        # NOT supported here: the proxy is hardcoded to its own
        # MYSQL_DATABASE, so a compromised backend can't make it connect
        # to an arbitrary database on the campus server.
        return HTTPConnectionWrapper()

    _ensure_db_once()
    target_db = db_name if db_name is not None else MYSQL_DATABASE

    attr = f"_conn_{target_db}"
    raw = getattr(_thread_local, attr, None)

    # Ping to check liveness; reconnect silently if dead
    if raw is not None:
        try:
            if MYSQL_DRIVER == "mysql.connector":
                raw.ping(reconnect=False, attempts=1, delay=0)
            elif MYSQL_DRIVER == "pymysql":
                raw.ping(reconnect=False)
        except Exception:
            try:
                raw.close()
            except Exception:
                pass
            raw = None

    if raw is None:
        raw = _new_raw_connection(target_db)
        setattr(_thread_local, attr, raw)

    return PooledConnectionWrapper(raw)


class PooledConnectionWrapper(ConnectionWrapper):
    """Like ConnectionWrapper but does NOT close the underlying socket on exit.
    The connection stays alive in the thread-local pool for the next request.
    """

    def close(self):
        # Don't close — return connection to pool (keep socket alive)
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            try:
                self.commit()
            except Exception:
                self.rollback()
        # intentionally NOT calling close() here — socket stays open




def _hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def _verify_password(password, stored):
    if not stored or not stored.startswith("pbkdf2_sha256$"):
        return hmac.compare_digest(password, stored or "")
    _, rounds, salt, digest = stored.split("$", 3)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
    return hmac.compare_digest(actual, digest)


def validate_student(data):
    for key in ("roll_no", "name", "department"):
        if not str(data.get(key, "")).strip():
            raise ValueError(f"{key.replace('_', ' ').title()} is required")
    if data["department"] not in DEPARTMENTS:
        raise ValueError("This system is restricted to CSD students")
    email = str(data.get("email", "")).strip()
    if email and not re.fullmatch(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValueError("Enter a valid email address (e.g. student@gmail.com)")
    phone = re.sub(r"[\s+()-]", "", str(data.get("phone", "")))
    if phone and (not phone.isdigit() or len(phone) != 10):
        raise ValueError("Phone number must be a valid 10-digit mobile number (e.g. 9876543210)")
    parent_phone = re.sub(r"[\s+()-]", "", str(data.get("parent_phone", "")))
    if parent_phone and (not parent_phone.isdigit() or len(parent_phone) != 10):
        raise ValueError("Parent phone number must be a valid 10-digit mobile number (e.g. 9876543210)")
    aadhaar = re.sub(r"\s", "", str(data.get("aadhaar_number", "")))
    if aadhaar and (not aadhaar.isdigit() or len(aadhaar) != 12):
        raise ValueError("Aadhaar Number must be exactly 12 digits")
    for label, key in (("10th", "tenth_marks"), ("12th", "twelfth_marks"), ("Diploma", "diploma_marks")):
        val = str(data.get(key, "")).strip()
        if val:
            try:
                num = float(val)
            except ValueError:
                raise ValueError(f"{label} Marks must be a number")
            if not 0 <= num <= 100:
                raise ValueError(f"{label} Marks must be between 0 and 100")


def mask_aadhaar(value):
    digits = re.sub(r"\s", "", str(value or ""))
    if len(digits) != 12:
        return "—" if not digits else "XXXX XXXX XXXX"
    return f"XXXX XXXX {digits[-4:]}"


def validate_staff_profile(data):
    full_name = str(data.get("full_name", "")).strip()
    if not full_name:
        raise ValueError("Full Name is required")
    email = str(data.get("email", "")).strip()
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Enter a valid email address")
    phone = re.sub(r"[\s+()-]", "", str(data.get("phone", "")))
    if phone and (not phone.isdigit() or not 7 <= len(phone) <= 15):
        raise ValueError("Phone must contain 7 to 15 digits")


def audit(conn, username, action, entity, details="", actor_role=None):
    actor = username or "system"
    if actor_role is None and actor != "system":
        try:
            row = conn.execute("SELECT role FROM users WHERE username=%s", (actor,)).fetchone()
            actor_role = row["role"] if row else None
        except Exception:
            actor_role = None
    conn.execute(
        "INSERT INTO audit_logs(username,actor_role,action,entity,details) VALUES(%s,%s,%s,%s,%s)",
        (actor, actor_role, action, entity, details),
    )


def resolve_hod_for_department(c, dept="CSD") -> str | None:
    """Find the responsible active HOD for the given department.
    If multiple active HODs exist, prefer a departmental HOD.
    If no departmental HOD is found, fallback to any active HOD, or None.
    """
    dept = (dept or "CSD").strip()
    hods = c.execute(
        "SELECT username FROM users WHERE role='HOD' AND active=1 AND department=%s ORDER BY id ASC",
        (dept,)
    ).fetchall()
    if hods:
        return hods[0]["username"]
    fallback = c.execute(
        "SELECT username FROM users WHERE role='HOD' AND active=1 ORDER BY id ASC"
    ).fetchall()
    if fallback:
        return fallback[0]["username"]
    return None


def get_setting(key, default=None):
    with connect() as c:
        row = c.execute("SELECT `value` FROM settings WHERE `key`=%s", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value, actor="system"):
    with connect() as c:
        c.execute("INSERT INTO settings(`key`,`value`) VALUES(%s,%s) ON DUPLICATE KEY UPDATE `value`=%s", (key, str(value), str(value)))
        audit(c, actor, "UPDATE", "settings", f"{key}={value}")


STUDENT_SELF_EDIT_SETTING_KEY = "student_self_edit_enabled"


def is_student_self_edit_enabled() -> bool:
    val = get_setting(STUDENT_SELF_EDIT_SETTING_KEY, "0")
    return str(val).strip().lower() in ("1", "true", "yes")


def set_student_self_edit_enabled(enabled: bool | str | int, actor: str = "system") -> bool:
    is_on = str(enabled).strip().lower() in ("1", "true", "yes") if not isinstance(enabled, bool) else enabled
    val = "1" if is_on else "0"
    set_setting(STUDENT_SELF_EDIT_SETTING_KEY, val, actor=actor)
    return is_on


def _seed_checklist(c, roll):
    for item, status in [("Personal details","Complete"),("Documents","Pending"),("ID card","Pending"),("Fees","Pending"),("Attendance records","Available"),("Marks records","Available")]:
        c.execute("INSERT IGNORE INTO checklist(roll_no,item,status) VALUES(%s,%s,%s)", (roll,item,status))


def _ensure_bootstrap_account(c):
    """Fail closed until a real privileged account exists.

    No account or password is ever synthesized from a source-controlled
    default. First-run provisioning requires explicit operator-supplied
    environment variables.
    """
    row = c.execute(
        "SELECT COUNT(*) AS count FROM users WHERE active=1 AND role IN ('HOD','ADMIN')"
    ).fetchone()
    privileged_count = int(row["count"] if row and row.get("count") is not None else 0)
    if privileged_count:
        return None

    username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "No active HOD/ADMIN account exists. Set BOOTSTRAP_ADMIN_USERNAME "
            "and BOOTSTRAP_ADMIN_PASSWORD for the first startup."
        )
    if len(username) < 3:
        raise RuntimeError("BOOTSTRAP_ADMIN_USERNAME must be at least 3 characters.")
    if len(password) < 8:
        raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD must be at least 8 characters.")
    if c.execute("SELECT 1 FROM users WHERE username=%s", (username,)).fetchone():
        raise RuntimeError("Bootstrap username already exists; refuse to overwrite an existing account.")

    c.execute(
        "INSERT INTO users(username,password,role,full_name,department,hod_username,active,must_change_password,auth_version) "
        "VALUES(%s,%s,'HOD',%s,'CSD',%s,1,0,0)",
        (username, _hash_password(password), "Head of Department", username),
    )
    return username


def init_db(db_name=None):
    with connect(db_name) as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS students(
            id INT AUTO_INCREMENT PRIMARY KEY,
            roll_no VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            department VARCHAR(64) NOT NULL DEFAULT 'CSD' CHECK(department='CSD'),
            hod_username VARCHAR(64),
            email VARCHAR(255) UNIQUE,
            phone VARCHAR(32),
            parent_phone VARCHAR(32),
            dob VARCHAR(32),
            address TEXT,
            father_name VARCHAR(255),
            category VARCHAR(64),
            gender VARCHAR(32),
            seat_category VARCHAR(64),
            certificates_submitted TEXT,
            certificates_due TEXT,
            consultant_name VARCHAR(255),
            photo_path VARCHAR(512),
            active TINYINT(1) NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            aadhaar_number TEXT,
            apaar_id TEXT,
            tenth_school VARCHAR(255),
            tenth_year VARCHAR(32),
            tenth_certificate_path VARCHAR(512),
            twelfth_school VARCHAR(255),
            twelfth_year VARCHAR(32),
            twelfth_certificate_path VARCHAR(512),
            diploma_college VARCHAR(255),
            diploma_year VARCHAR(32),
            diploma_certificate_path VARCHAR(512),
            tenth_marks VARCHAR(32),
            twelfth_marks VARCHAR(32),
            diploma_marks VARCHAR(32),
            current_semester_id INT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(32) NOT NULL CHECK(role IN ('ADMIN','HOD','FACULTY','STUDENT')),
            student_roll_no VARCHAR(64) UNIQUE,
            full_name VARCHAR(255) NOT NULL DEFAULT '',
            photo_path VARCHAR(512),
            department VARCHAR(64),
            hod_username VARCHAR(64),
            designation VARCHAR(128),
            employee_id VARCHAR(64),
            email VARCHAR(255),
            email_verified TINYINT(1) NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1)),
            phone VARCHAR(32),
            qualification VARCHAR(255),
            date_of_joining VARCHAR(32),
            active TINYINT(1) NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            must_change_password TINYINT(1) NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1)),
            auth_version INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_roll_no) REFERENCES students(roll_no) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Migration for DB files created before email/email_verified existed
        # on `users` -- CREATE TABLE IF NOT EXISTS only affects brand-new
        # tables, so an already-existing MySQL database needs these columns
        # added explicitly. Additive, no data loss, safe to run every startup.
        existing_user_cols = {row["Field"] if "Field" in row else row["name"] for row in c.execute("SHOW COLUMNS FROM users").fetchall()}

        if "email" not in existing_user_cols:
            c.execute("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
        if "email_verified" not in existing_user_cols:
            c.execute("ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1))")
        if "hod_username" not in existing_user_cols:
            c.execute("ALTER TABLE users ADD COLUMN hod_username VARCHAR(64) NULL")
        if "auth_version" not in existing_user_cols:
            c.execute("ALTER TABLE users ADD COLUMN auth_version INT NOT NULL DEFAULT 0")

        c.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit_buckets(
            bucket_key VARCHAR(255) NOT NULL,
            window_seconds INT NOT NULL,
            bucket_no BIGINT NOT NULL,
            request_count INT NOT NULL DEFAULT 0,
            PRIMARY KEY(bucket_key, window_seconds, bucket_no)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Additive migrations for HOD-scoped SMS routing. These are intentionally
        # idempotent because init_db() runs on application startup.
        existing_student_cols = {row["Field"] if "Field" in row else row["name"] for row in c.execute("SHOW COLUMNS FROM students").fetchall()}
        if "hod_username" not in existing_student_cols:
            c.execute("ALTER TABLE students ADD COLUMN hod_username VARCHAR(64) NULL")

        c.execute("""
        CREATE TABLE IF NOT EXISTS attendance(
            id INT AUTO_INCREMENT PRIMARY KEY,
            roll_no VARCHAR(64) NOT NULL,
            date VARCHAR(32) NOT NULL,
            department VARCHAR(64) NOT NULL DEFAULT 'CSD',
            status VARCHAR(32) NOT NULL CHECK(status IN ('Present','Absent','Late','Excused')),
            marked_by VARCHAR(64),
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE(roll_no,date),
            FOREIGN KEY(roll_no) REFERENCES students(roll_no) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS marks(
            id INT AUTO_INCREMENT PRIMARY KEY,
            roll_no VARCHAR(64) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            internal DOUBLE NOT NULL DEFAULT 0 CHECK(internal BETWEEN 0 AND 100),
            external DOUBLE NOT NULL DEFAULT 0 CHECK(external BETWEEN 0 AND 100),
            entered_by VARCHAR(64),
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE(roll_no,subject),
            FOREIGN KEY(roll_no) REFERENCES students(roll_no) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS checklist(
            id INT AUTO_INCREMENT PRIMARY KEY,
            roll_no VARCHAR(64) NOT NULL,
            item VARCHAR(255) NOT NULL,
            status VARCHAR(64) NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Complete','Available','Not Applicable')),
            UNIQUE(roll_no,item),
            FOREIGN KEY(roll_no) REFERENCES students(roll_no) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            `key` VARCHAR(191) PRIMARY KEY,
            `value` TEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs(
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) NOT NULL,
            actor_role VARCHAR(32) NULL,
            action VARCHAR(64) NOT NULL,
            entity VARCHAR(64) NOT NULL,
            details TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_audit_created (created_at),
            INDEX idx_audit_actor_role_created (actor_role, created_at),
            INDEX idx_audit_username_created (username, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        existing_audit_cols = {row["Field"] if "Field" in row else row["name"] for row in c.execute("SHOW COLUMNS FROM audit_logs").fetchall()}
        if "actor_role" not in existing_audit_cols:
            c.execute("ALTER TABLE audit_logs ADD COLUMN actor_role VARCHAR(32) NULL AFTER username")
            c.execute("UPDATE audit_logs a JOIN users u ON LOWER(u.username)=LOWER(a.username) SET a.actor_role=u.role WHERE a.actor_role IS NULL")

        c.execute("""
        CREATE TABLE IF NOT EXISTS academic_semesters(
            id INT AUTO_INCREMENT PRIMARY KEY,
            code VARCHAR(32) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            sort_order INT NOT NULL UNIQUE,
            active TINYINT(1) NOT NULL DEFAULT 1 CHECK(active IN (0,1))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS subjects(
            id INT AUTO_INCREMENT PRIMARY KEY,
            semester_id INT NOT NULL,
            code VARCHAR(64) NOT NULL,
            name VARCHAR(255) NOT NULL,
            has_lab TINYINT(1) NOT NULL DEFAULT 0 CHECK(has_lab IN (0,1)),
            active TINYINT(1) NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            UNIQUE(semester_id,code),
            FOREIGN KEY(semester_id) REFERENCES academic_semesters(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS subject_faculty(
            subject_id INT NOT NULL,
            faculty_username VARCHAR(64) NOT NULL,
            PRIMARY KEY(subject_id,faculty_username),
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY(faculty_username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS attendance_sessions(
            id INT AUTO_INCREMENT PRIMARY KEY,
            attendance_date VARCHAR(32) NOT NULL,
            semester_id INT NOT NULL,
            subject_id INT NOT NULL,
            faculty_username VARCHAR(64) NOT NULL,
            hod_username VARCHAR(64),
            session_type VARCHAR(32) NOT NULL CHECK(session_type IN ('CLASS','LAB')),
            duration_hours INT NOT NULL CHECK(duration_hours IN (1,2,3)),
            topic TEXT NOT NULL,
            created_by VARCHAR(64) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE(attendance_date,subject_id,faculty_username,session_type),
            FOREIGN KEY(semester_id) REFERENCES academic_semesters(id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(faculty_username) REFERENCES users(username) ON UPDATE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        existing_session_cols = {row["Field"] if "Field" in row else row["name"] for row in c.execute("SHOW COLUMNS FROM attendance_sessions").fetchall()}
        if "hod_username" not in existing_session_cols:
            c.execute("ALTER TABLE attendance_sessions ADD COLUMN hod_username VARCHAR(64) NULL")

        # Backfill ownership on users and students.
        active_hods = c.execute("SELECT username, department FROM users WHERE role='HOD' AND active=1 ORDER BY (username != 'admin') DESC, id ASC").fetchall()
        dept_hod_map = {}
        for h in active_hods:
            dept = (h["department"] or "").strip()
            if dept and (dept not in dept_hod_map or dept_hod_map[dept] == "admin"):
                dept_hod_map[dept] = h["username"]
        for dept, hod_username in dept_hod_map.items():
            if hod_username:
                c.execute("UPDATE users SET hod_username=%s WHERE department=%s AND role<>'HOD' AND (hod_username IS NULL OR hod_username='')", (hod_username, dept))
                c.execute("UPDATE users SET hod_username=username WHERE department=%s AND role='HOD' AND username=%s", (dept, hod_username))
                c.execute("UPDATE students SET hod_username=%s WHERE department=%s AND (hod_username IS NULL OR hod_username='')", (hod_username, dept))
                c.execute("UPDATE attendance_sessions a JOIN users u ON u.username=a.faculty_username SET a.hod_username=%s WHERE u.department=%s AND a.hod_username IS NULL", (hod_username, dept))

        c.execute("""
        CREATE TABLE IF NOT EXISTS attendance_records(
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            roll_no VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL CHECK(status IN ('Present','Absent')),
            marked_by VARCHAR(64) NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE(session_id,roll_no),
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(roll_no) REFERENCES students(roll_no) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # SMS gateway ownership is by HOD/organizational scope, never by physical
        # college block. A phone may be physically anywhere and still serve only
        # the students assigned to its HOD.
        c.execute("""
        CREATE TABLE IF NOT EXISTS sms_gateways(
            id INT AUTO_INCREMENT PRIMARY KEY,
            hod_username VARCHAR(64) NOT NULL UNIQUE,
            gateway_name VARCHAR(128) NOT NULL DEFAULT 'SMSGate Phone',
            gateway_mode VARCHAR(16) NOT NULL DEFAULT 'cloud',
            device_id VARCHAR(255),
            local_url VARCHAR(255),
            username VARCHAR(128),
            password VARCHAR(255),
            modem_port VARCHAR(128),
            modem_baud VARCHAR(32) DEFAULT '115200',
            sim_number TINYINT,
            auto_send TINYINT(1) NOT NULL DEFAULT 0 CHECK(auto_send IN (0,1)),
            active TINYINT(1) NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY(hod_username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS sms_queue(
            id INT AUTO_INCREMENT PRIMARY KEY,
            roll_no VARCHAR(64) NOT NULL,
            parent_phone VARCHAR(32) NOT NULL,
            message TEXT NOT NULL,
            attendance_session_id INT,
            send_date VARCHAR(32) NOT NULL,
            hod_username VARCHAR(64) NULL,
            gateway_id INT NULL,
            approved TINYINT(1) NOT NULL DEFAULT 0 CHECK(approved IN (0,1)),
            message_type VARCHAR(32) NOT NULL DEFAULT 'ABSENTEE_ALERT',
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','SENT','FAILED','REJECTED')),
            attempt_count INT NOT NULL DEFAULT 0,
            processing_started_at DATETIME NULL,
            provider_message_id VARCHAR(255),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sent_at DATETIME,
            error TEXT,
            UNIQUE KEY uq_sms_queue_roll_session (roll_no,attendance_session_id),
            FOREIGN KEY(roll_no) REFERENCES students(roll_no) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY(attendance_session_id) REFERENCES attendance_sessions(id),
            FOREIGN KEY(gateway_id) REFERENCES sms_gateways(id) ON UPDATE CASCADE ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        existing_gateway_cols = {row["Field"] if "Field" in row else row["name"] for row in c.execute("SHOW COLUMNS FROM sms_gateways").fetchall()}
        if "auto_send" not in existing_gateway_cols:
            c.execute("ALTER TABLE sms_gateways ADD COLUMN auto_send TINYINT(1) NOT NULL DEFAULT 0")

        # Existing deployments may already have sms_queue with the old
        # PENDING/SENT/FAILED CHECK constraint. The worker now uses a short
        # PROCESSING lease while it owns a row, so upgrade that constraint
        # in-place without dropping any queue data.
        try:
            check_rows = c.execute("""
                SELECT tc.CONSTRAINT_NAME, cc.CHECK_CLAUSE
                FROM information_schema.TABLE_CONSTRAINTS tc
                JOIN information_schema.CHECK_CONSTRAINTS cc
                  ON cc.CONSTRAINT_SCHEMA=tc.CONSTRAINT_SCHEMA
                 AND cc.CONSTRAINT_NAME=tc.CONSTRAINT_NAME
                WHERE tc.CONSTRAINT_SCHEMA=DATABASE()
                  AND tc.TABLE_NAME='sms_queue'
                  AND tc.CONSTRAINT_TYPE='CHECK'
            """).fetchall()
            for chk in check_rows:
                clause = str(chk.get("CHECK_CLAUSE") or "").upper()
                if "STATUS" in clause and "PENDING" in clause and "SENT" in clause and "FAILED" in clause and "REJECTED" not in clause:
                    name = chk["CONSTRAINT_NAME"]
                    c.execute(f"ALTER TABLE sms_queue DROP CHECK `{name}`")
                    c.execute("ALTER TABLE sms_queue ADD CONSTRAINT `chk_sms_queue_status` CHECK(status IN ('PENDING','PROCESSING','SENT','FAILED','REJECTED'))")
                    break
        except Exception as exc:
            # Do not hide the real migration failure; startup logs the problem
            # and the worker will not be able to claim rows safely until the
            # schema is repaired.
            print(f"[SMS QUEUE MIGRATION] Warning updating status CHECK: {exc}")

        # Demo mode is session-scoped: a student may generate another absentee
        # SMS in a later attendance session on the same day. Older deployments
        # have UNIQUE(roll_no,send_date), which silently suppresses the second
        # class. Replace that unique key with (roll_no,attendance_session_id).
        try:
            all_idxs = {r.get("Key_name") for r in c.execute("SHOW INDEX FROM sms_queue").fetchall()}
            if "idx_sms_queue_roll_no" not in all_idxs:
                try:
                    c.execute("ALTER TABLE sms_queue ADD INDEX idx_sms_queue_roll_no (roll_no)")
                except Exception:
                    pass

            idx_rows = c.execute("SHOW INDEX FROM sms_queue").fetchall()
            grouped = {}
            for r in idx_rows:
                if int(r.get("Non_unique", 1)) == 0 and r.get("Key_name") != "PRIMARY":
                    grouped.setdefault(r.get("Key_name"), []).append(r)
            old_unique_names = []
            for name, cols in grouped.items():
                ordered = sorted(cols, key=lambda x: int(x.get("Seq_in_index") or 0))
                names = [x.get("Column_name") for x in ordered]
                if names == ["roll_no", "send_date"]:
                    old_unique_names.append(name)
            for name in old_unique_names:
                c.execute(f"ALTER TABLE sms_queue DROP INDEX `{name}`")
            has_session_unique = any(name == "uq_sms_queue_roll_session" for name in grouped)
            if not has_session_unique:
                c.execute("ALTER TABLE sms_queue ADD UNIQUE KEY uq_sms_queue_roll_session (roll_no,attendance_session_id)")
        except Exception as exc:
            print(f"[SMS QUEUE MIGRATION] Warning updating session uniqueness: {exc}")

        # Existing deployments may already have sms_queue without the new
        # routing/approval columns. Add them without destroying queued data.
        existing_sms_cols = {row["Field"] if "Field" in row else row["name"] for row in c.execute("SHOW COLUMNS FROM sms_queue").fetchall()}
        if "message_type" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN message_type VARCHAR(32) NOT NULL DEFAULT 'ABSENTEE_ALERT'")

        c.execute("""
        CREATE TABLE IF NOT EXISTS sms_absentee_triggers(
            id INT AUTO_INCREMENT PRIMARY KEY,
            hod_username VARCHAR(64) NOT NULL,
            semester_id INT NOT NULL,
            attendance_date VARCHAR(32) NOT NULL,
            session_id INT NOT NULL,
            triggered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_sms_absentee_trigger_scope (hod_username,semester_id,attendance_date),
            FOREIGN KEY(session_id) REFERENCES attendance_sessions(id) ON DELETE RESTRICT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS sms_message_templates(
            id INT AUTO_INCREMENT PRIMARY KEY,
            hod_username VARCHAR(64) NOT NULL,
            message_type VARCHAR(32) NOT NULL,
            template TEXT NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_sms_template_scope_type (hod_username,message_type),
            FOREIGN KEY(hod_username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        if "hod_username" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN hod_username VARCHAR(64) NULL")
        if "gateway_id" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN gateway_id INT NULL")
        if "approved" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN approved TINYINT(1) NOT NULL DEFAULT 0")
            # Legacy rows are approved only after their original HOD/gateway
            # ownership can be resolved below. Unresolved rows stay blocked.
        if "attempt_count" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN attempt_count INT NOT NULL DEFAULT 0")
        if "processing_started_at" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN processing_started_at DATETIME NULL")
        if "provider_message_id" not in existing_sms_cols:
            c.execute("ALTER TABLE sms_queue ADD COLUMN provider_message_id VARCHAR(255) NULL")

        # Add the two routing foreign keys only if they are not already present.
        fk_rows = c.execute("""
            SELECT TABLE_NAME, CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE()
              AND TABLE_NAME IN ('students','sms_queue')
              AND REFERENCED_TABLE_NAME IS NOT NULL
        """).fetchall()
        fk_names = {r["CONSTRAINT_NAME"] for r in fk_rows}
        if "fk_students_hod_username" not in fk_names:
            c.execute("ALTER TABLE students ADD CONSTRAINT fk_students_hod_username FOREIGN KEY(hod_username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE SET NULL")
        user_fk_rows = c.execute("""
            SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users'
              AND COLUMN_NAME='hod_username' AND REFERENCED_TABLE_NAME='users'
        """).fetchall()
        if not user_fk_rows:
            try:
                c.execute("ALTER TABLE users ADD CONSTRAINT fk_users_hod_username FOREIGN KEY(hod_username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE SET NULL")
            except Exception:
                pass
        if "fk_sms_queue_gateway" not in fk_names:
            c.execute("ALTER TABLE sms_queue ADD CONSTRAINT fk_sms_queue_gateway FOREIGN KEY(gateway_id) REFERENCES sms_gateways(id) ON UPDATE CASCADE ON DELETE RESTRICT")
        session_fk_rows = c.execute("""
            SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='attendance_sessions'
              AND COLUMN_NAME='hod_username' AND REFERENCED_TABLE_NAME='users'
        """).fetchall()
        if not session_fk_rows:
            try:
                c.execute("ALTER TABLE attendance_sessions ADD CONSTRAINT fk_attendance_sessions_hod FOREIGN KEY(hod_username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE SET NULL")
            except Exception:
                pass

        # Safe indexes; duplicate-index errors are ignored because startup must
        # remain idempotent across MySQL versions.
        for idx_name, idx_sql in [
            ("idx_students_hod", "CREATE INDEX idx_students_hod ON students(hod_username)"),
            ("idx_users_hod", "CREATE INDEX idx_users_hod ON users(hod_username)"),
            ("idx_attendance_sessions_hod", "CREATE INDEX idx_attendance_sessions_hod ON attendance_sessions(hod_username)"),
            ("idx_sms_queue_gateway", "CREATE INDEX idx_sms_queue_gateway ON sms_queue(gateway_id)"),
            ("idx_sms_queue_hod", "CREATE INDEX idx_sms_queue_hod ON sms_queue(hod_username,send_date)"),
            ("idx_sms_queue_approval", "CREATE INDEX idx_sms_queue_approval ON sms_queue(approved,status,send_date)"),
        ]:
            try:
                c.execute(idx_sql)
            except Exception:
                pass

        # Backfill legacy CSD students.
        hod_username = resolve_hod_for_department(c, "CSD")
        if hod_username:
            c.execute("UPDATE students SET hod_username=%s WHERE department='CSD' AND (hod_username IS NULL OR hod_username='')", (hod_username,))

        # Create one cloud gateway placeholder for the HOD if none exists.
        if hod_username:
            c.execute("""
                INSERT IGNORE INTO sms_gateways(hod_username,gateway_name,gateway_mode,active)
                VALUES(%s,%s,'cloud',1)
            """, (hod_username, f"{hod_username} SMSGate"))

        c.execute("""
        CREATE TABLE IF NOT EXISTS academic_calendar(
            semester_id INT PRIMARY KEY,
            timetable_path VARCHAR(512),
            timetable_updated_at VARCHAR(64),
            timetable_updated_by VARCHAR(64),
            calendar_path VARCHAR(512),
            calendar_updated_at VARCHAR(64),
            calendar_updated_by VARCHAR(64),
            FOREIGN KEY(semester_id) REFERENCES academic_semesters(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Email OTP verification codes -- used for both registration (verify
        # a new account's email before it's usable) and password reset (OTP
        # instead of a clickable link, per the "Email OTP Verification" /
        # "Forgot Password" requirements). One row per OTP request; a purpose
        # + email pair can have several rows over time (old ones just expire/
        # get superseded), so there's no UNIQUE constraint on (email,purpose)
        # -- request_otp() below invalidates any earlier unused row itself.
        c.execute("""
        CREATE TABLE IF NOT EXISTS email_otps(
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            purpose VARCHAR(32) NOT NULL CHECK(purpose IN ('REGISTER','RESET_PASSWORD')),
            code_hash VARCHAR(255) NOT NULL,
            attempts INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL,
            used TINYINT(1) NOT NULL DEFAULT 0 CHECK(used IN (0,1))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS problem_reports(
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) NOT NULL,
            role VARCHAR(32) NOT NULL,
            category VARCHAR(64) NOT NULL DEFAULT 'General',
            subject VARCHAR(255) NOT NULL,
            description TEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','IN_PROGRESS','RESOLVED','CLOSED')),
            admin_notes TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY(username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS role_permissions (
            role VARCHAR(32) PRIMARY KEY,
            can_view_student_phone TINYINT(1) DEFAULT 1,
            can_edit_students TINYINT(1) DEFAULT 1,
            can_delete_students TINYINT(1) DEFAULT 1,
            can_view_audit_logs TINYINT(1) DEFAULT 1,
            can_view_sms_logs TINYINT(1) DEFAULT 1,
            can_manage_calendar TINYINT(1) DEFAULT 1,
            can_manage_subjects TINYINT(1) DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            username VARCHAR(64) PRIMARY KEY,
            can_view_students TINYINT(1) DEFAULT 1,
            can_edit_students TINYINT(1) DEFAULT 0,
            can_delete_students TINYINT(1) DEFAULT 0,
            can_manage_attendance TINYINT(1) DEFAULT 1,
            can_manage_subjects TINYINT(1) DEFAULT 1,
            can_manage_calendar TINYINT(1) DEFAULT 1,
            can_view_sms_logs TINYINT(1) DEFAULT 0,
            can_view_audit_logs TINYINT(1) DEFAULT 0,
            FOREIGN KEY(username) REFERENCES users(username) ON UPDATE CASCADE ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        c.execute("""
        INSERT IGNORE INTO role_permissions (role, can_view_student_phone, can_edit_students, can_delete_students, can_view_audit_logs, can_view_sms_logs, can_manage_calendar, can_manage_subjects)
        VALUES 
            ('ADMIN', 1, 1, 1, 1, 1, 1, 1),
            ('HOD', 1, 1, 1, 1, 1, 1, 1),
            ('FACULTY', 1, 0, 0, 0, 0, 1, 1);
        """)

        # Safely migrate older MySQL check constraints if present
        try:
            checks = c.execute("""
                SELECT CONSTRAINT_NAME, CHECK_CLAUSE 
                FROM information_schema.CHECK_CONSTRAINTS 
                WHERE CONSTRAINT_SCHEMA = DATABASE()
            """).fetchall()
            for chk in checks:
                name = chk.get("CONSTRAINT_NAME")
                clause = str(chk.get("CHECK_CLAUSE", "")).lower()
                if "role" in clause and "admin" not in clause:
                    try:
                        c.execute(f"ALTER TABLE users DROP CHECK `{name}`")
                    except Exception:
                        pass
        except Exception:
            pass

        # Safely create indexes
        indexes = [
            ("idx_attendance_sessions_date", "attendance_sessions(attendance_date)"),
            ("idx_attendance_sessions_subject", "attendance_sessions(subject_id)"),
            ("idx_attendance_records_session", "attendance_records(session_id)"),
            ("idx_attendance_records_roll", "attendance_records(roll_no)"),
            ("idx_attendance_date", "attendance(date)"),
            ("idx_attendance_date_roll", "attendance(date, roll_no)"),
            ("idx_attendance_roll", "attendance(roll_no)"),
            ("idx_marks_roll", "marks(roll_no)"),
            ("idx_students_department", "students(department)"),
            ("idx_sms_queue_status", "sms_queue(status)"),
            ("idx_sms_queue_date", "sms_queue(send_date)"),
            ("idx_email_otps_email_purpose", "email_otps(email, purpose)"),
        ]
        for idx_name, idx_def in indexes:
            try:
                c.execute(f"CREATE INDEX {idx_name} ON {idx_def}")
            except Exception:
                pass

        # Restore explicitly operator-managed custom users, then require an
        # authenticated bootstrap path when the database has no active HOD/Admin.
        _restore_custom_users(c)
        _ensure_bootstrap_account(c)

        # Re-resolve ownership after possible first-run bootstrap.
        hod_username = resolve_hod_for_department(c, "CSD")

        c.execute("UPDATE users SET department='CSD', designation='System Administrator' WHERE username='admin' AND (designation IS NULL OR designation='Head of Department')")
        for row in c.execute("SELECT id,password FROM users").fetchall():
            if not row["password"].startswith("pbkdf2_sha256$"):
                c.execute("UPDATE users SET password=%s WHERE id=%s",(_hash_password(row["password"]),row["id"]))
        for key,value in [("institution_name","VCET CSD Student Management System"),("attendance_threshold","75"),("academic_year","2024-25"),("department","CSD"),("open_student_registration","1")]:
            c.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES(%s,%s)",(key,value))
        for k, v in [
            ("sms_enabled", os.environ.get("SMS_ENABLED", "1")),
            ("sms_repeat_every_attendance", os.environ.get("SMS_REPEAT_EVERY_ATTENDANCE", "1")),
            ("sms_gateway_type", "cloud"),
            ("sms_department_number", "+916300743637"),
            ("sms_modem_port", "/dev/ttyUSB0"),
            ("sms_modem_baud", "115200"),
            ("sms_daily_cap", os.environ.get("SMS_DAILY_CAP", "1000")),
        ]:
            c.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES(%s,%s)", (k, v))

        semesters=[("I-I","I Year - I Semester",1,0),("I-II","I Year - II Semester",2,0),("II-I","II Year - I Semester",3,1),("II-II","II Year - II Semester",4,1),("III-I","III Year - I Semester",5,1),("III-II","III Year - II Semester",6,1),("IV-I","IV Year - I Semester",7,1),("IV-II","IV Year - II Semester",8,1)]
        for code,name,order,is_active in semesters:
            c.execute("INSERT IGNORE INTO academic_semesters(code,name,sort_order,active) VALUES(%s,%s,%s,%s)",(code,name,order,is_active))
        if not c.execute("SELECT 1 FROM settings WHERE `key`='migrated_deactivate_year1'").fetchone():
            c.execute("UPDATE academic_semesters SET active=0 WHERE code IN ('I-I','I-II')")
            c.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES('migrated_deactivate_year1','1')")
        current_sem=c.execute("SELECT id FROM academic_semesters WHERE code='II-II'").fetchone()["id"]
        for idx,name in enumerate(SUBJECTS,1):
            code=f"CSD{220+idx}"
            has_lab=1 if name in ("Database Systems","Web Technologies") else 0
            c.execute("INSERT IGNORE INTO subjects(semester_id,code,name,has_lab) VALUES(%s,%s,%s,%s)",(current_sem,code,name,has_lab))

        iii_i_sem=c.execute("SELECT id FROM academic_semesters WHERE code='III-I'").fetchone()["id"]
        III_I_SUBJECTS=[
            ("24CS501PC", "Algorithms Design and Analysis",                1),
            ("24CS502PC", "Computer Networks",                             1),
            ("24CS503PC", "Introduction to Data Science",                  1),
            ("24CS522PE", "Software Project Management",                   0),
            ("24CS512PE", "Artificial Intelligence",                       0),
            ("24MC510",   "Intellectual Property Rights",                  0),
            ("24CS508PC", "Advanced English Communication Skills Laboratory", 1),
        ]
        for code,name,has_lab in III_I_SUBJECTS:
            c.execute("INSERT IGNORE INTO subjects(semester_id,code,name,has_lab) VALUES(%s,%s,%s,%s)",(iii_i_sem,code,name,has_lab))
        if not c.execute("SELECT 1 FROM settings WHERE `key`='migrated_iii_i_current_semester'").fetchone():
            c.execute("UPDATE students SET current_semester_id=%s WHERE department='CSD'",(iii_i_sem,))
            c.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES('migrated_iii_i_current_semester','1')")
        if not c.execute("SELECT 1 FROM settings WHERE `key`='migrated_iii_i_timetable_doc'").fetchone():
            timetable_dir = Path(__file__).parent / "webapp" / "static" / "uploads" / "academic_calendar"
            existing_pdfs = sorted(timetable_dir.glob("iii-i-timetable-*.pdf")) if timetable_dir.exists() else []
            if existing_pdfs:
                rel_path = f"/static/uploads/academic_calendar/{existing_pdfs[0].name}"
                c.execute("""
                    INSERT INTO academic_calendar(semester_id, timetable_path, timetable_updated_at, timetable_updated_by)
                    VALUES(%s, %s, CURRENT_TIMESTAMP, 'system')
                    ON DUPLICATE KEY UPDATE
                        timetable_path=VALUES(timetable_path), timetable_updated_at=CURRENT_TIMESTAMP, timetable_updated_by='system'
                """, (iii_i_sem, rel_path))
            c.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES('migrated_iii_i_timetable_doc','1')")
        if not c.execute("SELECT 1 FROM settings WHERE `key`='migrated_iii_i_calendar_doc'").fetchone():
            calendar_dir = Path(__file__).parent / "webapp" / "static" / "uploads" / "academic_calendar"
            existing_cal_pdfs = sorted(calendar_dir.glob("iii-i-calendar-*.pdf")) if calendar_dir.exists() else []
            if existing_cal_pdfs:
                rel_path = f"/static/uploads/academic_calendar/{existing_cal_pdfs[0].name}"
                c.execute("""
                    INSERT INTO academic_calendar(semester_id, calendar_path, calendar_updated_at, calendar_updated_by)
                    VALUES(%s, %s, CURRENT_TIMESTAMP, 'system')
                    ON DUPLICATE KEY UPDATE
                        calendar_path=VALUES(calendar_path), calendar_updated_at=CURRENT_TIMESTAMP, calendar_updated_by='system'
                """, (iii_i_sem, rel_path))
            c.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES('migrated_iii_i_calendar_doc','1')")

        # Final ownership backfill after all default users and student rows have been created.
        hod_username = resolve_hod_for_department(c, "CSD")
        if hod_username:
            c.execute("UPDATE users SET hod_username=%s WHERE department='CSD' AND role='HOD' AND username=%s", (hod_username, hod_username))
            c.execute("UPDATE users SET hod_username=%s WHERE department='CSD' AND role='FACULTY' AND (hod_username IS NULL OR hod_username='')", (hod_username,))
            c.execute("UPDATE students SET hod_username=%s WHERE department='CSD' AND (hod_username IS NULL OR hod_username='')", (hod_username,))
            c.execute("UPDATE attendance_sessions a JOIN users u ON u.username=a.faculty_username SET a.hod_username=%s WHERE u.department='CSD' AND a.hod_username IS NULL", (hod_username,))
            c.execute("""
                INSERT IGNORE INTO sms_gateways(hod_username,gateway_name,gateway_mode,active)
                VALUES(%s,%s,'cloud',1)
            """, (hod_username, f"{hod_username} SMSGate"))

            c.execute("""
                UPDATE sms_queue q
                JOIN students st ON st.roll_no=q.roll_no
                JOIN sms_gateways g ON g.hod_username=st.hod_username
                SET q.hod_username=st.hod_username, q.gateway_id=g.id
                WHERE q.gateway_id IS NULL AND st.hod_username=%s
            """, (hod_username,))
            c.execute("""
                UPDATE sms_queue q
                JOIN sms_gateways g ON g.id=q.gateway_id
                SET q.hod_username=g.hod_username
                WHERE q.hod_username IS NULL
            """)

        for col in ("aadhaar_number", "apaar_id"):
            for srow in c.execute(f"SELECT id, {col} FROM students WHERE {col} IS NOT NULL AND {col} != ''").fetchall():
                value = srow[col]
                if not looks_encrypted(value):
                    c.execute(f"UPDATE students SET {col}=%s WHERE id=%s", (encrypt_field(value), srow["id"]))

        # SMSGate gateway credentials are stored as gateway configuration.
        # They intentionally do not use SMS_FIELD_ENCRYPTION_KEY: that key is
        # reserved for student Aadhaar/APAAR field encryption. This keeps SMS
        # gateway setup usable on a clean deployment without coupling it to
        # the student-PII encryption key.


def get_conn():
    c = connect()
    try:
        yield c
    finally:
        c.close()


_DUMMY_PASSWORD_HASH = _hash_password("dummy-password-for-constant-time")


def auth(username, password):
    u = username.strip()
    if not u or not password:
        return None
    with connect() as c:
        rows = c.execute(
            """SELECT * FROM users 
               WHERE (username = %s 
                      OR (student_roll_no IS NOT NULL AND student_roll_no != '' AND student_roll_no = %s)
                      OR (email IS NOT NULL AND email != '' AND email = %s))
               AND active = 1""",
            (u, u, u),
        ).fetchall()
        # Login identifiers are exact matches only. In particular, never
        # authenticate by partial/full-name matching: names are not unique
        # credentials and a matching password could otherwise authenticate
        # against an unintended account.
        if not rows:
            _verify_password(password, _DUMMY_PASSWORD_HASH)
            return None
        for row in rows:
            if _verify_password(password, row["password"]):
                return row
        return None


def change_password(username, old_password, new_password):
    if len(new_password)<8: raise ValueError("New password must be at least 8 characters")
    with connect() as c:
        row=c.execute("SELECT * FROM users WHERE username=%s",(username,)).fetchone()
        if not row or not _verify_password(old_password,row["password"]): raise ValueError("Current password is incorrect")
        c.execute("UPDATE users SET password=%s,must_change_password=0,auth_version=auth_version+1 WHERE id=%s",(_hash_password(new_password),row["id"]))
        audit(c,username,"CHANGE_PASSWORD","user",username)


def create_user(username,password,role,full_name="",student_roll_no=None,actor="system"):
    username=username.strip()
    if len(username)<3: raise ValueError("Username must be at least 3 characters")
    if len(password)<8: raise ValueError("Password must be at least 8 characters")
    if role not in ROLES: raise ValueError("Invalid role")
    with connect() as c:
        if role=="STUDENT":
            if not student_roll_no: raise ValueError("Student account must be linked to a roll number")
            s=c.execute("SELECT * FROM students WHERE roll_no=%s AND department='CSD'",(student_roll_no,)).fetchone()
            if not s: raise ValueError("Student roll number was not found in CSD")
            full_name=s["name"]
        pw_hash = _hash_password(password)
        hod_username = None
        dept = None
        if role == "ADMIN":
            dept = "CSD"
        elif role == "HOD":
            hod_username = username
            dept = "CSD"
        elif role == "FACULTY":
            dept = "CSD"
            actor_row = c.execute("SELECT role,hod_username,department FROM users WHERE username=%s", (actor,)).fetchone()
            if actor_row and actor_row["role"] == "HOD":
                hod_username = actor
            elif actor_row and actor_row.get("hod_username"):
                hod_username = actor_row["hod_username"]
            elif actor_row and actor_row.get("department"):
                hod_username = resolve_hod_for_department(c, actor_row["department"])
            else:
                hod_username = resolve_hod_for_department(c, "CSD")
        c.execute("INSERT INTO users(username,password,role,student_roll_no,full_name,hod_username,department) VALUES(%s,%s,%s,%s,%s,%s,%s)",(username,pw_hash,role,student_roll_no,full_name.strip(),hod_username,dept))
        _save_custom_user_backup(username, pw_hash, role, full_name.strip(), student_roll_no)
        audit(c,actor,"CREATE","user",f"{username} ({role})")


def ensure_student_login(roll_no, actor="system"):
    with connect() as c:
        s=c.execute("SELECT * FROM students WHERE roll_no=%s AND department='CSD'",(roll_no,)).fetchone()
        if not s: raise ValueError("CSD student not found")
        if c.execute("SELECT 1 FROM users WHERE student_roll_no=%s",(roll_no,)).fetchone(): raise ValueError("This student already has a login")
        username=roll_no.lower(); password=roll_no+'@CSD'
        pw_hash = _hash_password(password)
        c.execute("INSERT INTO users(username,password,role,student_roll_no,full_name,must_change_password) VALUES(%s,%s,'STUDENT',%s,%s,1)",(username,pw_hash,roll_no,s["name"]))
        _save_custom_user_backup(username, pw_hash, "STUDENT", s["name"], roll_no)
        audit(c,actor,"CREATE","student_login",roll_no)
        return username,password


def reset_student_password(roll_no, actor="system"):
    with connect() as c:
        user=c.execute("SELECT * FROM users WHERE student_roll_no=%s AND role='STUDENT'",(roll_no,)).fetchone()
        if not user: raise ValueError("Student login does not exist")
        password=roll_no+'@CSD'
        c.execute("UPDATE users SET password=%s,active=1,must_change_password=1,auth_version=auth_version+1 WHERE id=%s",(_hash_password(password),user["id"]))
        audit(c,actor,"RESET_PASSWORD","student_login",roll_no)
        return user["username"],password


OPEN_REGISTRATION_SETTING_KEY = "open_student_registration"


def is_open_registration_enabled() -> bool:
    return get_setting(OPEN_REGISTRATION_SETTING_KEY, "1") == "1"


def register_student(roll_no, username, password, full_name=None, email=None, phone=None, year_of_study=None, department="CSD"):
    """Self-service registration with MANDATORY email & OTP verification.

    Email is required for creating a new user account, and must be OTP-verified
    (via request_otp/verify_otp, purpose='REGISTER') before account creation.
    """
    username = username.strip()
    roll_no = str(roll_no).strip()
    email = (email or "").strip().lower()
    phone = (phone or "").strip()
    dept = (department or "CSD").strip()

    if not email or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("A valid email address is required for registration")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    with connect() as c:
        # Check if email has been verified via OTP
        otp_verified = c.execute(
            "SELECT 1 FROM email_otps WHERE email=%s AND purpose='REGISTER' AND used=1 LIMIT 1",
            (email,),
        ).fetchone()
        if not otp_verified:
            raise ValueError("Email verification is required — please send and verify the OTP code for your email before registering")

        if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
            raise ValueError("That email address is already registered")

        s = c.execute("SELECT * FROM students WHERE roll_no=%s AND department=%s", (roll_no, dept)).fetchone()

        # Map year_of_study (e.g. '1', '2', '3', '4') to initial semester ID
        sem_id = None
        if year_of_study:
            sem_code_map = {"1": "I-I", "2": "II-I", "3": "III-I", "4": "IV-I"}
            code = sem_code_map.get(str(year_of_study).strip())
            if code:
                sem_row = c.execute("SELECT id FROM academic_semesters WHERE code=%s", (code,)).fetchone()
                if sem_row:
                    sem_id = sem_row["id"]

        assigned_hod = resolve_hod_for_department(c, dept)

        if not s:
            if not is_open_registration_enabled():
                raise ValueError("Roll number was not found in CSD records")
            name = str(full_name or "").strip() or username or f"Student {roll_no}"
            validate_student({"roll_no": roll_no, "name": name, "department": dept})
            if c.execute("SELECT 1 FROM students WHERE roll_no=%s", (roll_no,)).fetchone():
                raise ValueError("That roll number is already registered")
            c.execute(
                "INSERT INTO students(roll_no,name,department,email,phone,current_semester_id,hod_username) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (roll_no, name, dept, email, phone or None, sem_id, assigned_hod),
            )
            audit(c, username, "SELF_REGISTER_NEW_STUDENT", "student", f"{roll_no} ({name}) — open registration, verified email")
            s = c.execute("SELECT * FROM students WHERE roll_no=%s AND department=%s", (roll_no, dept)).fetchone()
        else:
            if not s.get("hod_username") and assigned_hod:
                c.execute("UPDATE students SET hod_username=%s WHERE roll_no=%s", (assigned_hod, roll_no))
            if phone or sem_id:
                c.execute(
                    "UPDATE students SET phone=COALESCE(NULLIF(%s,''),phone), current_semester_id=COALESCE(%s,current_semester_id) WHERE roll_no=%s",
                    (phone, sem_id, roll_no)
                )

        if c.execute("SELECT 1 FROM users WHERE student_roll_no=%s", (roll_no,)).fetchone():
            raise ValueError("This student already has a login — use Forgot Password instead")
        if c.execute("SELECT 1 FROM users WHERE username=%s", (username,)).fetchone():
            raise ValueError("That username is already taken")

        pw_hash = _hash_password(password)
        c.execute(
            "INSERT INTO users(username,password,role,student_roll_no,full_name,email,email_verified,department,hod_username) VALUES(%s,%s,'STUDENT',%s,%s,%s,1,%s,%s)",
            (username, pw_hash, roll_no, s["name"], email, dept, assigned_hod),
        )
        c.execute("UPDATE students SET email=%s WHERE roll_no=%s AND (email IS NULL OR email = '' OR email != %s)", (email, roll_no, email))
        _save_custom_user_backup(username, pw_hash, "STUDENT", s["name"], roll_no)
        audit(c, username, "SELF_REGISTER", "student_login", roll_no)
        return username


def reset_password_by_email(email, new_password):
    """Password reset via a verified OTP (api/routes_auth.py's
    /reset-password-otp) rather than a token link. Same 8-char floor and
    audit trail for the OTP reset; the OTP itself was already
    checked by verify_otp() before this is called, so this function trusts
    that the email has just been proven to belong to the requester."""
    if len(new_password) < 8:
        raise ValueError("New password must be at least 8 characters")
    with connect() as c:
        user = c.execute("SELECT * FROM users WHERE email=%s AND active=1", (email,)).fetchone()
        if not user:
            raise ValueError("Account not found or inactive")
        c.execute("UPDATE users SET password=%s, must_change_password=0, auth_version=auth_version+1 WHERE id=%s", (_hash_password(new_password), user["id"]))
        audit(c, user["username"], "RESET_PASSWORD_VIA_OTP", "user", user["username"])
        return True


# ---------------------------------------------------------------------------
# Email OTP verification (registration + password reset)
# ---------------------------------------------------------------------------
OTP_MAX_AGE_MINUTES = 10          # matches the "expires in 10 minutes" copy in the email/UI
OTP_MAX_ATTEMPTS = 5              # wrong-code guesses allowed before an OTP is burned
OTP_RESEND_COOLDOWN_SECONDS = 45  # UI-side cooldown lives in the frontend; this is the server-side floor


def _hash_otp(email, purpose, code):
    # Salted with email+purpose so the same 6-digit code hashes differently
    # per (email, purpose) pair -- a leaked email_otps table row can't be
    # replayed against a different account/purpose even if two users were
    # ever issued the same random code at the same time.
    return hashlib.sha256(f"{email.lower()}:{purpose}:{code}".encode()).hexdigest()


def request_otp(email, purpose):
    """Generates and stores a fresh, cryptographically secure 6-digit OTP (valid for 10 minutes),
    invalidating any earlier unused OTP for the same (email, purpose) pair first."""
    import secrets
    import datetime

    if purpose not in ("REGISTER", "RESET_PASSWORD"):
        raise ValueError("Invalid OTP purpose")
    email = email.strip().lower()
    code = f"{secrets.randbelow(900000) + 100000}"

    # Store both timestamps as UTC values generated by the application. This
    # avoids depending on the MySQL server/session timezone, which may differ
    # from the application host after deployment.
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    cutoff = (now - datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (now + datetime.timedelta(minutes=OTP_MAX_AGE_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

    with connect() as c:
        # Rate limit check: Maximum 5 OTP requests per email within 10 minutes
        recent_requests = c.execute(
            """SELECT COUNT(*) AS count FROM email_otps 
               WHERE email=%s AND purpose=%s AND created_at >= %s""",
            (email, purpose, cutoff),
        ).fetchone()["count"]
        if recent_requests >= 5:
            raise ValueError("Too many OTP requests for this email. Please wait a few minutes before requesting a new code.")

        # Burn any earlier, still-unused OTP for this email+purpose so only
        # the most recently requested code is ever valid
        c.execute(
            "UPDATE email_otps SET used=1 WHERE email=%s AND purpose=%s AND used=0",
            (email, purpose),
        )
        c.execute(
            """INSERT INTO email_otps(email, purpose, code_hash, created_at, expires_at)
               VALUES(%s, %s, %s, %s, %s)""",
            (email, purpose, _hash_otp(email, purpose, code), created_at, expires_at),
        )
        audit(c, email, "REQUEST_OTP", purpose.lower(), email)
    return code


def verify_otp(email, purpose, code):
    """Checks a submitted code against the latest unused, unexpired OTP for (email, purpose).
    Strictly valid for 10 minutes with max 5 failed attempts allowed."""
    import datetime

    if purpose not in ("REGISTER", "RESET_PASSWORD"):
        raise ValueError("Invalid OTP purpose")
    email = email.strip().lower()
    code = str(code).strip()
    with connect() as c:
        row = c.execute(
            """SELECT * FROM email_otps WHERE email=%s AND purpose=%s AND used=0
               ORDER BY id DESC LIMIT 1 FOR UPDATE""",
            (email, purpose),
        ).fetchone()
        if not row:
            raise ValueError("No pending verification code for this email — please click 'Send Verification Code'")
        if row["attempts"] >= OTP_MAX_ATTEMPTS:
            c.execute("UPDATE email_otps SET used=1 WHERE id=%s", (row["id"],))
            raise ValueError("Too many incorrect attempts — OTP security locked. Please click 'Resend New OTP'")

        # OTP timestamps are stored as UTC values, so expiry is independent
        # of the MySQL server/session timezone.
        now_str = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        exp_str = str(row["expires_at"])
        if exp_str < now_str:
            c.execute("UPDATE email_otps SET used=1 WHERE id=%s", (row["id"],))
            raise ValueError("This 6-digit OTP code has expired after 10 minutes. Please click 'Resend New OTP' to receive a fresh code.")

        if not hmac.compare_digest(row["code_hash"], _hash_otp(email, purpose, code)):
            c.execute("UPDATE email_otps SET attempts=attempts+1 WHERE id=%s", (row["id"],))
            remaining = OTP_MAX_ATTEMPTS - (row["attempts"] + 1)
            if remaining <= 0:
                c.execute("UPDATE email_otps SET used=1 WHERE id=%s", (row["id"],))
                raise ValueError("Too many incorrect attempts — OTP security locked. Please click 'Resend New OTP'")
            raise ValueError(f"Incorrect OTP code ({remaining} attempt(s) remaining)")

        c.execute("UPDATE email_otps SET used=1 WHERE id=%s", (row["id"],))
        audit(c, email, "VERIFY_OTP", purpose.lower(), email)
        return True



def mark_email_verified(email):
    with connect() as c:
        c.execute("UPDATE users SET email_verified=1 WHERE email=%s", (email.strip().lower(),))


def find_user_by_email(email):
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE email=%s AND active=1", (email.strip().lower(),)).fetchone()


def create_problem_report(username, role, category, subject, description):
    subject = str(subject or "").strip()
    description = str(description or "").strip()
    category = str(category or "General").strip()
    if not subject:
        raise ValueError("Subject / Title is required")
    if not description:
        raise ValueError("Problem description is required")
    with connect() as c:
        c.execute(
            """INSERT INTO problem_reports(username, role, category, subject, description)
               VALUES(%s, %s, %s, %s, %s)""",
            (username, role, category, subject, description),
        )
        audit(c, username, "SUBMIT_PROBLEM_REPORT", "report", subject[:50])
        return True


def check_permission(role: str, perm_key: str) -> bool:
    if role in ("HOD", "ADMIN"):
        return True
    with connect() as c:
        row = c.execute("SELECT * FROM role_permissions WHERE role=%s", (role,)).fetchone()
        if not row:
            return True
        return bool(row.get(perm_key, 1))


def get_all_role_permissions():
    with connect() as c:
        rows = c.execute("SELECT * FROM role_permissions").fetchall()
        if not rows:
            return [
                {"role": "ADMIN", "can_view_student_phone": 1, "can_edit_students": 1, "can_delete_students": 1, "can_view_audit_logs": 1, "can_view_sms_logs": 1, "can_manage_calendar": 1, "can_manage_subjects": 1},
                {"role": "HOD", "can_view_student_phone": 1, "can_edit_students": 1, "can_delete_students": 1, "can_view_audit_logs": 1, "can_view_sms_logs": 1, "can_manage_calendar": 1, "can_manage_subjects": 1},
                {"role": "FACULTY", "can_view_student_phone": 1, "can_edit_students": 0, "can_delete_students": 0, "can_view_audit_logs": 0, "can_view_sms_logs": 0, "can_manage_calendar": 1, "can_manage_subjects": 1},
            ]
        return [dict(r) for r in rows]


def update_role_permissions(role: str, perms: dict):
    # WHY MySQL syntax, not SQLite: role_permissions.role has a UNIQUE
    # constraint (one row per role), so this is a real upsert on that key.
    # MySQL has no ON CONFLICT()/excluded — the equivalent is ON DUPLICATE
    # KEY UPDATE with VALUES(col) referencing the row that was attempted.
    with connect() as c:
        c.execute(
            """INSERT INTO role_permissions(role, can_view_student_phone, can_edit_students, can_delete_students, can_view_audit_logs, can_view_sms_logs, can_manage_calendar, can_manage_subjects)
               VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
               can_view_student_phone=VALUES(can_view_student_phone),
               can_edit_students=VALUES(can_edit_students),
               can_delete_students=VALUES(can_delete_students),
               can_view_audit_logs=VALUES(can_view_audit_logs),
               can_view_sms_logs=VALUES(can_view_sms_logs),
               can_manage_calendar=VALUES(can_manage_calendar),
               can_manage_subjects=VALUES(can_manage_subjects)""",
            (
                role,
                int(perms.get("can_view_student_phone", 1)),
                int(perms.get("can_edit_students", 0)),
                int(perms.get("can_delete_students", 0)),
                int(perms.get("can_view_audit_logs", 0)),
                int(perms.get("can_view_sms_logs", 0)),
                int(perms.get("can_manage_calendar", 1)),
                int(perms.get("can_manage_subjects", 1)),
            ),
        )
        return True


def get_user_permissions(username: str) -> dict:
    with connect() as c:
        user = c.execute("SELECT role FROM users WHERE username=%s", (username,)).fetchone()
        if user and user["role"] in ("HOD", "ADMIN"):
            return {
                "username": username,
                "can_view_students": 1,
                "can_edit_students": 1,
                "can_delete_students": 1,
                "can_manage_attendance": 1,
                "can_manage_subjects": 1,
                "can_manage_calendar": 1,
                "can_view_sms_logs": 1,
                "can_view_audit_logs": 1,
            }
        row = c.execute("SELECT * FROM user_permissions WHERE username=%s", (username,)).fetchone()
        if not row:
            return {
                "username": username,
                "can_view_students": 1,
                "can_edit_students": 0,
                "can_delete_students": 0,
                "can_manage_attendance": 1,
                "can_manage_subjects": 1,
                "can_manage_calendar": 1,
                "can_view_sms_logs": 0,
                "can_view_audit_logs": 0,
            }
        return dict(row)


def update_user_permissions(username: str, perms: dict):
    # Same MySQL-vs-SQLite upsert fix as update_role_permissions above —
    # user_permissions.username is UNIQUE, ON DUPLICATE KEY UPDATE +
    # VALUES(col) is the MySQL equivalent of ON CONFLICT()/excluded.
    with connect() as c:
        c.execute(
            """INSERT INTO user_permissions(username, can_view_students, can_edit_students, can_delete_students, can_manage_attendance, can_manage_subjects, can_manage_calendar, can_view_sms_logs, can_view_audit_logs)
               VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
               can_view_students=VALUES(can_view_students),
               can_edit_students=VALUES(can_edit_students),
               can_delete_students=VALUES(can_delete_students),
               can_manage_attendance=VALUES(can_manage_attendance),
               can_manage_subjects=VALUES(can_manage_subjects),
               can_manage_calendar=VALUES(can_manage_calendar),
               can_view_sms_logs=VALUES(can_view_sms_logs),
               can_view_audit_logs=VALUES(can_view_audit_logs)""",
            (
                username,
                int(perms.get("can_view_students", 1)),
                int(perms.get("can_edit_students", 0)),
                int(perms.get("can_delete_students", 0)),
                int(perms.get("can_manage_attendance", 1)),
                int(perms.get("can_manage_subjects", 1)),
                int(perms.get("can_manage_calendar", 1)),
                int(perms.get("can_view_sms_logs", 0)),
                int(perms.get("can_view_audit_logs", 0)),
            ),
        )
        return True


def get_problem_reports():
    with connect() as c:
        return c.execute("SELECT * FROM problem_reports ORDER BY created_at DESC").fetchall()


def update_problem_report_status(report_id, status, admin_notes=None, actor="admin"):
    valid_statuses = ("PENDING", "IN_PROGRESS", "RESOLVED", "CLOSED")
    status = status.upper().strip()
    if status not in valid_statuses:
        raise ValueError(f"Invalid status. Must be one of {valid_statuses}")
    with connect() as c:
        # WHY check existence first, not rely on UPDATE's rowcount: MySQL
        # reports rowcount=0 both when no row matches the WHERE AND when a
        # row matches but every column is already equal to the new value —
        # the latter is a legitimate no-op update, not a missing report.
        existing = c.execute("SELECT id FROM problem_reports WHERE id=%s", (report_id,)).fetchone()
        if not existing:
            raise ValueError(f"Problem report {report_id} not found")
        c.execute(
            "UPDATE problem_reports SET status=%s, admin_notes=%s WHERE id=%s",
            (status, admin_notes or "", report_id),
        )
        audit(c, actor, "UPDATE_PROBLEM_REPORT", "report", f"ID {report_id} -> {status}")
        return True