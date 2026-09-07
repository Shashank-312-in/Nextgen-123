import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import connect

def run_fix():
    with connect() as c:
        # 1. Update faculty users to have proper departmental HOD and department
        c.execute("UPDATE users SET hod_username='Srikanthhod', department='CSD' WHERE role='FACULTY'")
        print("Updated faculty users.")

        # 2. Update attendance sessions to have proper departmental HOD
        c.execute("UPDATE attendance_sessions SET hod_username='Srikanthhod' WHERE faculty_username != 'admin'")
        print("Updated attendance sessions.")

        # 3. Update SMS gateway for Srikanthhod with the configured cloud credentials from gateway 1
        admin_gw = c.execute("SELECT device_id, username, password, local_url, modem_port FROM sms_gateways WHERE hod_username='admin'").fetchone()
        if admin_gw:
            c.execute("""
                UPDATE sms_gateways 
                SET device_id=%s, username=%s, password=%s, local_url=%s, modem_port=%s, active=1
                WHERE hod_username='Srikanthhod'
            """, (admin_gw['device_id'], admin_gw['username'], admin_gw['password'], admin_gw['local_url'], admin_gw['modem_port']))
            print("Updated Srikanthhod SMS gateway credentials.")

        # 4. Verify users
        fac_users = c.execute("SELECT username, role, hod_username, department FROM users WHERE role='FACULTY'").fetchall()
        print("\nFACULTY USERS:")
        for f in fac_users:
            print(dict(f))

        # 5. Verify sessions
        sessions = c.execute("SELECT id, attendance_date, semester_id, subject_id, faculty_username, hod_username FROM attendance_sessions").fetchall()
        print("\nSESSIONS:")
        for s in sessions:
            print(dict(s))

if __name__ == "__main__":
    run_fix()
