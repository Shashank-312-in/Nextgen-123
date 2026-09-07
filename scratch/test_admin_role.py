import sys
sys.path.insert(0, ".")
import database

with database.connect() as c:
    # Check current table constraints
    checks = c.execute("""
        SELECT CONSTRAINT_NAME, CHECK_CLAUSE 
        FROM information_schema.CHECK_CONSTRAINTS 
        WHERE CONSTRAINT_SCHEMA = DATABASE()
    """).fetchall()
    print("Check constraints:", checks)
    
    for chk in checks:
        name = chk.get("CONSTRAINT_NAME")
        clause = chk.get("CHECK_CLAUSE", "")
        if "role" in str(clause).lower():
            try:
                c.execute(f"ALTER TABLE users DROP CHECK `{name}`")
                print(f"Dropped check constraint {name}")
            except Exception as e:
                print(f"Could not drop check constraint {name}: {e}")

    c.execute("UPDATE users SET role='ADMIN', full_name='System Administrator', designation='System Administrator' WHERE username='admin'")
    admin_row = c.execute("SELECT id, username, role, full_name, designation, department, email FROM users WHERE username='admin'").fetchone()
    print("Admin row:", admin_row)

    hod_row = c.execute("SELECT id, username, role, full_name, designation, department, email FROM users WHERE role='HOD'").fetchall()
    print("HOD rows:", hod_row)
