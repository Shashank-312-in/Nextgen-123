import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  type AttendanceSession,
  type RosterEntry,
  getSession,
  markAllPresent,
  saveRegister,
  registerPdfUrl,
} from "../../api/attendance";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";
import "./attendance-p0.css";

interface AttendanceRegisterPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

type IconName = "search" | "check" | "x" | "arrow" | "bolt" | "calendar" | "clock" | "lock" | "list" | "download" | "close";

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<IconName, ReactNode> = {
    search: <><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    x: <><path d="m6 6 12 12"/><path d="m18 6-12 12"/></>,
    arrow: <><path d="M5 12h13"/><path d="m13 6 6 6-6 6"/></>,
    bolt: <path d="m13 2-9 12h7l-1 8 9-13h-7z"/>,
    calendar: <><rect x="3" y="4" width="18" height="17" rx="3"/><path d="M16 2v4M8 2v4M3 9h18"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    lock: <><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    list: <><path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1" fill="currentColor"/><circle cx="4" cy="12" r="1" fill="currentColor"/><circle cx="4" cy="18" r="1" fill="currentColor"/></>,
    download: <><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></>,
    close: <><path d="m6 6 12 12"/><path d="m18 6-12 12"/></>,
  };
  return <svg {...common}>{paths[name]}</svg>;
}

function normalizeLeToken(token: string): string | null {
  const cleaned = token.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!cleaned.startsWith("LE")) return null;
  const suffix = cleaned.slice(2);
  return /^\d{2}$/.test(suffix) ? suffix : null;
}

function isLeRoll(roll: string): boolean {
  return /^\d{2}BT5A\d{2,}$/i.test(roll.trim());
}

export function AttendanceRegisterPage({ user, onLoggedOut }: AttendanceRegisterPageProps) {
  const navigate = useNavigate();
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>();
  const sessionId = Number(sessionIdParam);

  const [session, setSession] = useState<AttendanceSession | null>(null);
  const [editable, setEditable] = useState(false);
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [search, setSearch] = useState("");
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickRolls, setQuickRolls] = useState("");
  const [quickNote, setQuickNote] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [showConfirmList, setShowConfirmList] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSession(sessionId);
      setSession(res.session);
      setEditable(res.editable);
      setRoster(res.roster);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not load attendance register");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (Number.isFinite(sessionId)) load();
  }, [sessionId, load]);

  const presentCount = useMemo(() => roster.filter((r) => r.present).length, [roster]);
  const absentCount = roster.length - presentCount;
  const filteredRoster = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return roster;
    return roster.filter((r) => r.roll_no.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));
  }, [roster, search]);

  function toggleRow(rollNo: string) {
    if (!editable) return;
    setError(null);
    setSuccess(null);
    setRoster((prev) => prev.map((r) => r.roll_no === rollNo ? { ...r, present: !r.present } : r));
  }

  async function handleMarkAllPresent() {
    if (!editable) return;
    setMarkingAll(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await markAllPresent(sessionId);
      setEditable(res.editable);
      setRoster(res.roster);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not mark everyone present");
    } finally {
      setMarkingAll(false);
    }
  }

  function handleQuickMark() {
    if (!editable || !quickRolls.trim()) return;
    const allRolls = roster.map((r) => r.roll_no);
    const normalPool = allRolls.filter((roll) => !isLeRoll(roll));
    const lePool = allRolls.filter(isLeRoll);
    const tokens = quickRolls.split(/[,;\s]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
    const toMark = new Set<string>();
    let skipped = 0;

    for (const token of tokens) {
      const leSuffix = normalizeLeToken(token);
      const pool = leSuffix ? lePool : normalPool;
      const suffix = leSuffix ?? (/^\d+$/.test(token) && (token.length === 2 || token.length === 4) ? token : null);
      let matches: string[] = allRolls.includes(token) ? [token] : [];
      if (!matches.length && suffix) matches = pool.filter((roll) => roll.toUpperCase().endsWith(suffix));
      matches = [...new Set(matches)];
      if (matches.length === 1) toMark.add(matches[0]);
      else skipped += 1;
    }

    setRoster((prev) => prev.map((r) => toMark.has(r.roll_no) ? { ...r, present: true } : r));
    setQuickNote(toMark.size ? `Marked ${toMark.size} student${toMark.size === 1 ? "" : "s"} present${skipped ? ` · ${skipped} token${skipped === 1 ? "" : "s"} unmatched` : ""}.` : "No unique roll numbers matched.");
    setQuickRolls("");
  }

  async function commitSave() {
    setSaving(true);
    setError(null);
    try {
      const presentRollNos = roster.filter((r) => r.present).map((r) => r.roll_no);
      const res = await saveRegister(sessionId, presentRollNos);
      setSession(res.session);
      setRoster(res.roster);
      setConfirmOpen(false);
      setShowConfirmList(false);
      setSuccess("Attendance saved.");
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "EDIT_WINDOW_EXPIRED") setEditable(false);
      setError(err instanceof ApiClientError ? err.message : "Could not save attendance");
    } finally {
      setSaving(false);
    }
  }

  function openConfirm(e?: FormEvent) {
    e?.preventDefault();
    if (!editable || saving) return;
    setSuccess(null);
    setConfirmOpen(true);
  }

  if (loading) {
    return (
      <AppShell user={user} activeNav="attendance" heading="Attendance Register" onLoggedOut={onLoggedOut}>
        <div className="att-p0"><div className="att-card pad att-loading"><div className="att-spinner" />Loading register…</div></div>
      </AppShell>
    );
  }

  return (
    <AppShell user={user} activeNav="attendance" heading="Attendance Register" onLoggedOut={onLoggedOut}>
      <div className="att-p0 att-register">
        <div className="att-reg-top">
          <div>
            <button className="att-reg-back" type="button" onClick={() => navigate("/attendance")}>← Back to attendance</button>
            <h1 className="att-reg-title">{session?.subject_code} — {session?.subject_name}</h1>
            <div className="att-reg-meta">
              <span className="att-reg-badge blue"><Icon name="calendar" size={12} />{session?.attendance_date}</span>
              <span className="att-reg-badge"><Icon name="clock" size={12} />{session?.duration_hours} hour{session?.duration_hours === 1 ? "" : "s"}</span>
              <span className="att-reg-badge">{session?.session_type === "LAB" ? "Lab" : "Regular class"}</span>
              {session?.topic && <span className="att-reg-badge">{session.topic}</span>}
              <span className={`att-reg-badge ${editable ? "blue" : "lock"}`}><Icon name={editable ? "check" : "lock"} size={12} />{editable ? "Editable" : "View only"}</span>
            </div>
          </div>
          <div className="att-reg-actions">
            <a className="att-secondary" href={registerPdfUrl(sessionId)} target="_blank" rel="noreferrer"><Icon name="download" size={14} />&nbsp; PDF</a>
          </div>
        </div>

        {error && <div className="att-error">{error}</div>}
        {success && <div className="att-success" style={{ marginBottom: 12 }}>{success}</div>}
        {!editable && <div className="att-inline-warning" style={{ marginBottom: 13 }}><Icon name="lock" size={13} />&nbsp; This register is outside the 24-hour faculty edit window. It remains available for viewing.</div>}

        <div className="att-tally">
          <div className="att-tally-item"><span className="att-tally-dot p" /><div><div className="att-tally-num">{presentCount}</div><div className="att-tally-label">Present</div></div></div>
          <div className="att-tally-item"><span className="att-tally-dot a" /><div><div className="att-tally-num">{absentCount}</div><div className="att-tally-label">Absent</div></div></div>
        </div>

        <div className="att-tools">
          <div className="att-search">
            <Icon name="search" size={16} />
            <input aria-label="Search students" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name or roll number" />
          </div>
          <button className="att-secondary" type="button" onClick={() => setQuickOpen(true)} disabled={!editable}><Icon name="bolt" size={14} />&nbsp; Quick present</button>
          <button className="att-secondary" type="button" onClick={handleMarkAllPresent} disabled={!editable || markingAll || saving}>{markingAll ? "Marking…" : "Mark all present"}</button>
        </div>

        <section className="att-roster-wrap">
          <div className="att-roster-head"><div>Roll no.</div><div>Student</div><div>Status</div></div>
          {filteredRoster.length === 0 ? (
            <div className="att-loading">No matching students.</div>
          ) : filteredRoster.map((r) => (
            <div className={`att-roster-row ${editable ? "clickable" : ""}`} key={r.roll_no} onClick={() => toggleRow(r.roll_no)}>
              <div className="att-roll">{r.roll_no}</div>
              <div className="att-student"><div className="att-student-name">{r.name}</div>{isLeRoll(r.roll_no) && <div className="att-student-sub">Lateral entry</div>}</div>
              <button className={`att-status ${r.present ? "present" : "absent"}`} type="button" disabled={!editable} onClick={(e) => { e.stopPropagation(); toggleRow(r.roll_no); }} aria-label={`${r.name}: ${r.present ? "Present" : "Absent"}`}>
                <Icon name={r.present ? "check" : "x"} size={14} /> {r.present ? "Present" : "Absent"}
              </button>
            </div>
          ))}
          <div className="att-roster-foot">Showing {filteredRoster.length} of {roster.length} students. Tap a student row to switch their status.</div>
        </section>

        {editable && (
          <div className="att-commit-bar">
            <div className="att-commit-summary"><strong>{presentCount}</strong> present · <strong>{absentCount}</strong> absent · {roster.length} students</div>
            <button className="att-save" id="save-register-btn" type="button" onClick={() => openConfirm()} disabled={saving || markingAll}>{saving ? "Saving…" : "Review & save"} <Icon name="arrow" size={15} /></button>
          </div>
        )}

        {quickOpen && (
          <div className="att-sheet-backdrop" onClick={() => setQuickOpen(false)}>
            <div className="att-sheet" onClick={(e) => e.stopPropagation()}>
              <div className="att-sheet-handle" />
              <h2 className="att-sheet-title">Quick present</h2>
              <p className="att-sheet-caption">Paste roll numbers, spaces, commas or new lines. Normal students use their 2/4-digit suffix. LE-01, LE-02 etc. are matched only against LE students.</p>
              <div className="att-quick-grid">
                <textarea className="att-quick-input" value={quickRolls} onChange={(e) => setQuickRolls(e.target.value)} placeholder={'01, 02, 03\n6704, 6707\nLE-01, LE-02'} autoFocus />
                <div className="att-quick-tip"><strong>Examples</strong><br />01 → normal student ending 01<br />6704 → unique normal suffix<br />LE-02 → unique LE student ending 02<br /><br />Ambiguous tokens are ignored.</div>
              </div>
              {quickNote && <div className="att-success" style={{ marginTop: 11 }}>{quickNote}</div>}
              <div className="att-sheet-actions"><button className="att-sheet-cancel" type="button" onClick={() => setQuickOpen(false)}>Done</button><button className="att-sheet-confirm" type="button" onClick={handleQuickMark} disabled={!quickRolls.trim()}>Apply marks</button></div>
            </div>
          </div>
        )}

        {confirmOpen && (
          <div className="att-sheet-backdrop" onClick={() => setConfirmOpen(false)}>
            <div className="att-sheet" onClick={(e) => e.stopPropagation()}>
              <div className="att-sheet-handle" />
              <h2 className="att-sheet-title">Review before saving</h2>
              <p className="att-sheet-caption">This is the final check. Saving will commit the attendance for {session?.attendance_date}.</p>
              <div className="att-confirm-counts">
                <div className="att-confirm-count p"><span className="n">{presentCount}</span><span className="l">Present</span></div>
                <div className="att-confirm-count a"><span className="n">{absentCount}</span><span className="l">Absent</span></div>
              </div>
              <div className="att-toggle-row"><span className="att-toggle-label">Show names and roll numbers</span><button className={`att-switch ${showConfirmList ? "on" : ""}`} type="button" onClick={() => setShowConfirmList((v) => !v)} aria-label="Show attendance list"><span /></button></div>
              {showConfirmList && (
                <div className="att-person-list">
                  {roster.map((r) => <div className="att-person" key={r.roll_no}><div><div className="name">{r.name}</div><div className="roll">{r.roll_no}</div></div><div style={{ color: r.present ? "#168a5a" : "#c83a4a", fontWeight: 850, fontSize: 11 }}>{r.present ? "Present" : "Absent"}</div></div>)}
                </div>
              )}
              <div className="att-sheet-actions"><button className="att-sheet-cancel" type="button" onClick={() => setConfirmOpen(false)}>Go back</button><button className="att-sheet-confirm" type="button" onClick={commitSave} disabled={saving}>{saving ? "Saving…" : "Confirm & save"}</button></div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
