import os
import sys

sys.path.insert(0, os.path.abspath("."))
import database

with database.connect() as c:
    c.execute("DELETE FROM problem_reports")
    c.execute("DELETE FROM sms_queue")
    c.execute("DELETE FROM attendance_records")
    c.execute("DELETE FROM attendance_sessions")
    c.execute("DELETE FROM attendance")
    c.execute("DELETE FROM audit_logs")
    c.execute("DELETE FROM checklist")
    c.execute("DELETE FROM marks")
    c.execute("DELETE FROM student_semester_history")
    c.execute("DELETE FROM email_otps")
    c.execute("DELETE FROM bonafide_issues")
    c.execute("DELETE FROM subject_faculty")
    c.execute("DELETE FROM user_permissions")
    c.execute("DELETE FROM users WHERE username NOT IN ('admin', 'Naveen', 'student_1')")
    c.commit()
    print("[OK] Production database is completely fresh and clean!")
