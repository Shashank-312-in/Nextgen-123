import sys
import os

sys.path.insert(0, os.path.abspath("."))
import database

with database.connect() as c:
    targets = ['faculty1', 'faculty2', 'faculty_csd']
    for u in targets:
        c.execute('DELETE FROM user_permissions WHERE username=%s', (u,))
        c.execute('DELETE FROM subject_faculty WHERE faculty_username=%s', (u,))
        c.execute('DELETE FROM problem_reports WHERE username=%s', (u,))
        c.execute('DELETE FROM sms_gateways WHERE hod_username=%s', (u,))
        c.execute('DELETE FROM users WHERE username=%s', (u,))
    c.commit()
    print('Target profiles removed from DB successfully.')
    
    # Also trigger init_db to confirm they do NOT get re-inserted
    database.init_db()
    
    users = c.execute("SELECT username, role, full_name, active FROM users WHERE role != 'STUDENT' ORDER BY role, username").fetchall()
    print('\nCurrent non-student users in DB:')
    for row in users:
        print(f" - {row['username']} | {row['full_name']} | Role: {row['role']} | Active: {row['active']}")
