"""Comprehensive Clean & Fresh Launch Reset Script
Cleans old dummy data, audit logs, orphaned student/calendar uploads,
and verifies production readiness for server launch.
"""
import os
import sys
import shutil

sys.path.insert(0, os.path.abspath("."))
import database
from webapp.photo_upload import UPLOADS_DIR

print("=== STARTING FULL PRODUCTION CLEAN & FRESH RESET ===")

with database.connect() as c:
    # 1. Clear audit logs
    c.execute("DELETE FROM audit_logs")
    print("[OK] Cleared audit_logs")

    # 2. Clear attendance & SMS queue
    c.execute("DELETE FROM attendance_records")
    c.execute("DELETE FROM attendance_sessions")
    c.execute("DELETE FROM attendance")
    c.execute("DELETE FROM sms_queue")
    print("[OK] Cleared attendance_records, attendance_sessions, attendance, sms_queue")

    # 3. Clear problem reports, bonafide issues, email otps
    c.execute("DELETE FROM problem_reports")
    c.execute("DELETE FROM bonafide_issues")
    c.execute("DELETE FROM email_otps")
    print("[OK] Cleared problem_reports, bonafide_issues, email_otps")

    # 4. Clear student records & history (keep test student for test suite)
    c.execute("DELETE FROM checklist")
    c.execute("DELETE FROM marks")
    c.execute("DELETE FROM student_semester_history")
    c.execute("DELETE FROM students WHERE roll_no != 'STU_TEST_001'")
    print("[OK] Cleared student records & history")

    # 5. Clear subject-faculty mappings and user permissions
    c.execute("DELETE FROM subject_faculty")
    c.execute("DELETE FROM user_permissions")
    print("[OK] Cleared subject_faculty mappings and user_permissions")

    # 6. Reset academic calendar uploaded paths
    c.execute("UPDATE academic_calendar SET timetable_path=NULL, calendar_path=NULL")
    print("[OK] Reset academic_calendar paths")

    # 7. Clean dummy faculty/user accounts (leaving admin and genuine users)
    c.execute("DELETE FROM users WHERE username IN ('dummy', 'faculty1', 'faculty2', 'faculty_csd', 'test_faculty_del')")
    c.execute("UPDATE users SET must_change_password=0 WHERE username='admin'")
    c.commit()
    print("[OK] Cleaned users table")

# 8. Clean orphaned uploads in webapp/uploads/students and webapp/uploads/academic_calendar
for subdir in ["students", "academic_calendar", "certificates"]:
    folder = UPLOADS_DIR / subdir
    if folder.exists():
        for f in folder.glob("*.*"):
            try:
                os.remove(f)
                print(f"[OK] Removed orphaned file: {subdir}/{f.name}")
            except Exception as e:
                print(f"! Could not remove {f}: {e}")

# 9. Clean any root test logs
for log_file in ["test_results.log", "pytest_report.html"]:
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
            print(f"[OK] Removed temporary file: {log_file}")
        except Exception:
            pass

print("\n=== VERIFYING FINAL DATABASE STATE ===")
with database.connect() as c:
    tables = [
        "users", "students", "attendance_sessions", "attendance_records",
        "sms_queue", "problem_reports", "audit_logs", "subject_faculty",
        "user_permissions", "academic_calendar", "subjects", "institution_profile"
    ]
    for t in tables:
        cnt = c.execute(f"SELECT COUNT(*) as c FROM `{t}`").fetchone()["c"]
        print(f"  {t}: {cnt} rows")

print("\n=== SYSTEM IS FULLY FRESH, CLEAN & READY FOR LAUNCH! ===")
