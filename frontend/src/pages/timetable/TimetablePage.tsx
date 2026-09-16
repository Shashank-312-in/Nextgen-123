import { useEffect, useMemo, useState } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import {
  getTimetables,
  saveTimetable,
  deleteTimetable,
  type TimetableBlockType,
  type TimetableEntry,
  type TimetableEntryInput,
  type TimetableFaculty,
  type TimetablePageData,
  type TimetablePeriod,
  type TimetableRecord,
  type TimetableSection,
  type TimetableSubject,
} from "../../api/timetable";
import "./timetable.css";

interface Props { user: CurrentUser; onLoggedOut: () => void; }

type DraftEntry = TimetableEntryInput & {
  clientId: string;
  subject_code?: string | null;
  subject_name?: string | null;
  faculty_name?: string | null;
};

const DAYS = [
  ["MON", "Mon"], ["TUE", "Tue"], ["WED", "Wed"], ["THU", "Thu"], ["FRI", "Fri"], ["SAT", "Sat"],
] as const;
const BLOCKS: Array<[TimetableBlockType, string]> = [
  ["THEORY", "Theory"], ["LAB", "Lab"], ["PE", "Professional Elective"], ["OE", "Open Elective"],
  ["TUTORIAL", "Tutorial"], ["ACTIVITY", "Activity"], ["OTHER", "Other"],
];
const BLOCK_LABELS: Record<TimetableBlockType, string> = Object.fromEntries(BLOCKS) as Record<TimetableBlockType, string>;

function toDraft(entry: TimetableEntry): DraftEntry {
  return {
    clientId: `existing-${entry.id}`,
    id: String(entry.id), day: entry.day, section: entry.section, start_slot: entry.start_slot, duration: entry.duration,
    block_type: entry.block_type, subject_id: entry.subject_id, custom_label: entry.custom_label,
    subject_code: entry.subject_code, subject_name: entry.subject_name,
    faculty_username: entry.faculty_username, faculty_name: entry.faculty_name, room: entry.room,
  };
}

function periodBySection(periods: TimetablePeriod[], section: TimetableSection) {
  return periods.filter(p => p.section === section);
}

function getSpanEntry(entries: DraftEntry[], day: string, section: TimetableSection, slot: number) {
  return entries.find(e => e.day === day && e.section === section && slot >= e.start_slot && slot < e.start_slot + e.duration);
}

function canPlace(entries: DraftEntry[], candidate: Pick<DraftEntry, "day" | "section" | "start_slot" | "duration">, ignoreId?: string) {
  return !entries.some(e => {
    if (e.clientId === ignoreId || e.day !== candidate.day || e.section !== candidate.section) return false;
    const a0 = e.start_slot, a1 = e.start_slot + e.duration;
    const b0 = candidate.start_slot, b1 = candidate.start_slot + candidate.duration;
    return a0 < b1 && b0 < a1;
  });
}

export function TimetablePage({ user, onLoggedOut }: Props) {
  const isBuilder = user.role === "HOD" || user.role === "ADMIN";
  const [data, setData] = useState<TimetablePageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [semesterId, setSemesterId] = useState<number | "">("");
  const [sectionName, setSectionName] = useState("A");
  const [academicYear, setAcademicYear] = useState("2026-27");
  const [selectedRecordId, setSelectedRecordId] = useState<number | null>(null);
  const [periods, setPeriods] = useState<TimetablePeriod[]>([]);
  const [entries, setEntries] = useState<DraftEntry[]>([]);
  const [editing, setEditing] = useState<DraftEntry | null>(null);
  const [dragType, setDragType] = useState<TimetableBlockType | null>(null);
  const [dragEntryId, setDragEntryId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [viewerSemesterId, setViewerSemesterId] = useState<number | "">("");
  const [viewerSection, setViewerSection] = useState("ALL");

  async function load(params: Parameters<typeof getTimetables>[0] = {}) {
    setLoading(true); setError(null);
    try { setData(await getTimetables(params)); }
    catch (err) { setError(err instanceof ApiClientError ? err.message : "Failed to load timetable"); }
    finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, []);

  const activePeriods = periods.length ? periods : (data?.periods_default || []);
  const morningPeriods = useMemo(() => periodBySection(activePeriods, "MORNING"), [activePeriods]);
  const afternoonPeriods = useMemo(() => periodBySection(activePeriods, "AFTERNOON"), [activePeriods]);
  const selectedRecord = useMemo(() => data?.timetables.find(t => t.id === selectedRecordId) || null, [data, selectedRecordId]);
  const filteredViewer = useMemo(() => (data?.timetables || []).filter(t => viewerSection === "ALL" || t.section_name === viewerSection), [data, viewerSection]);
  const viewerRecord = filteredViewer[0] || null;

  useEffect(() => {
    if (!data || !isBuilder) return;
    const firstSemester = data.semesters.find(s => s.active) || data.semesters[0];
    if (!semesterId && firstSemester) setSemesterId(firstSemester.id);
    if (!periods.length) setPeriods(data.periods_default);
  }, [data, isBuilder, semesterId, periods.length]);

  useEffect(() => {
    if (!isBuilder || !semesterId) return;
    void (async () => {
      try {
        const fresh = await getTimetables({ semester_id: Number(semesterId) });
        setData(fresh);
        if (!periods.length) setPeriods(fresh.periods_default);
      } catch (err) {
        setError(err instanceof ApiClientError ? err.message : "Failed to load semester data");
      }
    })();
  // Load subjects/faculty for the selected semester.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [semesterId, isBuilder]);

  useEffect(() => {
    if (!data || !isBuilder || !selectedRecordId) return;
    const match = data.timetables.find(t => t.id === selectedRecordId);
    if (match) {
      setSemesterId(match.semester_id); setSectionName(match.section_name); setAcademicYear(match.academic_year); setPeriods(match.periods); setEntries(match.entries.map(toDraft));
    }
  }, [data, isBuilder, selectedRecordId]);

  useEffect(() => {
    if (!data || isBuilder) return;
    const first = data.timetables[0];
    if (first && !viewerSemesterId) setViewerSemesterId(first.semester_id);
  }, [data, isBuilder, viewerSemesterId]);

  async function newDraftForSemester(nextSemester: number) {
    setSemesterId(nextSemester); setSelectedRecordId(null); setEntries([]); setPeriods(data?.periods_default || []); setSectionName("A"); setEditing(null);
    try { setData(await getTimetables({ semester_id: nextSemester })); }
    catch (err) { setError(err instanceof ApiClientError ? err.message : "Failed to load semester data"); }
  }

  function openRecord(record: TimetableRecord) {
    setSelectedRecordId(record.id); setSemesterId(record.semester_id); setSectionName(record.section_name); setAcademicYear(record.academic_year); setPeriods(record.periods); setEntries(record.entries.map(toDraft)); setEditing(null);
  }

  function subjectFor(entry: DraftEntry): TimetableSubject | undefined {
    if (entry.subject_id == null) return undefined;

    // Builder responses include the subject catalogue, while viewer responses
    // only need the subject data serialized on each timetable entry. Keep the
    // renderer tolerant of both shapes so a published timetable never crashes.
    const subject = data?.subjects?.find(s => s.id === entry.subject_id);
    if (subject) return subject;

    if (entry.subject_code || entry.subject_name) {
      return {
        id: entry.subject_id,
        code: entry.subject_code ?? "",
        name: entry.subject_name ?? "",
        has_lab: 0,
      };
    }

    return undefined;
  }

  function facultyFor(entry: DraftEntry): TimetableFaculty | undefined {
    if (!entry.faculty_username) return undefined;

    const faculty = data?.faculty?.find(f => f.username === entry.faculty_username);
    if (faculty) return faculty;

    // Viewer payloads carry the resolved faculty name on each entry instead of
    // returning a separate faculty catalogue.
    if (entry.faculty_name) {
      return { username: entry.faculty_username, full_name: entry.faculty_name };
    }

    return undefined;
  }

  function createEntry(type: TimetableBlockType, day = "MON", section: TimetableSection = "MORNING", slot = 0) {
    const candidate: DraftEntry = {
      clientId: `new-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      day, section, start_slot: slot, duration: 1, block_type: type, subject_id: null, custom_label: "", faculty_username: null, room: "",
    };
    if (!canPlace(entries, candidate)) { setError("That period is already occupied."); return; }
    setEntries(prev => [...prev, candidate]); setEditing(candidate);
  }

  function handleSlotDrop(day: string, section: TimetableSection, slot: number) {
    if (dragType) {
      if (canPlace(entries, { day, section, start_slot: slot, duration: 1 })) createEntry(dragType, day, section, slot);
      else setError("That period is already occupied.");
      setDragType(null); return;
    }
    if (dragEntryId) {
      const moving = entries.find(e => e.clientId === dragEntryId);
      if (!moving) return;
      if (!canPlace(entries, { day, section, start_slot: slot, duration: moving.duration }, moving.clientId)) { setError("That move would overlap another block."); return; }
      setEntries(prev => prev.map(e => e.clientId === dragEntryId ? { ...e, day, section, start_slot: slot } : e));
      setDragEntryId(null);
    }
  }

  function removeEntry(id: string) { setEntries(prev => prev.filter(e => e.clientId !== id)); if (editing?.clientId === id) setEditing(null); }

  function updateEditing(patch: Partial<DraftEntry>) {
    if (!editing) return;
    setEditing(prev => prev ? { ...prev, ...patch } : prev);
    setEntries(prev => prev.map(e => e.clientId === editing.clientId ? { ...e, ...patch } : e));
  }

  function changeDuration(raw: number) {
    if (!editing) return;
    const count = periodBySection(activePeriods, editing.section).length;
    const next = Math.max(1, Math.min(raw, count - editing.start_slot));
    const candidate = { day: editing.day, section: editing.section, start_slot: editing.start_slot, duration: next } as const;
    if (!canPlace(entries, candidate, editing.clientId)) { setError("That length overlaps another block."); return; }
    updateEditing({ duration: next });
  }

  async function save(status: "DRAFT" | "PUBLISHED") {
    if (!semesterId) { setError("Select a semester first."); return; }
    setSaving(true); setError(null);
    try {
      const result = await saveTimetable({ id: selectedRecordId, semester_id: semesterId, section_name: sectionName.trim().toUpperCase(), academic_year: academicYear.trim(), periods: activePeriods, entries, status });
      setSelectedRecordId(result.timetable.id); setNotice(status === "PUBLISHED" ? "Timetable published for faculty and students." : "Timetable draft saved."); await load({ semester_id: semesterId });
      setTimeout(() => setSelectedRecordId(result.timetable.id), 0);
    } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not save timetable"); }
    finally { setSaving(false); }
  }

  async function removeCurrent() {
    if (!selectedRecordId) return;
    if (!window.confirm("Delete this timetable?")) return;
    try { await deleteTimetable(selectedRecordId); setNotice("Timetable deleted."); setSelectedRecordId(null); setEntries([]); await load({ semester_id: Number(semesterId) }); }
    catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not delete timetable"); }
  }

  function blockTitle(entry: DraftEntry) {
    const subject = subjectFor(entry);
    return subject ? `${subject.code} · ${subject.name}` : entry.custom_label || BLOCK_LABELS[entry.block_type];
  }

  function renderDay(day: string, label: string, readonly = false, record?: TimetableRecord) {
    const sourceEntries = readonly && record ? record.entries.map(toDraft) : entries;
    const sourcePeriods = readonly && record ? record.periods : activePeriods;
    const renderSection = (section: TimetableSection, count: number) => {
      const sectionEntries = sourceEntries.filter(e => e.day === day && e.section === section);
      return (
        <div className={`tt-slot-area ${section === "MORNING" ? "morning" : "afternoon"}`}>
          <div className="tt-slot-grid" aria-hidden={readonly ? undefined : "false"}>
            {Array.from({ length: count }, (_, slot) => (
              <div
                key={`${day}-${section}-${slot}`}
                className="tt-slot"
                onDragOver={readonly ? undefined : e => { e.preventDefault(); e.currentTarget.classList.add("drop-ready"); }}
                onDragLeave={readonly ? undefined : e => e.currentTarget.classList.remove("drop-ready")}
                onDrop={readonly ? undefined : e => { e.preventDefault(); e.currentTarget.classList.remove("drop-ready"); handleSlotDrop(day, section, slot); }}
                onClick={readonly ? undefined : () => { if (dragType) handleSlotDrop(day, section, slot); }}
              >
                {!readonly && !getSpanEntry(sourceEntries, day, section, slot) && <div className="tt-drop-label">Drop here</div>}
              </div>
            ))}
          </div>
          <div className="tt-block-layer">
            {sectionEntries.map(entry => (
              <div
                key={entry.clientId}
                className={`tt-block${!readonly && editing?.clientId === entry.clientId ? " tt-selected" : ""}`}
                data-type={entry.block_type}
                style={{ gridColumn: `${entry.start_slot + 1} / span ${entry.duration}` }}
                draggable={!readonly}
                onDragStart={readonly ? undefined : () => setDragEntryId(entry.clientId)}
                onDragEnd={readonly ? undefined : () => setDragEntryId(null)}
                onClick={readonly ? undefined : () => setEditing(entry)}
              >
                <div className="tt-block-title">{blockTitle(entry)}</div>
                <div className="tt-block-meta">{BLOCK_LABELS[entry.block_type]} · {entry.duration} {entry.duration === 1 ? "period" : "periods"}</div>
                {(entry.faculty_username && facultyFor(entry)) && <div className="tt-block-faculty">{facultyFor(entry)?.full_name}</div>}
                {readonly && entry.faculty_name && <div className="tt-block-faculty">{entry.faculty_name}</div>}
                {!!entry.room && <div className="tt-block-faculty">{entry.room}</div>}
                {!readonly && <div className="tt-block-actions"><button type="button" className="tt-icon-btn" onClick={e => { e.stopPropagation(); setEditing(entry); }} aria-label="Edit">✎</button></div>}
              </div>
            ))}
          </div>
        </div>
      );
    };
    return <div className="tt-day-row" key={`${day}-${record?.id ?? "edit"}`}><div className="tt-day-label">{label}</div>{renderSection("MORNING", periodBySection(sourcePeriods, "MORNING").length)}<div className="tt-break-strip">LUNCH</div>{renderSection("AFTERNOON", periodBySection(sourcePeriods, "AFTERNOON").length)}</div>;
  }



  function renderReadonly(record: TimetableRecord) {
    return (
      <div className="tt-canvas-card"><div className="tt-scroll"><div className="tt-grid">
        <div className="tt-grid-header"><div className="tt-day-head">Day</div><div className="tt-slot-group">{periodBySection(record.periods, "MORNING").map(p=><div key={p.key} className="tt-slot-head"><strong>{p.label}</strong>{p.start}-{p.end}</div>)}</div><div className="tt-break-strip">L</div><div className="tt-slot-group afternoon">{periodBySection(record.periods, "AFTERNOON").map(p=><div key={p.key} className="tt-slot-head"><strong>{p.label}</strong>{p.start}-{p.end}</div>)}</div></div>
        {DAYS.map(([day,label]) => renderDay(day, label, true, record))}
      </div></div></div>
    );
  }

  if (loading) return <AppShell user={user} activeNav="timetable" heading="Timetable" onLoggedOut={onLoggedOut}><p className="empty-note">Loading timetable workspace…</p></AppShell>;

  if (!isBuilder) {
    const records = filteredViewer;
    const viewer = records.find(t => t.semester_id === viewerSemesterId) || viewerRecord;
    return <AppShell user={user} activeNav="timetable" heading="Timetable" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error} onClose={() => setError(null)} />{notice&&<ToastPopup type="success" message={notice} onClose={()=>setNotice(null)}/>} 
      <div className="timetable-page">
        <div className="tt-viewer-head"><div className="tt-viewer-title"><h2>Class timetable</h2><p>Published schedules from your department.</p></div><div className="tt-viewer-selects"><select value={viewerSemesterId} onChange={e=>{setViewerSemesterId(Number(e.target.value));setViewerSection("ALL");void load({semester_id:Number(e.target.value)})}}><option value="">Select semester</option>{data?.semesters.map(s=><option key={s.id} value={s.id}>{s.code}</option>)}</select><select value={viewerSection} onChange={e=>setViewerSection(e.target.value)}><option value="ALL">All sections</option>{Array.from(new Set((data?.timetables||[]).map(t=>t.section_name))).sort().map(s=><option key={s} value={s}>Section {s}</option>)}</select></div></div>
        {!viewer && <div className="tt-empty">No published timetable is available for this selection yet.</div>}
        {viewer && <><div className="tt-status-row"><div className="tt-status-copy"><strong>{viewer.semester_code}</strong> · Section {viewer.section_name} · {viewer.academic_year}</div><span className="tt-badge published">PUBLISHED</span></div>{renderReadonly(viewer)}</>}
      </div>
    </AppShell>;
  }

  return <AppShell user={user} activeNav="timetable" heading="Timetable Builder" onLoggedOut={onLoggedOut}>
    <ErrorPopup message={error} onClose={()=>setError(null)} />{notice&&<ToastPopup type="success" message={notice} onClose={()=>setNotice(null)}/>} 
    <div className="timetable-page">
      <div className="timetable-toolbar">
        <div><div className="tt-inline-note">Compose the schedule as blocks. Drag a block onto a period, set its duration, then publish once it passes conflict checks.</div></div>
        <div className="timetable-toolbar-actions"><button type="button" className="btn-secondary" onClick={()=>semesterId&&newDraftForSemester(Number(semesterId))}>New timetable</button>{selectedRecordId&&<button type="button" className="btn-secondary" onClick={removeCurrent}>Delete</button>}<button type="button" className="btn-secondary" disabled={saving} onClick={()=>save("DRAFT")}>{saving?"Saving…":"Save draft"}</button><button type="button" className="btn-primary" disabled={saving} onClick={()=>save("PUBLISHED")}>{saving?"Publishing…":"Publish"}</button></div>
      </div>
      <div className="timetable-toolbar"><div className="timetable-toolbar-left"><div className="tt-field"><label>Semester</label><select value={semesterId} onChange={e=>newDraftForSemester(Number(e.target.value))}><option value="">Choose semester</option>{data?.semesters.map(s=><option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}</select></div><div className="tt-field"><label>Section</label><input value={sectionName} onChange={e=>setSectionName(e.target.value)} maxLength={32}/></div><div className="tt-field"><label>Academic year</label><input value={academicYear} onChange={e=>setAcademicYear(e.target.value)} maxLength={32}/></div></div><div className="tt-inline-note tt-desktop-note">Blocks snap to the timetable skeleton. A block cannot overlap another block.</div></div>
      {selectedRecord && <div className="tt-status-row"><div className="tt-status-copy"><strong>{selectedRecord.semester_code}</strong> · Section {selectedRecord.section_name} · {selectedRecord.academic_year}</div><span className={`tt-badge ${selectedRecord.status === "PUBLISHED" ? "published" : "draft"}`}>{selectedRecord.status}</span></div>}
      <div className="tt-workspace">
        <aside className="tt-palette"><h3>Block library</h3><p>Drag these onto the timetable. On mobile, tap a block, then tap a period.</p><div className="tt-mobile-placement">Tip: tap a block type, then tap the empty period where you want it.</div><div className="tt-palette-group"><div>Academic</div><div className="tt-palette-list">{BLOCKS.map(([type,label])=><button key={type} type="button" draggable onDragStart={()=>setDragType(type)} onClick={()=>setDragType(type)} className="tt-palette-item">{label}<small>+</small></button>)}</div></div></aside>
        <div className="tt-canvas-card"><div className="tt-scroll"><div className="tt-grid">
          <div className="tt-grid-header"><div className="tt-day-head">Day</div><div className="tt-slot-group">{morningPeriods.map(p=><div key={p.key} className="tt-slot-head"><strong>{p.label}</strong>{p.start}-{p.end}</div>)}</div><div className="tt-break-strip">L</div><div className="tt-slot-group afternoon">{afternoonPeriods.map(p=><div key={p.key} className="tt-slot-head"><strong>{p.label}</strong>{p.start}-{p.end}</div>)}</div></div>
          {DAYS.map(([day,label])=>renderDay(day,label))}
        </div></div></div>
      </div>
      {editing && <div className="tt-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setEditing(null)}}><section className="tt-modal" role="dialog" aria-modal="true"><div className="tt-modal-head"><div><h3>Configure block</h3><p>{editing.day} · {editing.section === "MORNING" ? "Morning" : "Afternoon"} · slot {editing.start_slot + 1}</p></div><button type="button" className="tt-icon-btn" onClick={()=>setEditing(null)} aria-label="Close">×</button></div><div className="tt-modal-body"><div className="tt-modal-grid"><div className="tt-field"><label>Block type</label><select value={editing.block_type} onChange={e=>updateEditing({block_type:e.target.value as TimetableBlockType})}>{BLOCKS.map(([t,l])=><option key={t} value={t}>{l}</option>)}</select></div><div className="tt-field"><label>Duration</label><select value={editing.duration} onChange={e=>changeDuration(Number(e.target.value))}>{Array.from({length:periodBySection(activePeriods,editing.section).length-editing.start_slot},(_,i)=><option key={i+1} value={i+1}>{i+1} {i===0?"period":"periods"}</option>)}</select></div><div className="tt-field"><label>Subject</label><select value={editing.subject_id ?? ""} onChange={e=>updateEditing({subject_id:e.target.value?Number(e.target.value):null,custom_label:e.target.value?"":editing.custom_label})}><option value="">Custom / no subject</option>{(data?.subjects ?? []).map(s=><option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}</select></div><div className="tt-field"><label>Faculty</label><select value={editing.faculty_username ?? ""} onChange={e=>updateEditing({faculty_username:e.target.value||null})}><option value="">Not assigned</option>{(data?.faculty ?? []).map(f=><option key={f.username} value={f.username}>{f.full_name || f.username}</option>)}</select></div><div className="tt-field"><label>Room</label><input value={editing.room} onChange={e=>updateEditing({room:e.target.value})} placeholder="e.g. Lab 2"/></div><div className="tt-field"><label>Custom label</label><input value={editing.custom_label} onChange={e=>updateEditing({custom_label:e.target.value})} placeholder="Used for activities / labels"/></div></div><div className="tt-help">The duration changes the block span automatically. Moving a block keeps its length; the system refuses overlaps before saving.</div><div className="tt-modal-actions"><button type="button" className="btn-secondary" onClick={()=>{removeEntry(editing.clientId);setEditing(null)}}>Remove block</button><button type="button" className="btn-primary" onClick={()=>setEditing(null)}>Done</button></div></div></section></div>}
      <div className="tt-side-panel"><div className="tt-side-card"><h3>Saved timetables</h3>{!data?.timetables.length?<div className="tt-empty">No timetable drafts yet.</div>:<div className="tt-side-list">{data?.timetables.map(t=><div className="tt-saved-row" key={t.id}><div className="tt-saved-main"><strong>{t.semester_code} · Section {t.section_name}</strong><span>{t.academic_year} · {t.status}</span></div><button type="button" className="btn-secondary" onClick={()=>openRecord(t)}>Open</button></div>)}</div>}</div><div className="tt-side-card"><h3>Build status</h3><div className="tt-side-list"><div className="tt-saved-row"><div className="tt-saved-main"><strong>{entries.length}</strong><span>scheduled blocks</span></div></div><div className="tt-saved-row"><div className="tt-saved-main"><strong>{entries.filter(e=>e.block_type === "LAB").length}</strong><span>lab blocks</span></div></div></div></div></div>
    </div>
  </AppShell>;
}
