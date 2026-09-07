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

class StudentMixin:
    def student_row(self):
        if not self.student_roll_no:return None
        with connect() as c:return c.execute("SELECT * FROM students WHERE roll_no=? AND active=1",(self.student_roll_no,)).fetchone()

    def student_profile(self):
        if self.role!="STUDENT":return self.dashboard()
        r=self.student_row()
        if not r:return self.missing_student()
        body=self.shell("My Profile","Profile"); card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="x",pady=(0,14))
        ctk.CTkLabel(card,text="👤",font=("Segoe UI Emoji",65)).pack(side="left",padx=35,pady=35)
        info=ctk.CTkFrame(card,fg_color="transparent"); info.pack(side="left",fill="both",expand=True,pady=28); ctk.CTkLabel(info,text=r["name"],font=("Segoe UI",23,"bold"),text_color=TEXT).pack(anchor="w")
        for value in [r["roll_no"],r["department"],r["email"],r["phone"]]:ctk.CTkLabel(info,text=value or "—",font=("Segoe UI",13),text_color="#475467").pack(anchor="w",pady=3)
        more=ctk.CTkFrame(card,fg_color="transparent"); more.pack(side="left",fill="both",expand=True,pady=28)
        for label,value in [("Father Name",r["father_name"]),("Date of Birth",r["dob"]),("Category / Gender",f"{r['category'] or '—'} / {r['gender'] or '—'}"),("Seat Category",r["seat_category"]),("Address",r["address"])]:ctk.CTkLabel(more,text=label,font=("Segoe UI",11,"bold"),text_color=MUTED).pack(anchor="w"); ctk.CTkLabel(more,text=value or "—",font=("Segoe UI",13),text_color=TEXT).pack(anchor="w",pady=(1,8))
        ctk.CTkButton(body,text="Change My Password",width=180,command=self.password_dialog).pack(anchor="w")

    def student_attendance(self):
        if self.role!="STUDENT":return self.attendance()
        r=self.student_row()
        if not r:return self.missing_student()
        body=self.shell("My Attendance","Attendance")
        with connect() as c:rows=c.execute("SELECT date,department,status,marked_by FROM attendance WHERE roll_no=? ORDER BY date DESC",(r["roll_no"],)).fetchall()
        p=sum(x["status"] in ("Present","Late") for x in rows); pct=p*100/len(rows) if rows else 0
        ctk.CTkLabel(body,text=f"Attendance: {pct:.2f}% across {len(rows)} recorded sessions",font=("Segoe UI",15,"bold"),text_color=TEXT).pack(anchor="w",pady=(0,10))
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True); tree=self.tree(card,["Date","Department","Status","Marked By"],[200,180,180,180])
        for x in rows:tree.insert("","end",values=tuple(x))
        ctk.CTkLabel(body,text="Read only — attendance is managed by HOD/Faculty.",text_color=MUTED).pack(anchor="w",pady=10)

    def student_marks(self):
        if self.role!="STUDENT":return self.marks()
        r=self.student_row()
        if not r:return self.missing_student()
        body=self.shell("My Marks","Marks")
        with connect() as c:rows=c.execute("SELECT subject,internal,external FROM marks WHERE roll_no=? ORDER BY subject",(r["roll_no"],)).fetchall()
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True); tree=self.tree(card,["Subject","Internal (100)","External (100)","Total (200)","Percentage"],[270,150,150,150,150])
        total=0
        for x in rows:t=x["internal"]+x["external"]; total+=t; tree.insert("","end",values=(x["subject"],x["internal"],x["external"],t,f"{t/2:.2f}%"))
        ctk.CTkLabel(body,text=f"Total Marks: {total:g} / {len(rows)*200}     Overall Percentage: {(total/(len(rows)*2) if rows else 0):.2f}%",font=("Segoe UI",14,"bold"),text_color=TEXT).pack(anchor="e",pady=12)

    def student_checklist(self):
        if self.role!="STUDENT":return self.dashboard()
        r=self.student_row()
        if not r:return self.missing_student()
        body=self.shell("My Checklist","Checklist")
        with connect() as c:rows=c.execute("SELECT item,status FROM checklist WHERE roll_no=? ORDER BY id",(r["roll_no"],)).fetchall()
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="x"); ctk.CTkLabel(card,text="Student Checklist",font=("Segoe UI",20,"bold"),text_color=TEXT).pack(anchor="w",padx=24,pady=(22,12))
        for x in rows:
            row=ctk.CTkFrame(card,fg_color="#f8fafc",corner_radius=6); row.pack(fill="x",padx=24,pady=5); ctk.CTkLabel(row,text=x["item"],text_color=TEXT).pack(side="left",padx=15,pady=12); ctk.CTkLabel(row,text=x["status"],text_color=GREEN if x["status"] in ("Complete","Available") else "#d97706",font=("Segoe UI",12,"bold")).pack(side="right",padx=15)

