import re
from datetime import date
from tkinter import messagebox

import customtkinter as ctk
from tkcalendar import DateEntry

from database import connect
from sms_app.config import *
from sms_app.services.attendance_service import (
    LAB_HOURS, get_or_create_session, list_semesters, list_subjects,
    load_register, save_register, session_details, session_is_editable,
    subject_details, validate_session_payload,
)


class AttendanceMixin:
    """Single attendance entry flow: Setup -> Register -> Confirm -> Save."""

    def attendance(self):
        if self.role == "STUDENT":
            return self.student_attendance()
        return self.attendance_setup()

    def attendance_setup(self, preset=None):
        if not self.require("HOD", "FACULTY"):
            return
        body = self.shell("Attendance", "Attendance")
        preset = preset or {}

        card = ctk.CTkFrame(body, width=620, fg_color="white", border_width=1,
                            border_color="#e1e6ef", corner_radius=8)
        card.pack(anchor="n", pady=(24, 0))
        card.pack_propagate(False)
        card.configure(height=520)

        ctk.CTkLabel(card, text="Open attendance register", font=("Segoe UI", 21, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=30, pady=(28, 4))
        ctk.CTkLabel(card, text="Choose the class session first. The register opens next.",
                     font=("Segoe UI", 12), text_color=MUTED).pack(anchor="w", padx=30, pady=(0, 22))

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=30)
        form.grid_columnconfigure((0, 1), weight=1)

        def label(text, row, col):
            ctk.CTkLabel(form, text=text, font=("Segoe UI", 11, "bold"), text_color=TEXT).grid(
                row=row, column=col, sticky="w", padx=(0, 12), pady=(0, 6))

        label("Date", 0, 0)
        label("Semester", 0, 1)
        datee = DateEntry(form, width=22, date_pattern="yyyy-mm-dd", state="readonly",
                          maxdate=date.today(), font=("Segoe UI", 12))
        datee.grid(row=1, column=0, sticky="ew", padx=(0, 12), ipady=7)
        datee.set_date(preset.get("date", date.today()))
        datee.bind("<Button-1>", lambda _e: datee.drop_down(), add="+")

        semesters = list_semesters()
        sem_by_label = {f'{r["code"]}  ·  {r["name"]}': r["id"] for r in semesters}
        sem_var = ctk.StringVar(value=next(iter(sem_by_label), ""))
        semester = ctk.CTkOptionMenu(form, values=list(sem_by_label), variable=sem_var, height=40)
        semester.grid(row=1, column=1, sticky="ew")

        label("Subject", 2, 0)
        subject_var = ctk.StringVar(value="")
        subject_menu = ctk.CTkOptionMenu(form, values=["Select subject"], variable=subject_var, height=40)
        subject_menu.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        subject_by_label = {}

        type_row = ctk.CTkFrame(form, fg_color="transparent")
        type_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 14))
        ctk.CTkLabel(type_row, text="Session", font=("Segoe UI", 11, "bold"), text_color=TEXT).pack(side="left")
        session_type = ctk.StringVar(value="CLASS")
        class_btn = ctk.CTkSegmentedButton(type_row, values=["Class", "Lab"], width=220,
                                           command=lambda value: on_type(value))
        class_btn.set("Class")
        class_btn.pack(side="right")

        detail = ctk.CTkFrame(form, fg_color="#f7f9fc", corner_radius=6)
        detail.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        hours_var = ctk.IntVar(value=1)

        def draw_detail():
            for w in detail.winfo_children():
                w.destroy()
            if session_type.get() == "LAB":
                ctk.CTkLabel(detail, text="Lab session", font=("Segoe UI", 12, "bold"), text_color=TEXT).pack(
                    side="left", padx=16, pady=14)
                ctk.CTkLabel(detail, text="3 hours · fixed", text_color=MUTED).pack(side="right", padx=16)
                hours_var.set(LAB_HOURS)
            else:
                ctk.CTkLabel(detail, text="Class duration", font=("Segoe UI", 12, "bold"), text_color=TEXT).pack(
                    side="left", padx=16, pady=14)
                hours = ctk.CTkSegmentedButton(detail, values=["1 hr", "2 hr", "3 hr"], width=230,
                                               command=lambda value: hours_var.set(int(value[0])))
                hours.set(f"{hours_var.get()} hr")
                hours.pack(side="right", padx=12)

        def on_type(value):
            session_type.set("LAB" if value == "Lab" else "CLASS")
            draw_detail()

        label("Today's topic", 6, 0)
        topic = ctk.CTkEntry(form, height=42, placeholder_text="What was taught in this session?")
        topic.grid(row=7, column=0, columnspan=2, sticky="ew")
        if preset.get("topic"):
            topic.insert(0, preset["topic"])

        hint = ctk.CTkLabel(card, text="", font=("Segoe UI", 11), text_color="#b45309")
        hint.pack(anchor="w", padx=30, pady=(14, 0))

        def refresh_subjects(*_):
            nonlocal subject_by_label
            sem_id = sem_by_label.get(sem_var.get())
            subjects = list_subjects(sem_id, self.username, self.role)
            subject_by_label = {f'{r["code"]}  ·  {r["name"]}': r["id"] for r in subjects}
            values = list(subject_by_label) or ["No assigned subjects"]
            subject_menu.configure(values=values)
            subject_var.set(values[0])
            on_subject()

        def on_subject(*_):
            sid = subject_by_label.get(subject_var.get())
            row = subject_details(sid) if sid else None
            if row and not row["has_lab"] and session_type.get() == "LAB":
                class_btn.set("Class")
                on_type("Class")
            hint.configure(text="Lab is available for this subject." if row and row["has_lab"] else "")

        semester.configure(command=lambda _value: refresh_subjects())
        subject_menu.configure(command=lambda _value: on_subject())
        draw_detail()
        refresh_subjects()

        def open_register():
            sem_id = sem_by_label.get(sem_var.get())
            subject_id = subject_by_label.get(subject_var.get())
            subject = subject_details(subject_id) if subject_id else None
            stype = session_type.get()
            if stype == "LAB" and subject and not subject["has_lab"]:
                messagebox.showwarning("Lab unavailable", "This subject is not configured with a lab.")
                return
            try:
                validate_session_payload(
                    attendance_date=datee.get(), semester_id=sem_id, subject_id=subject_id,
                    faculty_username=self.username, session_type=stype,
                    duration_hours=hours_var.get(), topic=topic.get(),
                )
                session = get_or_create_session(
                    attendance_date=datee.get(), semester_id=sem_id, subject_id=subject_id,
                    faculty_username=self.username, session_type=stype,
                    duration_hours=hours_var.get(), topic=topic.get(), actor=self.username,
                )
            except Exception as exc:
                messagebox.showwarning("Complete session details", str(exc))
                return
            self.attendance_register(session["id"])

        ctk.CTkButton(card, text="Open Register", width=170, height=42, command=open_register).pack(
            anchor="e", padx=30, pady=(18, 28))

    def attendance_register(self, session_id):
        session = session_details(session_id)
        if not session:
            messagebox.showerror("Attendance", "Attendance session was not found.")
            return self.attendance_setup()
        body = self.shell("Attendance Register", "Attendance")
        selected = {}
        row_widgets = {}
        dirty = False
        editable = session_is_editable(session, self.role)

        meta = ctk.CTkFrame(body, fg_color="white", border_width=1, border_color="#e1e6ef", corner_radius=7)
        meta.pack(fill="x", pady=(0, 12))
        left = ctk.CTkFrame(meta, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=18, pady=14)
        ctk.CTkLabel(left, text=f'{session["subject_name"]}  ·  {session["semester_code"]}',
                     font=("Segoe UI", 16, "bold"), text_color=TEXT).pack(anchor="w")
        type_text = "Lab · 3 hours" if session["session_type"] == "LAB" else f'Class · {session["duration_hours"]} hour(s)'
        ctk.CTkLabel(left, text=f'{session["attendance_date"]}   •   {type_text}   •   {session["topic"]}',
                     font=("Segoe UI", 11), text_color=MUTED).pack(anchor="w", pady=(3, 0))
        ctk.CTkButton(meta, text="Change session", width=120, height=34, fg_color="transparent",
                      border_width=1, border_color="#cfd6e2", text_color=TEXT,
                      hover_color="#f3f5f8", command=self.attendance_setup).pack(side="right", padx=16)

        if not editable:
            ctk.CTkLabel(body, text="Locked · Faculty editing ended 24 hours after this session was created.",
                         text_color="#b42318", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))

        content = ctk.CTkFrame(body, fg_color="transparent")
        content.pack(fill="both", expand=True)
        sheet = ctk.CTkFrame(content, fg_color="white", border_width=1, border_color="#dfe4ec", corner_radius=6)
        sheet.pack(side="left", fill="both", expand=True, padx=(0, 12))
        quick = ctk.CTkFrame(content, width=270, fg_color="white", border_width=1, border_color="#dfe4ec", corner_radius=6)
        quick.pack(side="right", fill="y")
        quick.pack_propagate(False)

        summary = ctk.CTkLabel(sheet, text="", font=("Segoe UI", 12, "bold"), text_color=TEXT)
        summary.pack(anchor="e", padx=18, pady=(10, 6))
        header = ctk.CTkFrame(sheet, fg_color="#f3f5f8", corner_radius=0, height=42)
        header.pack(fill="x", padx=1)
        header.pack_propagate(False)
        for col, minimum in enumerate((64, 155, 0, 115)):
            header.grid_columnconfigure(col, minsize=minimum, weight=1 if col == 2 else 0)
        for col, text, anchor in [(0, "S.No", "center"), (1, "Roll No", "w"), (2, "Student Name", "w"), (3, "Present", "center")]:
            ctk.CTkLabel(header, text=text, font=("Segoe UI", 11, "bold"), text_color=TEXT, anchor=anchor).grid(
                row=0, column=col, sticky="nsew", padx=10)

        rows = ctk.CTkScrollableFrame(sheet, fg_color="white", corner_radius=0)
        rows.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        def refresh_summary():
            present = sum(bool(v) for v in selected.values())
            summary.configure(text=f"{present} Present   •   {len(selected)-present} Absent")

        def set_present(roll, value, mark_dirty=True):
            nonlocal dirty
            selected[roll] = bool(value)
            cb = row_widgets.get(roll)
            if cb:
                cb.select() if value else cb.deselect()
            if mark_dirty:
                dirty = True
            refresh_summary()

        students, existing = load_register(session_id)
        for index, student in enumerate(students, 1):
            row = ctk.CTkFrame(rows, fg_color="#ffffff" if index % 2 else "#fbfcfe", corner_radius=0, height=38)
            row.pack(fill="x")
            row.grid_columnconfigure(0, minsize=64)
            row.grid_columnconfigure(1, minsize=155)
            row.grid_columnconfigure(2, weight=1)
            row.grid_columnconfigure(3, minsize=115)
            ctk.CTkLabel(row, text=str(index), anchor="center", text_color=TEXT).grid(row=0, column=0, sticky="nsew", padx=10)
            ctk.CTkLabel(row, text=student["roll_no"], anchor="w", text_color=TEXT).grid(row=0, column=1, sticky="nsew", padx=10)
            ctk.CTkLabel(row, text=student["name"], anchor="w", text_color=TEXT).grid(row=0, column=2, sticky="nsew", padx=10)
            cb = ctk.CTkCheckBox(row, text="", width=24, checkbox_width=22, checkbox_height=22,
                                 fg_color=GREEN, hover_color="#128447",
                                 state="normal" if editable else "disabled",
                                 command=lambda roll=student["roll_no"]: set_present(roll, bool(row_widgets[roll].get())))
            cb.grid(row=0, column=3)
            row_widgets[student["roll_no"]] = cb
            is_present = existing.get(student["roll_no"]) == "Present"
            selected[student["roll_no"]] = is_present
            if is_present:
                cb.select()
        refresh_summary()

        ctk.CTkLabel(quick, text="Quick Present", font=("Segoe UI", 18, "bold"), text_color=TEXT).pack(anchor="w", padx=18, pady=(20, 4))
        ctk.CTkLabel(quick, text="Enter roll numbers to tick\nmultiple students at once.", justify="left", text_color=MUTED).pack(anchor="w", padx=18)
        quick_entry = ctk.CTkTextbox(quick, height=150, corner_radius=6, border_width=1, border_color="#d0d5dd")
        quick_entry.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(quick, text="Examples:\n01, 03, 17\n6701 6703 6717", justify="left", text_color=MUTED, font=("Segoe UI", 11)).pack(anchor="w", padx=18)

        def resolve_rolls(raw):
            tokens = [x.strip().upper() for x in re.split(r"[,;\s]+", raw) if x.strip()]
            found, missing = [], []
            for token in tokens:
                matches = [token] if token in selected else []
                if not matches and token.isdigit() and len(token) in (2, 4):
                    matches = [r for r in selected if r.endswith(token)]
                matches = list(dict.fromkeys(matches))
                if len(matches) == 1:
                    if matches[0] not in found:
                        found.append(matches[0])
                else:
                    missing.append(token)
            return found, missing

        def quick_mark():
            if not editable:
                return
            raw = quick_entry.get("1.0", "end").strip()
            if not raw:
                return messagebox.showwarning("Enter roll numbers", "Enter one or more roll numbers first.")
            found, missing = resolve_rolls(raw)
            if not found:
                return messagebox.showerror("No students found", "None of the entered roll numbers matched active CSD students.")
            names = {s["roll_no"]: s["name"] for s in students}
            preview = "\n".join(f"{r:<16}{names.get(r, '')}" for r in found)
            if missing:
                preview += "\n\nNot found / ambiguous:\n" + "\n".join(f"  {x}" for x in missing)
            if not messagebox.askyesno("Confirm Quick Present", f"{preview}\n\nTick these {len(found)} students as PRESENT?"):
                return
            for roll in found:
                set_present(roll, True, False)
            nonlocal dirty
            dirty = True
            refresh_summary()
            quick_entry.delete("1.0", "end")

        mark_btn = ctk.CTkButton(quick, text="Mark Present", height=40, fg_color=GREEN,
                                 hover_color="#128447", command=quick_mark,
                                 state="normal" if editable else "disabled")
        mark_btn.pack(fill="x", padx=18, pady=18)

        def save():
            nonlocal dirty
            if not editable:
                return messagebox.showerror("Attendance locked", "The 24-hour faculty edit window has expired. Contact HOD for correction.")
            # The metadata is re-read from the session and passed through the write-boundary validator.
            current = session_details(session_id)
            type_text = "Lab" if current["session_type"] == "LAB" else "Class"
            duration_text = "3 hours (fixed)" if current["session_type"] == "LAB" else f'{current["duration_hours"]} hour(s)'
            present = sum(bool(v) for v in selected.values())
            message = (
                f'Save this attendance?\n\nDate: {current["attendance_date"]}\nSemester: {current["semester_code"]}\n'
                f'Subject: {current["subject_name"]}\nFaculty: {current["faculty_name"] or current["faculty_username"]}\n'
                f'Session: {type_text}\nDuration: {duration_text}\nTopic: {current["topic"]}\n\n'
                f'Present: {present}\nAbsent: {len(selected)-present}'
            )
            if not messagebox.askyesno("Confirm Attendance", message):
                return
            try:
                save_register(session_id=session_id, attendance=selected, actor=self.username, role=self.role,
                              session_type=current["session_type"], duration_hours=current["duration_hours"], topic=current["topic"])
                absent_rolls = [roll for roll, is_present in selected.items() if not is_present]
                if absent_rolls:
                    from sms_app.services.sms_service import queue_absentees_for_session
                    queue_absentees_for_session(session_id, absent_rolls, actor=self.username)
                    try:
                        from webapp.sms_worker import process_pending_sms_now
                        process_pending_sms_now()
                    except Exception:
                        pass
            except (ValueError, PermissionError) as exc:
                messagebox.showerror("Attendance not saved", str(exc))
                return
            dirty = False
            messagebox.showinfo("Attendance saved", "Attendance has been saved and absentee SMS dispatched.")

        ctk.CTkButton(body, text="Save Attendance", width=180, height=42, command=save,
                      state="normal" if editable else "disabled").pack(anchor="e", pady=(8, 0))
