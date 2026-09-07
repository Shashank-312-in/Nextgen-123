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

class AuthMixin:
    def login(self):
        self.role = self.username = self.student_roll_no = None
        self.clear()
        left=ctk.CTkFrame(self,width=390,corner_radius=0,fg_color=NAV); left.pack(side="left",fill="y"); left.pack_propagate(False)
        ctk.CTkLabel(left,text="🎓",font=("Segoe UI Emoji",80),text_color="white").pack(pady=(150,25))
        ctk.CTkLabel(left,text="CSD Student\nManagement\nSystem",font=("Segoe UI",32,"bold"),text_color="white").pack()
        area=ctk.CTkFrame(self,fg_color=BG,corner_radius=0); area.pack(fill="both",expand=True)
        card=ctk.CTkFrame(area,width=430,height=570,fg_color="white",corner_radius=12,border_width=1,border_color="#dfe4ec"); card.place(relx=.5,rely=.5,anchor="center"); card.pack_propagate(False)
        ctk.CTkLabel(card,text="Login",font=("Segoe UI",29,"bold"),text_color=TEXT).pack(pady=(55,4))
        ctk.CTkLabel(card,text="Sign in to continue",font=("Segoe UI",13),text_color=MUTED).pack(pady=(0,25))
        form=ctk.CTkFrame(card,fg_color="transparent"); form.pack(fill="x",padx=42)
        ctk.CTkLabel(form,text="Role",anchor="w",text_color=TEXT).pack(fill="x")
        role=ctk.CTkComboBox(form,values=["HOD","FACULTY","STUDENT"],height=42,state="readonly"); role.set("HOD"); role.pack(fill="x",pady=(5,14))
        ctk.CTkLabel(form,text="Username",anchor="w",text_color=TEXT).pack(fill="x")
        user=ctk.CTkEntry(form,height=42,placeholder_text="Enter username"); user.pack(fill="x",pady=(5,14))
        ctk.CTkLabel(form,text="Password",anchor="w",text_color=TEXT).pack(fill="x")
        pwd=ctk.CTkEntry(form,height=42,show="•",placeholder_text="Enter password"); pwd.pack(fill="x",pady=(5,12))
        show=ctk.CTkCheckBox(form,text="Show password",command=lambda: pwd.configure(show="" if show.get() else "•")); show.pack(anchor="w",pady=5)
        def go():
            if not user.get().strip() or not pwd.get(): return messagebox.showerror("Login failed","Enter username and password")
            row=auth(user.get(),pwd.get(),role.get())
            if not row: return messagebox.showerror("Login failed","Invalid credentials, role, or inactive account")
            self.role=row["role"]; self.username=row["username"]; self.student_roll_no=row["student_roll_no"]
            with connect() as c: audit(c,self.username,"LOGIN","session",self.role)
            self.dashboard()
        ctk.CTkButton(form,text="Login",height=45,font=("Segoe UI",14,"bold"),command=go).pack(fill="x",pady=25)
        user.focus(); self.bind("<Return>",lambda _e:go())

    def logout(self):
        with connect() as c: audit(c,self.username,"LOGOUT","session","")
        self.login()

