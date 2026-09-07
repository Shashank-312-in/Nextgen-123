import csv
import re
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk
from tkcalendar import DateEntry

from database import (ATTENDANCE_STATUSES, DEPARTMENTS, SUBJECTS, audit, auth,
                      change_password, connect, create_user, ensure_student_login, init_db,
                      reset_student_password, validate_student)
from sms_app.config import *
from sms_app.services.attendance_service import (
    absent_students_for_session, faculty_teaching_hours,
    recent_audit_logs, sessions_last_n_days,
)

class DashboardMixin:
    def dashboard(self):
        body=self.shell("Dashboard","Dashboard")
        ctk.CTkLabel(body,text=f"Welcome back, {self.username}.",text_color="#475467",font=("Segoe UI",14)).pack(anchor="w",pady=(0,14))
        if self.role=="STUDENT":
            return self._student_dashboard(body)
        return self._staff_dashboard(body)

    def _student_dashboard(self,body):
        with connect() as c:
            roll=self.student_roll_no
            s=c.execute("SELECT * FROM students WHERE roll_no=?",(roll,)).fetchone()
            if not s: return self.missing_student()
            present=c.execute("SELECT COUNT(*) n FROM attendance WHERE roll_no=? AND status IN ('Present','Late')",(roll,)).fetchone()["n"]
            total=c.execute("SELECT COUNT(*) n FROM attendance WHERE roll_no=?",(roll,)).fetchone()["n"]
            avg=c.execute("SELECT AVG((internal+external)/2) a FROM marks WHERE roll_no=?",(roll,)).fetchone()["a"] or 0
            stats_data=[("Department",s["department"],"🏫"),("Attendance",f"{present*100/total:.1f}%" if total else "No data","🎒"),("Average Marks",f"{avg:.1f}%","📋"),("Roll Number",s["roll_no"],"🪪")]
        stats=ctk.CTkFrame(body,fg_color="transparent"); stats.pack(fill="x")
        for i,data in enumerate(stats_data): stats.grid_columnconfigure(i,weight=1); self.card(stats,*data).grid(row=0,column=i,sticky="nsew",padx=(0 if i==0 else 6,6))

    def _staff_dashboard(self,body):
        # — Stat cards: totals stay on the legacy flat table (dept headcount, faculty
        # count) but "Present Today" now reflects real subject-wise sessions, not the
        # old single daily attendance row per student.
        with connect() as c:
            total=c.execute("SELECT COUNT(*) n FROM students WHERE active=1").fetchone()["n"]
            faculty=c.execute("SELECT COUNT(*) n FROM users WHERE role='FACULTY' AND active=1").fetchone()["n"]
            avg=c.execute("SELECT AVG((internal+external)/2) a FROM marks").fetchone()["a"] or 0
            present_today=c.execute("""SELECT COUNT(*) n FROM attendance_records r
                JOIN attendance_sessions a ON a.id=r.session_id
                WHERE a.attendance_date=? AND r.status='Present'""",(date.today().isoformat(),)).fetchone()["n"]
        stats_data=[("Total Students",total,"👤"),("Present Today (sessions)",present_today,"🎒"),("Total Faculty",faculty,"♟"),("Avg Marks (%)",f"{avg:.2f}","📋")]
        stats=ctk.CTkFrame(body,fg_color="transparent"); stats.pack(fill="x")
        for i,data in enumerate(stats_data): stats.grid_columnconfigure(i,weight=1); self.card(stats,*data).grid(row=0,column=i,sticky="nsew",padx=(0 if i==0 else 6,6))

        tabs=ctk.CTkTabview(body, fg_color="white", segmented_button_selected_color=BLUE,
                            segmented_button_selected_hover_color=BLUE)
        tabs.pack(fill="both",expand=True,pady=(18,0))
        tabs.add("15-Day Attendance")
        tabs.add("Faculty Hours")
        if self.role=="HOD":
            tabs.add("Audit Log")
        tabs.add("Recent Students")

        self._build_fifteen_day_tab(tabs.tab("15-Day Attendance"))
        self._build_faculty_hours_tab(tabs.tab("Faculty Hours"))
        if self.role=="HOD":
            self._build_audit_log_tab(tabs.tab("Audit Log"))
        self._build_recent_students_tab(tabs.tab("Recent Students"))

    def _build_fifteen_day_tab(self,parent):
        # — P0-P1 req 5: DATE -> hour/subject rows with absent count -> click -> roster.
        # Faculty see only their own sessions; HOD sees every session.
        wrap=ctk.CTkFrame(parent,fg_color="transparent"); wrap.pack(fill="both",expand=True,padx=4,pady=4)
        scroll=ctk.CTkScrollableFrame(wrap,fg_color="transparent")
        scroll.pack(fill="both",expand=True)
        grouped=sessions_last_n_days(15)
        if not grouped:
            ctk.CTkLabel(scroll,text="No attendance sessions in the last 15 days.",text_color=MUTED).pack(pady=30)
            return
        for day, sessions in grouped.items():
            if self.role=="FACULTY":
                sessions=[s for s in sessions if s["faculty_username"]==self.username]
                if not sessions: continue
            day_card=ctk.CTkFrame(scroll,fg_color="white",border_width=1,border_color="#e1e6ef",corner_radius=8)
            day_card.pack(fill="x",pady=(0,10))
            ctk.CTkLabel(day_card,text=day,font=("Segoe UI",14,"bold"),text_color=TEXT).pack(anchor="w",padx=16,pady=(12,4))
            for sess in sessions:
                row=ctk.CTkFrame(day_card,fg_color="#f7f9fc",corner_radius=6)
                row.pack(fill="x",padx=16,pady=4)
                label=f'{sess["session_type"].title()} · {sess["subject_name"]}' if sess["session_type"]=="LAB" else f'{sess["duration_hours"]}hr · {sess["subject_name"]}'
                ctk.CTkLabel(row,text=label,font=("Segoe UI",12,"bold"),text_color=TEXT).pack(side="left",padx=12,pady=10)
                ctk.CTkLabel(row,text=sess["faculty_name"] or sess["faculty_username"],text_color=MUTED,font=("Segoe UI",11)).pack(side="left",padx=(0,12))
                absent=sess["absent_count"]
                color=RED if absent>0 else GREEN
                ctk.CTkButton(row,text=f"{absent} Absent",width=100,height=28,fg_color=color,hover_color=color,
                              state="normal" if absent>0 else "disabled",
                              command=lambda sid=sess["id"],lbl=label,dy=day: self._show_absent_list(sid,lbl,dy)).pack(side="right",padx=12,pady=6)

    def _show_absent_list(self,session_id,label,day):
        rows=absent_students_for_session(session_id)
        win=ctk.CTkToplevel(self)
        win.title(f"Absent · {label}")
        win.geometry("420x480")
        win.transient(self)
        ctk.CTkLabel(win,text="ABSENT STUDENTS",font=("Segoe UI",16,"bold"),text_color=TEXT).pack(anchor="w",padx=18,pady=(16,2))
        ctk.CTkLabel(win,text=f"{day} · {label}",text_color=MUTED).pack(anchor="w",padx=18,pady=(0,10))
        tframe=ctk.CTkFrame(win,fg_color="white",border_width=1,border_color="#e1e6ef")
        tframe.pack(fill="both",expand=True,padx=18,pady=(0,18))
        t=self.tree(tframe,["S.No","Roll No","Student Name"],[60,140,200])
        for i,r in enumerate(rows,1):
            t.insert("","end",values=(i,r["roll_no"],r["name"]))

    def _build_faculty_hours_tab(self,parent):
        # — P0-P1 req 7: derived from attendance_sessions, never manually entered.
        wrap=ctk.CTkFrame(parent,fg_color="white",border_width=1,border_color="#e1e6ef")
        wrap.pack(fill="both",expand=True,padx=4,pady=4)
        rows=faculty_teaching_hours(self.username if self.role=="FACULTY" else None)
        t=self.tree(wrap,["Faculty","Sessions Taken","Teaching Hours","Classes","Labs"],[220,130,130,110,90])
        for r in rows:
            t.insert("","end",values=(r["full_name"] or r["faculty_username"],r["sessions_taken"],r["teaching_hours"],r["classes"],r["labs"]))
        if not rows:
            ctk.CTkLabel(wrap,text="No sessions recorded yet.",text_color=MUTED).pack(pady=20)

    def _build_audit_log_tab(self,parent):
        # — P0-P1 req 6: read-only surface over audit_logs; every write path in the
        # app already calls audit(), this just renders the trail for HOD.
        wrap=ctk.CTkFrame(parent,fg_color="white",border_width=1,border_color="#e1e6ef")
        wrap.pack(fill="both",expand=True,padx=4,pady=4)
        rows=recent_audit_logs(150)
        t=self.tree(wrap,["Time","User","Action","Entity","Details"],[150,110,130,150,320])
        for r in rows:
            t.insert("","end",values=(r["created_at"],r["username"],r["action"],r["entity"],r["details"] or ""))

    def _build_recent_students_tab(self,parent):
        with connect() as c:
            recent=c.execute("SELECT roll_no,name,department,email FROM students WHERE active=1 ORDER BY id DESC LIMIT 15").fetchall()
        wrap=ctk.CTkFrame(parent,fg_color="white",border_width=1,border_color="#e1e6ef")
        wrap.pack(fill="both",expand=True,padx=4,pady=4)
        t=self.tree(wrap,["Roll No","Name","Department","Email"],[110,180,120,240])
        for r in recent: t.insert("","end",values=tuple(r))

    def missing_student(self):
        body=self.shell("Account Error","Dashboard"); ctk.CTkLabel(body,text="This student account is not linked to an active student record. Contact the HOD.",text_color=RED,font=("Segoe UI",16,"bold")).pack(pady=80)

