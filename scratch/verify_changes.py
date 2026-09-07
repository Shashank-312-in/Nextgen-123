import os
import sys
sys.path.insert(0, os.path.abspath("."))
from database import connect

def test_roll_no_ordering():
    with connect() as c:
        students = c.execute("SELECT roll_no, name, current_semester_id FROM students WHERE department='CSD' ORDER BY UPPER(roll_no) ASC").fetchall()
        print(f"Total students in DB: {len(students)}")
        print("First 5 students:")
        for s in students[:5]:
            print(f"  {s['roll_no']}: {s['name']} (Sem {s['current_semester_id']})")
        print("Last 5 students:")
        for s in students[-5:]:
            print(f"  {s['roll_no']}: {s['name']} (Sem {s['current_semester_id']})")

        # Verify ordering is strictly ascending
        roll_nos = [s['roll_no'].upper() for s in students]
        is_sorted = roll_nos == sorted(roll_nos)
        print(f"Is roll_no strictly sorted ascending? {is_sorted}")
        assert is_sorted, "Students are not sorted roll_no wise!"

def test_api_routes():
    from fastapi.testclient import TestClient
    from api.app import app
    from api.auth_token import make_access_token

    client = TestClient(app)

    # Test Admin
    admin_token = make_access_token(username="admin", role="ADMIN", student_roll_no=None)
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = client.get("/api/students", headers=headers)
    assert resp.status_code == 200, f"Admin students list failed: {resp.text}"
    data = resp.json()["data"]
    print(f"API /api/students returned {len(data)} rows for Admin")
    api_rolls = [r["roll_no"].upper() for r in data]
    assert api_rolls == sorted(api_rolls), "API rows not sorted by roll_no!"
    print("Admin API rows strictly roll_no sorted: PASS")

    # Test Semester Endpoint
    resp_sem = client.get("/api/students/semesters", headers=headers)
    assert resp_sem.status_code == 200, f"Semesters endpoint failed: {resp_sem.text}"
    sem_data = resp_sem.json()["data"]
    print(f"API /api/students/semesters returned {len(sem_data)} semesters: PASS")

    # Test HOD
    hod_token = make_access_token(username="Srikanth", role="HOD", student_roll_no=None)
    headers_hod = {"Authorization": f"Bearer {hod_token}"}
    resp_hod = client.get("/api/students", headers=headers_hod)
    assert resp_hod.status_code == 200
    data_hod = resp_hod.json()["data"]
    hod_rolls = [r["roll_no"].upper() for r in data_hod]
    assert hod_rolls == sorted(hod_rolls), "HOD rows not sorted by roll_no!"
    print("HOD API rows strictly roll_no sorted: PASS")

    # Test Faculty
    fac_token = make_access_token(username="faculty_test", role="FACULTY", student_roll_no=None)
    headers_fac = {"Authorization": f"Bearer {fac_token}"}
    resp_fac = client.get("/api/students", headers=headers_fac)
    assert resp_fac.status_code == 200
    data_fac = resp_fac.json()["data"]
    fac_rolls = [r["roll_no"].upper() for r in data_fac]
    assert fac_rolls == sorted(fac_rolls), "Faculty rows not sorted by roll_no!"
    print("Faculty API rows strictly roll_no sorted: PASS")

    # Test Student (Access Denied)
    stu_token = make_access_token(username="stu_test", role="STUDENT", student_roll_no="24BT1A6701")
    resp_stu = client.get("/api/students", headers={"Authorization": f"Bearer {stu_token}"})
    assert resp_stu.status_code == 403, "Student should be denied /api/students"
    print("Student role blocked from students list: PASS")

    print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_roll_no_ordering()
    test_api_routes()
