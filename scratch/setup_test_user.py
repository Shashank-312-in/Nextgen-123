import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import create_user, auth, connect

roll = "TEST_STUDENT_01"
with connect() as c:
    c.execute("DELETE FROM users WHERE username='student_1'")
    c.execute(
        """INSERT INTO students (roll_no, name, department, active)
           VALUES (%s, 'Test Student One', 'CSD', 1)
           ON DUPLICATE KEY UPDATE name='Test Student One', department='CSD', active=1""",
        (roll,)
    )

create_user("student_1", "student123", "STUDENT", student_roll_no=roll)
row = auth("student_1", "student123")
print("Auth verify:", row["username"] if row else "FAILED")
