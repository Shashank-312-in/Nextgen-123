import database

def main():
    with database.connect() as c:
        print("=========================================================================")
        print("                   STUDENT ATTENDANCE SUMMARY (DATABASE)                 ")
        print("=========================================================================")
        rows = c.execute("""
            SELECT r.roll_no, s.name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN r.status = 'Present' THEN 1 ELSE 0 END) AS present,
                   ROUND((SUM(CASE WHEN r.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(*)), 2) AS pct
            FROM attendance_records r
            JOIN students s ON s.roll_no = r.roll_no
            GROUP BY r.roll_no, s.name
            ORDER BY r.roll_no
        """).fetchall()

        print(f"{'ROLL NO':<12} {'STUDENT NAME':<20} {'SESSIONS':<10} {'PRESENT':<10} {'ATTENDANCE %':<12}")
        print("-" * 65)
        for r in rows:
            print(f"{r['roll_no']:<12} {r['name']:<20} {r['total']:<10} {r['present']:<10} {r['pct']}%")

        print("\n=========================================================================")
        print("                 SUBJECT-WISE ATTENDANCE BREAKDOWN                       ")
        print("=========================================================================")
        sub_rows = c.execute("""
            SELECT r.roll_no, s.name AS student_name, subj.code AS subject_code, subj.name AS subject_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN r.status = 'Present' THEN 1 ELSE 0 END) AS present,
                   ROUND((SUM(CASE WHEN r.status = 'Present' THEN 1 ELSE 0 END) * 100.0 / COUNT(*)), 2) AS pct
            FROM attendance_records r
            JOIN students s ON s.roll_no = r.roll_no
            JOIN attendance_sessions sess ON sess.id = r.session_id
            JOIN subjects subj ON subj.id = sess.subject_id
            GROUP BY r.roll_no, s.name, subj.code, subj.name
            ORDER BY r.roll_no, subj.code
        """).fetchall()

        print(f"{'ROLL NO':<12} {'SUBJECT CODE':<14} {'SUBJECT NAME':<22} {'PRESENT/TOTAL':<15} {'ATTENDANCE %':<12}")
        print("-" * 75)
        for r in sub_rows:
            ratio = f"{r['present']}/{r['total']}"
            print(f"{r['roll_no']:<12} {r['subject_code']:<14} {r['subject_name']:<22} {ratio:<15} {r['pct']}%")
        print("=========================================================================\n")

if __name__ == "__main__":
    main()
