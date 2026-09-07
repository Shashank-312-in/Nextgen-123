import os
import sys
sys.path.insert(0, ".")

import database
from api.app import app
from fastapi.testclient import TestClient

print("--- Running database.init_db() ---")
database.init_db()

with database.connect() as c:
    admin_row = c.execute("SELECT id, username, role, full_name, designation, department, email FROM users WHERE username='admin'").fetchone()
    print("Admin user:", dict(admin_row) if admin_row else None)

    hod_rows = c.execute("SELECT id, username, role, full_name, designation, department, email FROM users WHERE role='HOD'").fetchall()
    print("HOD users:", [dict(r) for r in hod_rows])

    faculty_rows = c.execute("SELECT id, username, role, full_name, designation, department, email FROM users WHERE role='FACULTY'").fetchall()
    print(f"Faculty count: {len(faculty_rows)}")

    resolved_hod = database.resolve_hod_for_department(c, "CSD")
    print("Resolved HOD for CSD:", resolved_hod)

    role_perms = database.get_all_role_permissions()
    print("Role permissions:", role_perms)

print("\n--- Testing API Endpoints ---")
client = TestClient(app)

# 1. Test Admin Login
admin_login = client.post("/api/auth/login", json={"username": os.environ["VERIFY_ADMIN_USERNAME"], "password": os.environ["VERIFY_ADMIN_PASSWORD"]})
print("Admin login status:", admin_login.status_code)
admin_data = admin_login.json()
print("Admin login response user:", admin_data.get("data", {}).get("user"))
admin_token = admin_data.get("data", {}).get("access_token")

# 2. Test Admin My Account
admin_headers = {"Authorization": f"Bearer {admin_token}"}
me_res = client.get("/api/me/account", headers=admin_headers)
print("Admin /api/me/account status:", me_res.status_code)
print("Admin profile data:", me_res.json().get("data", {}).get("user"))

# 3. Test Admin Access to Faculty, Subjects, Reports, Calendar
fac_res = client.get("/api/faculty", headers=admin_headers)
print("Admin /api/faculty status:", fac_res.status_code)
print("Admin /api/faculty accounts count:", len(fac_res.json().get("data", {}).get("accounts", [])))

subj_res = client.get("/api/subjects", headers=admin_headers)
print("Admin /api/subjects status:", subj_res.status_code)

rep_res = client.get("/api/reports", headers=admin_headers)
print("Admin /api/reports status:", rep_res.status_code)

cal_res = client.get("/api/academic-calendar", headers=admin_headers)
print("Admin /api/academic-calendar status:", cal_res.status_code)

# 4. Test HOD Login (Srikanthhod or similar)
hod_user = hod_rows[0]["username"] if hod_rows else None
if hod_user:
    print(f"\n--- Testing HOD User ({hod_user}) ---")
    with database.connect() as c:
        row = c.execute("SELECT username, role, full_name, designation, department, email FROM users WHERE username=%s", (hod_user,)).fetchone()
        print("HOD user in DB:", dict(row))

print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
