import csv
import re
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk
from tkcalendar import DateEntry

from database import (ATTENDANCE_STATUSES, DEPARTMENTS, SUBJECTS, audit, auth,
                      change_password, connect, create_user, ensure_student_login, init_db,
                      reset_student_password, validate_student, IntegrityError)
from sms_app.config import *

class AdminMixin:
    def faculty(self):
        if not self.require("HOD"): return
        body=self.shell("Faculty & Accounts","Faculty")
        tools=ctk.CTkFrame(body,fg_color="transparent"); tools.pack(fill="x",pady=(0,10)); ctk.CTkButton(tools,text="+ Create Account",command=self.create_account_dialog).pack(side="right")
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True)
        tree=self.tree(card,["ID","Username","Full Name","Role","Student Roll","Status","Created"],[60,150,190,110,130,90,160])
        def load():
            tree.delete(*tree.get_children())
            with connect() as c: rows=c.execute("SELECT * FROM users ORDER BY role,username").fetchall()
            for r in rows: tree.insert("","end",values=(r["id"],r["username"],r["full_name"] or "",r["role"],r["student_roll_no"] or "","Active" if r["active"] else "Inactive",r["created_at"] or ""))
        def toggle():
            sel=tree.selection()
            if not sel:return messagebox.showwarning("Select account","Select an account first")
            v=tree.item(sel[0])["values"]
            if v[1]==self.username:return messagebox.showerror("Not allowed","You cannot deactivate your own logged-in account")
            new=0 if v[5]=="Active" else 1
            with connect() as c:c.execute("UPDATE users SET active=?, auth_version=auth_version+1 WHERE id=?",(new,v[0])); audit(c,self.username,"STATUS","user",f"{v[1]} -> {new}")
            load()
        actions=ctk.CTkFrame(body,fg_color="transparent"); actions.pack(fill="x",pady=10)
        ctk.CTkButton(actions,text="Activate / Deactivate selected",fg_color="#d97706",command=toggle).pack(side="left",padx=(0,8))
        def reset_selected():
            sel=tree.selection()
            if not sel:return messagebox.showwarning("Select account","Select a student account first")
            v=tree.item(sel[0])["values"]
            if v[3]!="STUDENT" or not v[4]:return messagebox.showerror("Student account required","Select a linked STUDENT account")
            try:
                username,password=reset_student_password(str(v[4]),self.username)
                messagebox.showinfo("Password reset",f"Username: {username}\nTemporary password: {password}")
            except ValueError as e:messagebox.showerror("Cannot reset",str(e))
        ctk.CTkButton(actions,text="Reset Student Password",command=reset_selected).pack(side="left")
        load()

    def create_account_dialog(self):
        if not self.require("HOD"):return
        win=ctk.CTkToplevel(self); win.title("Create account"); win.geometry("460x520"); win.transient(self); win.grab_set()
        fields={}
        for label,key,show in [("Username","username",None),("Full name","full_name",None),("Password","password","•")]:
            ctk.CTkLabel(win,text=label).pack(anchor="w",padx=35,pady=(15,3)); e=ctk.CTkEntry(win,height=40,show=show or ""); e.pack(fill="x",padx=35); fields[key]=e
        ctk.CTkLabel(win,text="Role").pack(anchor="w",padx=35,pady=(15,3)); role=ctk.CTkComboBox(win,values=["FACULTY","STUDENT"],state="readonly"); role.set("FACULTY"); role.pack(fill="x",padx=35)
        ctk.CTkLabel(win,text="Student roll number (required for STUDENT)").pack(anchor="w",padx=35,pady=(15,3)); roll=ctk.CTkEntry(win,height=40); roll.pack(fill="x",padx=35)
        def save():
            try:create_user(fields["username"].get(),fields["password"].get(),role.get(),fields["full_name"].get(),roll.get().strip() or None,self.username); messagebox.showinfo("Created","Account created"); win.destroy(); self.faculty()
            except (ValueError,IntegrityError) as e:messagebox.showerror("Cannot create account",str(e),parent=win)
        ctk.CTkButton(win,text="Create Account",height=42,command=save).pack(fill="x",padx=35,pady=28)

    def settings(self):
        if not self.require("HOD"):return
        body=self.shell("Settings","Settings")
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="x",pady=(0,14))
        with connect() as c: current={r["key"]:r["value"] for r in c.execute("SELECT * FROM settings")}
        fields={}
        for label,key in [("Institution name","institution_name"),("Academic year","academic_year"),("Low attendance threshold (%)","attendance_threshold")]:
            row=ctk.CTkFrame(card,fg_color="transparent"); row.pack(fill="x",padx=25,pady=10); ctk.CTkLabel(row,text=label,width=260,anchor="w",text_color=TEXT).pack(side="left"); e=ctk.CTkEntry(row,height=38); e.insert(0,current.get(key,"")); e.pack(side="left",fill="x",expand=True); fields[key]=e
        def save_settings():
            try:
                threshold=float(fields["attendance_threshold"].get()); assert 0<=threshold<=100
            except (ValueError,AssertionError):return messagebox.showerror("Invalid threshold","Attendance threshold must be between 0 and 100")
            with connect() as c:
                for k,e in fields.items():c.execute("INSERT INTO settings(`key`,`value`) VALUES(%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",(k,e.get().strip()))
                audit(c,self.username,"UPDATE","settings","General settings")
            messagebox.showinfo("Saved","Settings saved")
        ctk.CTkButton(card,text="Save Settings",command=save_settings).pack(anchor="e",padx=25,pady=(5,20))
        security=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); security.pack(fill="x")
        ctk.CTkLabel(security,text="Security",font=("Segoe UI",17,"bold"),text_color=TEXT).pack(anchor="w",padx=25,pady=(20,5)); ctk.CTkButton(security,text="Change My Password",command=self.password_dialog).pack(anchor="w",padx=25,pady=(5,20))

    def password_dialog(self):
        old=simpledialog.askstring("Change password","Current password",show="•",parent=self)
        if old is None:return
        new=simpledialog.askstring("Change password","New password (minimum 8 characters)",show="•",parent=self)
        if new is None:return
        confirm=simpledialog.askstring("Change password","Confirm new password",show="•",parent=self)
        if new!=confirm:return messagebox.showerror("Mismatch","New passwords do not match")
        try:change_password(self.username,old,new); messagebox.showinfo("Changed","Password changed successfully")
        except ValueError as e:messagebox.showerror("Cannot change password",str(e))

