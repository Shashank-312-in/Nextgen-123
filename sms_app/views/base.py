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

class BaseSMS(ctk.CTk):
    def __init__(self):
        super().__init__()
        init_db()
        self.title("CSD Student Management System")
        self.geometry("1360x780")
        self.minsize(1050, 650)
        self.configure(fg_color=BG)
        self.role = self.username = self.student_roll_no = None
        self.style = ttk.Style(); self.style.theme_use("clam")
        self.style.configure("Treeview", rowheight=34, background="white", fieldbackground="white", foreground=TEXT, borderwidth=0)
        self.style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", TEXT)])
        self.style.configure("Treeview.Heading", background="#f3f5f8", foreground=TEXT, relief="flat", font=("Segoe UI", 10, "bold"))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.login()

    def on_close(self):
        if self.username:
            with connect() as c: audit(c, self.username, "LOGOUT", "session", "Application closed")
        self.destroy()

    def clear(self):
        self.unbind("<Return>")
        for w in self.winfo_children(): w.destroy()

    def require(self, *roles):
        if self.role not in roles:
            messagebox.showerror("Access denied", "You do not have permission to perform this action.")
            return False
        return True

    def shell(self,title,active):
        self.clear()
        nav=ctk.CTkFrame(self,width=225,corner_radius=0,fg_color=NAV); nav.pack(side="left",fill="y"); nav.pack_propagate(False)
        ctk.CTkLabel(nav,text=f"{self.role}\nDashboard",font=("Segoe UI",18,"bold"),text_color="white",justify="left").pack(anchor="w",padx=24,pady=(25,22))
        if self.role=="STUDENT":
            items=[("⌂  Dashboard",self.dashboard),("♙  Profile",self.student_profile),("▣  Attendance",self.student_attendance),("▤  Marks",self.student_marks),("☑  Checklist",self.student_checklist)]
        else:
            items=[("⌂  Dashboard",self.dashboard),("♟  Students",self.students),("▣  Attendance",self.attendance),("▤  Marks",self.marks),("▧  Reports",self.reports)]
            if self.role=="HOD": items += [("♟  Faculty",self.faculty),("⚙  Settings",self.settings)]
        for label,fn in items:
            key=label.split("  ")[-1]
            ctk.CTkButton(nav,text=label,anchor="w",height=45,corner_radius=6,fg_color=NAV2 if key==active else "transparent",hover_color=NAV2,font=("Segoe UI",13),command=fn).pack(fill="x",padx=10,pady=2)
        ctk.CTkButton(nav,text="↪  Logout",anchor="w",height=45,fg_color="transparent",hover_color=NAV2,command=self.logout).pack(side="bottom",fill="x",padx=10,pady=18)
        main=ctk.CTkFrame(self,corner_radius=0,fg_color=BG); main.pack(fill="both",expand=True)
        top=ctk.CTkFrame(main,fg_color="transparent"); top.pack(fill="x",padx=28,pady=(22,10))
        ctk.CTkLabel(top,text=title,font=("Segoe UI",27,"bold"),text_color=TEXT).pack(side="left")
        ctk.CTkLabel(top,text=self.username or "",font=("Segoe UI",12),text_color=MUTED).pack(side="right")
        body=ctk.CTkFrame(main,fg_color="transparent"); body.pack(fill="both",expand=True,padx=28,pady=(0,25))
        return body

    def tree(self,parent,cols,widths):
        wrap=ctk.CTkFrame(parent,fg_color="white"); wrap.pack(fill="both",expand=True,padx=14,pady=(0,14))
        t=ttk.Treeview(wrap,columns=cols,show="headings",selectmode="browse")
        center_cols={"ID","S.No","Role","Student Roll","Status","Created","Department","Present/Late","Absent","Sessions","Attendance %","Marks %","Internal","External"}
        for col,w in zip(cols,widths):
            anchor="center" if col in center_cols else "w"
            t.heading(col,text=col,anchor=anchor)
            t.column(col,width=w,anchor=anchor,stretch=True)
        y=ttk.Scrollbar(wrap,orient="vertical",command=t.yview); x=ttk.Scrollbar(wrap,orient="horizontal",command=t.xview); t.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        t.grid(row=0,column=0,sticky="nsew"); y.grid(row=0,column=1,sticky="ns"); x.grid(row=1,column=0,sticky="ew"); wrap.grid_rowconfigure(0,weight=1); wrap.grid_columnconfigure(0,weight=1)
        return t

    def card(self,parent,title,value,icon):
        f=ctk.CTkFrame(parent,fg_color="white",corner_radius=8,border_width=1,border_color="#e1e6ef")
        ctk.CTkLabel(f,text=icon,font=("Segoe UI Emoji",25)).pack(side="left",padx=18)
        x=ctk.CTkFrame(f,fg_color="transparent"); x.pack(side="left",pady=17)
        ctk.CTkLabel(x,text=title,text_color=MUTED,font=("Segoe UI",11)).pack(anchor="w"); ctk.CTkLabel(x,text=str(value),text_color=TEXT,font=("Segoe UI",22,"bold")).pack(anchor="w")
        return f

