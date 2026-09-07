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

class StudentsMixin:
    def students(self):
        if self.role=="STUDENT": return self.student_profile()
        body=self.shell("Students","Students")
        tools=ctk.CTkFrame(body,fg_color="transparent"); tools.pack(fill="x",pady=(0,14))
        search=ctk.CTkEntry(tools,width=360,height=40,placeholder_text="Search CSD student by name, roll no, email or phone..."); search.pack(side="left")
        status=ctk.CTkComboBox(tools,values=["Active","Inactive","All"],width=120,state="readonly"); status.set("Active"); status.pack(side="left",padx=8)
        if self.role=="HOD": ctk.CTkButton(tools,text="+ Add Student",height=40,command=lambda:self.student_form()).pack(side="right")
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True)
        tree=self.tree(card,["ID","Roll No","Name","Department","Email","Phone","Status"],[55,100,160,110,220,130,90])
        def load(*_):
            tree.delete(*tree.get_children()); q=f"%{search.get().strip()}%"; filt=status.get()
            sql="SELECT * FROM students WHERE department='CSD' AND (name LIKE ? OR roll_no LIKE ? OR email LIKE ? OR phone LIKE ?)"; args=[q,q,q,q]
            if filt!="All": sql+=" AND active=?"; args.append(1 if filt=="Active" else 0)
            sql+=" ORDER BY UPPER(roll_no) ASC, name ASC"
            with connect() as c: rows=c.execute(sql,args).fetchall()
            for r in rows: tree.insert("","end",values=(r["id"],r["roll_no"],r["name"],r["department"],r["email"] or "",r["phone"] or "","Active" if r["active"] else "Inactive"))
        search.bind("<KeyRelease>",load); status.configure(command=lambda _v:load())
        if self.role=="HOD":
            actions=ctk.CTkFrame(body,fg_color="transparent"); actions.pack(fill="x",pady=10)
            ctk.CTkButton(actions,text="Edit selected",command=lambda:self.edit_selected_student(tree)).pack(side="left",padx=(0,8))
            ctk.CTkButton(actions,text="Activate / Deactivate",fg_color="#d97706",command=lambda:self.toggle_student(tree,load)).pack(side="left")
        load()

    def edit_selected_student(self,tree):
        sel=tree.selection()
        if not sel: return messagebox.showwarning("Select student","Select a student first")
        self.student_form(int(tree.item(sel[0])["values"][0]))

    def student_form(self,student_id=None):
        if not self.require("HOD"): return
        row=None
        if student_id:
            with connect() as c: row=c.execute("SELECT * FROM students WHERE id=? AND department='CSD'",(student_id,)).fetchone()
        body=self.shell("Edit CSD Student" if row else "Add CSD Student","Students")
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True)
        fields={}; grid=ctk.CTkScrollableFrame(card,fg_color="transparent"); grid.pack(fill="both",expand=True,padx=24,pady=20)
        specs=[("Roll Number","roll_no"),("Full Name","name"),("Father Name","father_name"),("Department","department"),("Email","email"),("Phone","phone"),("Date of Birth (YYYY-MM-DD)","dob"),("Category","category"),("Gender","gender"),("Seat Category","seat_category"),("Certificates Submitted","certificates_submitted"),("Certificates Due","certificates_due"),("Consultant Name","consultant_name"),("Address","address")]
        for i,(lab,key) in enumerate(specs):
            box=ctk.CTkFrame(grid,fg_color="transparent"); box.grid(row=i//2,column=i%2,sticky="ew",padx=8,pady=6); grid.grid_columnconfigure(i%2,weight=1); ctk.CTkLabel(box,text=lab,text_color=TEXT).pack(anchor="w")
            if key=="department": w=ctk.CTkComboBox(box,values=["CSD"],height=40,state="readonly"); w.set("CSD")
            else: w=ctk.CTkEntry(box,height=40); w.insert(0,(row[key] or "") if row else "")
            w.pack(fill="x"); fields[key]=w
        def save():
            data={k:v.get().strip() for k,v in fields.items()}
            try:
                validate_student(data)
                if data["dob"]: datetime.strptime(data["dob"],"%Y-%m-%d")
                keys=["roll_no","name","department","email","phone","dob","address","father_name","category","gender","seat_category","certificates_submitted","certificates_due","consultant_name"]
                with connect() as c:
                    if row:
                        c.execute("""UPDATE students SET roll_no=?,name=?,department=?,email=NULLIF(?,''),phone=?,dob=?,address=?,father_name=?,category=?,gender=?,seat_category=?,certificates_submitted=?,certificates_due=?,consultant_name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",(*[data[k] for k in keys],student_id)); audit(c,self.username,"UPDATE","student",data["roll_no"])
                    else:
                        c.execute("""INSERT INTO students(roll_no,name,department,email,phone,dob,address,father_name,category,gender,seat_category,certificates_submitted,certificates_due,consultant_name) VALUES(?,?,?,NULLIF(?,''),?,?,?,?,?,?,?,?,?,?)""",tuple(data[k] for k in keys)); audit(c,self.username,"CREATE","student",data["roll_no"])
                        for item,st in [("Personal details","Complete"),("Documents","Pending"),("ID card","Pending"),("Fees","Pending"),("Attendance records","Available"),("Marks records","Available")]: c.execute("INSERT INTO checklist(roll_no,item,status) VALUES(?,?,?)",(data["roll_no"],item,st))
                if not row:
                    username,password=ensure_student_login(data["roll_no"],self.username)
                    messagebox.showinfo("Student created",f"Student and dashboard login created.\n\nUsername: {username}\nTemporary password: {password}")
                else: messagebox.showinfo("Saved","Student details updated successfully")
                self.students()
            except (ValueError,IntegrityError) as e: messagebox.showerror("Cannot save",str(e))
        buttons=ctk.CTkFrame(card,fg_color="transparent"); buttons.pack(pady=(0,22)); ctk.CTkButton(buttons,text="Save Student",width=150,command=save).pack(side="left",padx=6); ctk.CTkButton(buttons,text="Cancel",width=140,fg_color="#98a2b3",command=self.students).pack(side="left",padx=6)

    def toggle_student(self,tree,reload):
        sel=tree.selection()
        if not sel: return messagebox.showwarning("Select student","Select a student first")
        vals=tree.item(sel[0])["values"]; new=0 if vals[6]=="Active" else 1
        if not messagebox.askyesno("Confirm",f"{'Activate' if new else 'Deactivate'} {vals[2]}?"): return
        with connect() as c: c.execute("UPDATE students SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(new,vals[0])); audit(c,self.username,"STATUS","student",f"{vals[1]} -> {new}")

