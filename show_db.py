"""Safe MySQL persistence diagnostic.

Run this on the college machine immediately before a MySQL restart and again
after the restart. Compare the printed server identity, data directory,
database name, and row counts.

This script intentionally prints no password, connection key, or row contents.
It connects directly to MYSQL_HOST/MYSQL_PORT; it is not a DB-proxy diagnostic.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

try:
    import mysql.connector as mysql
except ImportError:
    mysql = None

try:
    import pymysql
except ImportError:
    pymysql = None


def connect():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "student_management")

    if mysql is not None:
        return mysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )
    if pymysql is not None:
        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            cursorclass=pymysql.cursors.DictCursor,
        )
    raise RuntimeError("Install mysql-connector-python or PyMySQL first.")


conn = connect()
cursor = conn.cursor(dictionary=True) if mysql is not None else conn.cursor()

cursor.execute(
    """
    SELECT
        @@hostname AS server_hostname,
        @@port AS server_port,
        @@datadir AS data_directory,
        DATABASE() AS database_name,
        @@global.time_zone AS global_timezone,
        @@session.time_zone AS session_timezone,
        VERSION() AS mysql_version
    """
)
info = cursor.fetchone()

print("=== MYSQL PERSISTENCE SNAPSHOT ===")
for key in (
    "server_hostname",
    "server_port",
    "data_directory",
    "database_name",
    "mysql_version",
    "global_timezone",
    "session_timezone",
):
    print(f"{key}: {info[key]}")

print("\n=== ROW COUNTS ===")
for table in ("users", "students", "attendance_sessions", "attendance_records", "attendance", "marks", "email_otps"):
    try:
        cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
        row = cursor.fetchone()
        print(f"{table}: {row['count']}")
    except Exception as exc:
        print(f"{table}: ERROR ({type(exc).__name__})")

cursor.close()
conn.close()
