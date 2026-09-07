import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import connect
from sms_app.services.attendance_service import load_register, month_register
from api.deps import CurrentUser
import asyncio

async def verify():
    # 1. Test load_register for session 13
    students, existing = load_register(13)
    print(f"Session 13 Roster Student Count: {len(students)}")
    for s in students[:5]:
        print(f"  Roll: {s['roll_no']}, Name: {s['name']}")

    # 2. Test students_list route directly with Faculty user
    from api.routes_students import students_list
    faculty_user = CurrentUser(
        username="Naveen",
        role="FACULTY",
        student_roll_no=None,
        must_change_password=False,
    )
    result = await students_list(q="", status="All", user=faculty_user)
    body_data = json.loads(result.body.decode("utf-8"))
    student_rows = body_data["data"]
    print(f"\nStudents List for Faculty Naveen Count: {len(student_rows)}")
    for r in student_rows[:5]:
        print(f"  Roll: {r['roll_no']}, Name: {r['name']}, Year: {r['year_of_study']}, Batch: {r['batch']}")

    # 3. Test month_register
    m_reg = month_register(
        faculty_username="Naveen",
        semester_id=5,
        subject_id=9,
        year=2026,
        month=8,
    )
    print(f"\nMonthly Register Roster Count: {len(m_reg['roster'])}")

if __name__ == "__main__":
    asyncio.run(verify())
