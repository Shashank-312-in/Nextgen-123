"""Official attendance-register PDF — printable anytime (Boss's request),
not gated by the 24h faculty edit lock (viewing/printing isn't editing).

Layout follows Boss's mockup: VCET logo + header, session meta block,
S.No/Roll No/Name/Status table with a light-red background on Absent rows
so the state isn't communicated by colour alone (status text stays too).
"""

import io
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

LOGO_PATH = Path(__file__).parent.parent.parent / "webapp" / "static" / "img" / "vcet_logo.png"

RED_BG = colors.Color(0.99, 0.90, 0.91)   # matches app.css --red tint
GREEN_BG = colors.Color(0.91, 0.98, 0.94)


def build_attendance_pdf(session, roster) -> bytes:
    """session: sqlite Row from session_details(). roster: list of dicts with
    roll_no, name, present (bool) — same shape load_register() produces."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []

    center = ParagraphStyle("center", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=13, leading=16)
    sub = ParagraphStyle("sub", alignment=TA_CENTER, fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#475467"))
    title = ParagraphStyle("title", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=12, spaceBefore=8, spaceAfter=10)

    if LOGO_PATH.exists():
        try:
            story.append(RLImage(str(LOGO_PATH), width=22 * mm, height=19 * mm))
        except Exception:
            pass
    story.append(Paragraph("Visvesvaraya College of Engineering &amp; Technology", center))
    story.append(Paragraph("An Autonomous Institution &middot; Affiliated to JNTU, Hyderabad", sub))
    story.append(Paragraph("Bongloor X Road, MP Patelguda (V), Ibrahimpatnam (M), Hyderabad-501510", sub))
    story.append(Paragraph("DEPARTMENT OF CSE (DATA SCIENCE)", sub))
    story.append(Paragraph("ATTENDANCE REGISTER", title))

    meta_rows = [
        ["Date", session["attendance_date"], "Semester", session["semester_code"]],
        ["Subject", f"{session['subject_name']} ({session['subject_code']})", "Faculty", session["faculty_name"] or session["faculty_username"]],
        ["Session", "Lab" if session["session_type"] == "LAB" else "Class", "Duration", f"{session['duration_hours']} Hour(s)"],
        ["Topic", session["topic"], "", ""],
    ]
    meta = Table(meta_rows, colWidths=[24 * mm, 68 * mm, 24 * mm, 62 * mm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("SPAN", (1, 3), (3, 3)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#d0d5dd")),
    ]))
    story.append(meta)
    story.append(Spacer(1, 10))

    present_count = sum(1 for r in roster if r["present"])
    data = [["S.No", "Roll No", "Name", "Status"]]
    for i, r in enumerate(roster, 1):
        data.append([str(i), r["roll_no"], r["name"], "PRESENT" if r["present"] else "ABSENT"])

    table = Table(data, colWidths=[14 * mm, 32 * mm, 90 * mm, 22 * mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f8")),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e4e7ec")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, r in enumerate(roster, start=1):
        style.append(("BACKGROUND", (0, i), (-1, i), GREEN_BG if r["present"] else RED_BG))
        style.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#067647") if r["present"] else colors.HexColor("#b42318")))
    table.setStyle(TableStyle(style))
    story.append(table)

    story.append(Spacer(1, 10))
    story.append(Paragraph(f"Present: {present_count} &nbsp;&nbsp; Absent: {len(roster) - present_count} &nbsp;&nbsp; Total: {len(roster)}",
                            ParagraphStyle("footer", fontName="Helvetica-Bold", fontSize=10)))

    doc.build(story)
    return buf.getvalue()


def build_monthly_attendance_pdf(data) -> bytes:
    """Plain landscape monthly register: students down, calendar days across."""
    from reportlab.lib.pagesizes import landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak
    from reportlab.lib.enums import TA_LEFT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), topMargin=10*mm, bottomMargin=10*mm,
        leftMargin=8*mm, rightMargin=8*mm,
    )
    story = []
    center = ParagraphStyle("mcenter", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=12, leading=14)
    sub = ParagraphStyle("msub", alignment=TA_CENTER, fontName="Helvetica", fontSize=7.5, leading=9)
    story.append(Paragraph("VISVESVARAYA COLLEGE OF ENGINEERING &amp; TECHNOLOGY", center))
    story.append(Paragraph("An Autonomous Institution · Affiliated to JNTU, Hyderabad", sub))
    story.append(Paragraph("Bongloor X Road, MP Patelguda (V), Ibrahimpatnam (M), Hyderabad-501510", sub))
    story.append(Paragraph(xml_escape(str(data["semester"]["name"])) + " · " + xml_escape(str(data["subject"]["name"])), sub))
    story.append(Paragraph(f"ATTENDANCE REGISTER · {xml_escape(str(data['month_label']))} · Faculty: {xml_escape(str(data['faculty_name']))}", center))
    story.append(Spacer(1, 4*mm))

    day_headers = [["Sl", "Hall Ticket No.", "Student Name"] + [f"{d['day']:02d}" for d in data["days"]]]
    day_headers.append(["", "", ""] + [d["weekday"][:2] for d in data["days"]])
    rows = day_headers
    for idx, student in enumerate(data["roster"], 1):
        rows.append([str(idx), student["roll_no"], student["name"]] + [c["status"] or "" for c in student["cells"]])

    # Landscape A4: fixed identity columns + narrow day columns.
    total_days = len(data["days"])
    day_w = 7.1 * mm if total_days > 28 else 8.5 * mm
    widths = [8*mm, 28*mm, 54*mm] + [day_w] * total_days
    tbl = Table(rows, colWidths=widths, repeatRows=2, splitByRow=1)
    style = [
        ("FONTNAME", (0,0), (-1,1), "Helvetica-Bold"),
        ("FONTNAME", (0,2), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 6.8),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("ALIGN", (2,2), (2,-1), "LEFT"),
        ("BACKGROUND", (0,0), (-1,1), colors.HexColor("#f2f4f7")),
        ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#bfc5cc")),
        ("TOPPADDING", (0,0), (-1,-1), 2.5), ("BOTTOMPADDING", (0,0), (-1,-1), 2.5),
    ]
    # H = central holiday; P/A = actual attendance. Blank = no session.
    for cidx, day in enumerate(data["days"], start=3):
        if day["holiday"]:
            style.append(("BACKGROUND", (cidx,0), (cidx,-1), colors.HexColor("#fff4d6")))
    for ridx, student in enumerate(data["roster"], start=2):
        for cidx, cell in enumerate(student["cells"], start=3):
            if cell["status"] == "H":
                style.append(("BACKGROUND", (cidx,ridx), (cidx,ridx), colors.HexColor("#fff4d6")))
            elif cell["status"] == "P":
                style.append(("TEXTCOLOR", (cidx,ridx), (cidx,ridx), colors.HexColor("#067647")))
            elif cell["status"] == "A":
                style.append(("TEXTCOLOR", (cidx,ridx), (cidx,ridx), colors.HexColor("#b42318")))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("P = Present · A = Absent · H = Central Holiday · blank = no class/session recorded", sub))
    doc.build(story)
    return buf.getvalue()

