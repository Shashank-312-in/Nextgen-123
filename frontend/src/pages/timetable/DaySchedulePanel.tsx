import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiClientError } from "../../api/client";
import {
  createOverride,
  deleteOverride,
  getDaySchedule,
  type DayScheduleEntry,
  type TimetableFaculty,
} from "../../api/timetable";
import "../../styles/ng-flat-controls.css";
import "./day-schedule.css";

// Local (not UTC) yyyy-mm-dd — toISOString() would shift the date for IST users.
const toIso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (iso: string, n: number) => { const d = new Date(`${iso}T00:00:00`); d.setDate(d.getDate() + n); return toIso(d); };
const pretty = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });

interface Props {
  faculty: TimetableFaculty[];
  onNotice?: (msg: string) => void;
}

// Day schedule + substitute cover. One purpose: who teaches each period on
// a chosen date, and covering for an absent faculty member (HOD only).
export function DaySchedulePanel({ faculty, onNotice }: Props) {
  const today = useMemo(() => toIso(new Date()), []);
  const [date, setDate] = useState(today);
  const [entries, setEntries] = useState<DayScheduleEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<DayScheduleEntry | null>(null);
  const [sub, setSub] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async (d: string) => {
    setEntries(null); setError(null);
    try {
      const res = await getDaySchedule(d);
      setEntries([...res.entries].sort((a, b) => (a.section === b.section ? a.start_slot - b.start_slot : a.section === "MORNING" ? -1 : 1)));
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not load the schedule.");
    }
  }, []);

  useEffect(() => { void load(date); }, [date, load]);

  function openAssign(e: DayScheduleEntry) { setAssigning(e); setSub(""); setReason(""); setDialogError(null); }

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!assigning) return;
    if (!sub || !reason.trim()) { setDialogError("Choose a substitute and give a reason."); return; }
    setSaving(true); setDialogError(null);
    try {
      await createOverride({ timetable_entry_id: assigning.timetable_entry_id, override_date: date, substitute_faculty_username: sub, reason: reason.trim() });
      setAssigning(null); onNotice?.("Substitute assigned."); await load(date);
    } catch (err) {
      setDialogError(err instanceof ApiClientError ? err.message : "Could not assign substitute.");
    } finally { setSaving(false); }
  }

  async function undo(e: DayScheduleEntry) {
    if (e.override_id == null) return;
    setBusyId(e.override_id);
    try { await deleteOverride(e.override_id); onNotice?.("Substitute removed."); await load(date); }
    catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not remove substitute."); }
    finally { setBusyId(null); }
  }

  const options = assigning ? faculty.filter(f => f.username !== assigning.regular_faculty_username) : faculty;

  return (
    <section className="ds-panel" aria-label="Day schedule">
      <div className="ds-head">
        <div className="ds-title"><h3>Day schedule</h3><p>{pretty(date)}{date === today ? " · Today" : ""}</p></div>
        <div className="ds-stepper">
          <button type="button" className="ng-flat-btn ng-flat-btn-outline" onClick={() => setDate(addDays(date, -1))} aria-label="Previous day">‹</button>
          <input type="date" className="ng-flat-input" value={date} onChange={e => e.target.value && setDate(e.target.value)} aria-label="Schedule date" />
          <button type="button" className="ng-flat-btn ng-flat-btn-outline" onClick={() => setDate(addDays(date, 1))} aria-label="Next day">›</button>
          {date !== today && <button type="button" className="ng-flat-btn ng-flat-btn-outline" onClick={() => setDate(today)}>Today</button>}
        </div>
      </div>

      {error ? <div className="ds-state is-error">{error}</div>
        : entries === null ? <div className="ds-state">Loading schedule…</div>
        : entries.length === 0 ? <div className="ds-state">No periods scheduled on this date.</div>
        : (
          <ul className="ds-list">
            {entries.map(e => {
              const label = e.subject_name || e.custom_label || e.block_type;
              const covered = e.override_id != null;
              return (
                <li className="ds-row" key={`${e.timetable_entry_id}`}>
                  <div className="ds-time">{e.start_time && e.end_time ? `${e.start_time}–${e.end_time}` : `Slot ${e.start_slot + 1}`}<small>Sec {e.section_name}</small></div>
                  <div className="ds-main">
                    <div className="ds-subject">{label}</div>
                    <div className="ds-meta">
                      {covered
                        ? <><s>{e.regular_faculty_name || e.regular_faculty_username}</s> → <span className="is-sub">{e.substitute_faculty_name || e.substitute_faculty_username}</span>{e.override_reason ? ` · ${e.override_reason}` : ""}</>
                        : (e.regular_faculty_name || e.regular_faculty_username || "No faculty assigned")}
                    </div>
                  </div>
                  <div className="ds-actions">
                    {covered
                      ? <button type="button" className="ng-flat-btn ng-flat-btn-outline ng-flat-btn-sm" disabled={busyId === e.override_id} onClick={() => void undo(e)}>{busyId === e.override_id ? "Removing…" : "Undo"}</button>
                      : <button type="button" className="ng-flat-btn ng-flat-btn-outline ng-flat-btn-sm" onClick={() => openAssign(e)}>Assign substitute</button>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}

      {assigning && (
        <div className="ds-scrim" onMouseDown={ev => { if (ev.target === ev.currentTarget) setAssigning(null); }}>
          <form className="ds-dialog" role="dialog" aria-modal="true" aria-label="Assign substitute" onSubmit={submit}>
            <h4>Assign substitute</h4>
            <div className="ds-meta">{assigning.subject_name || assigning.custom_label || assigning.block_type} · {pretty(date)} · Sec {assigning.section_name}</div>
            <div className="ds-field"><label htmlFor="ds-sub">Substitute faculty</label>
              <select id="ds-sub" className="ng-flat-select" value={sub} onChange={e => setSub(e.target.value)} required>
                <option value="">Select faculty</option>
                {options.map(f => <option key={f.username} value={f.username}>{f.full_name || f.username}</option>)}
              </select></div>
            <div className="ds-field"><label htmlFor="ds-reason">Reason</label>
              <input id="ds-reason" className="ng-flat-input" value={reason} maxLength={300} onChange={e => setReason(e.target.value)} placeholder="e.g. On medical leave" required /></div>
            {dialogError && <p className="ds-err" role="alert">{dialogError}</p>}
            <div className="ds-dialog-actions">
              <button type="button" className="ng-flat-btn ng-flat-btn-outline" onClick={() => setAssigning(null)}>Cancel</button>
              <button type="submit" className="ng-flat-btn ng-flat-btn-primary" disabled={saving}>{saving ? "Assigning…" : "Assign"}</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
