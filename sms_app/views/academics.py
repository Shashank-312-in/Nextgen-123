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

class AcademicsMixin:
    def marks(self):
        if self.role=="STUDENT": return self.student_marks()
        body=self.shell("Marks Entry","Marks")
        filters=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); filters.pack(fill="x",pady=(0,14))
        dept=ctk.CTkComboBox(filters,values=list(DEPARTMENTS),width=160,state="readonly"); dept.set("CSD"); dept.pack(side="left",padx=16,pady=15)
        subject=ctk.CTkComboBox(filters,values=list(SUBJECTS),width=240,state="readonly"); subject.set(SUBJECTS[0]); subject.pack(side="left",padx=6)
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True)
        tree=self.tree(card,["ID","Roll No","Name","Internal","External"],[70,150,260,140,140])
        def load():
            tree.delete(*tree.get_children())
            with connect() as c:
                for r in c.execute("SELECT * FROM students WHERE department=? AND active=1",(dept.get(),)).fetchall():
                    m=c.execute("SELECT * FROM marks WHERE roll_no=? AND subject=?",(r["roll_no"],subject.get())).fetchone(); tree.insert("","end",values=(r["id"],r["roll_no"],r["name"],m["internal"] if m else 0,m["external"] if m else 0))
        def edit(_e=None):
            sel=tree.selection()
            if not sel:return
            item=sel[0]; v=tree.item(item)["values"]
            internal=simpledialog.askfloat("Internal marks",f"Internal marks for {v[2]} (0-100)",initialvalue=float(v[3]),minvalue=0,maxvalue=100,parent=self)
            if internal is None:return
            external=simpledialog.askfloat("External marks",f"External marks for {v[2]} (0-100)",initialvalue=float(v[4]),minvalue=0,maxvalue=100,parent=self)
            if external is None:return
            tree.item(item,values=(*v[:3],internal,external))
        def save():
            with connect() as c:
                for item in tree.get_children():
                    v=tree.item(item)["values"]; internal=float(v[3]); external=float(v[4])
                    if not (0<=internal<=100 and 0<=external<=100): return messagebox.showerror("Invalid marks",f"Marks for {v[2]} must be between 0 and 100")
                    c.execute("INSERT INTO marks(roll_no,subject,internal,external,entered_by) VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE internal=VALUES(internal),external=VALUES(external),entered_by=VALUES(entered_by),updated_at=CURRENT_TIMESTAMP",(v[1],subject.get(),internal,external,self.username))
                audit(c,self.username,"UPSERT","marks",f"{subject.get()} {dept.get()} ({len(tree.get_children())} records)")
            messagebox.showinfo("Saved","Marks saved")
        ctk.CTkButton(filters,text="Load Students",command=load).pack(side="left",padx=12); tree.bind("<Double-1>",edit)
        ctk.CTkLabel(body,text="Double-click a student to enter marks.",text_color=MUTED).pack(anchor="w",pady=(8,0)); ctk.CTkButton(body,text="Save Marks",width=160,height=42,command=save).pack(anchor="w",pady=10); load()

    def reports(self):
        if self.role=="STUDENT": return self.dashboard()
        body=self.shell("Reports","Reports")
        tools=ctk.CTkFrame(body,fg_color="transparent"); tools.pack(fill="x",pady=(0,10))
        dept=ctk.CTkComboBox(tools,values=["All",*DEPARTMENTS],width=150,state="readonly"); dept.set("All"); dept.pack(side="left")
        card=ctk.CTkFrame(body,fg_color="white",border_width=1,border_color="#e1e6ef"); card.pack(fill="both",expand=True)
        tree=self.tree(card,["Roll No","Name","Department","Present/Late","Absent","Sessions","Attendance %","Marks %"],[120,190,110,120,90,90,120,100])
        def load(*_):
            tree.delete(*tree.get_children()); where="WHERE s.active=1"; args=[]
            if dept.get()!="All": where+=" AND s.department=?"; args=[dept.get()]
            with connect() as c:
                rows=c.execute(f"""SELECT s.roll_no,s.name,s.department,
                COALESCE(SUM(CASE WHEN a.status IN ('Present','Late') THEN 1 ELSE 0 END),0) p,
                COALESCE(SUM(CASE WHEN a.status='Absent' THEN 1 ELSE 0 END),0) ab,COUNT(a.id) n,
                (SELECT AVG((m.internal+m.external)/2) FROM marks m WHERE m.roll_no=s.roll_no) marks
                FROM students s LEFT JOIN attendance a ON s.roll_no=a.roll_no {where} GROUP BY s.roll_no ORDER BY s.roll_no""",args).fetchall()
            for r in rows: tree.insert("","end",values=(r["roll_no"],r["name"],r["department"],r["p"],r["ab"],r["n"],f"{r['p']*100/r['n']:.2f}%" if r["n"] else "No data",f"{(r['marks'] or 0):.2f}%"))
        def export():
            path=filedialog.asksaveasfilename(title="Export report",defaultextension=".csv",filetypes=[("CSV files","*.csv")])
            if not path:return
            with open(path,"w",newline="",encoding="utf-8-sig") as f:
                w=csv.writer(f); w.writerow([tree.heading(c)["text"] for c in tree["columns"]]); [w.writerow(tree.item(i)["values"]) for i in tree.get_children()]
            with connect() as c:audit(c,self.username,"EXPORT","report",Path(path).name)
            messagebox.showinfo("Exported",f"Report saved to:\n{path}")
        dept.configure(command=load); ctk.CTkButton(tools,text="Export CSV",command=export).pack(side="right"); load()

