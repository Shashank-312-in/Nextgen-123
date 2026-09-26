import { useEffect, useMemo, useState } from "react";
import { type CurrentUser } from "../../api/auth";
import { getTimetables, getDaySchedule, type TimetablePeriod, type TimetableRecord, type DayScheduleEntry } from "../../api/timetable";
import { ApiClientError } from "../../api/client";
import { ErrorPopup } from "../../components/ErrorPopup";
import "./schedule-view.css";

const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"] as const;
const DAY_LABELS: Record<(typeof DAYS)[number], string> = {
  MON: "Mon",
  TUE: "Tue",
  WED: "Wed",
  THU: "Thu",
  FRI: "Fri",
  SAT: "Sat",
};
const FULL_DAY_NAMES: Record<(typeof DAYS)[number], string> = {
  MON: "Monday",
  TUE: "Tuesday",
  WED: "Wednesday",
  THU: "Thursday",
  FRI: "Friday",
  SAT: "Saturday",
};
const PALETTE: Array<[string, string]> = [
  ["#dceafa", "#3976b9"],
  ["#dcefe5", "#398563"],
  ["#f8e8c9", "#ad7822"],
  ["#f4dfdf", "#b65b62"],
  ["#d9eeee", "#368b8a"],
  ["#e9e2f5", "#8064aa"],
  ["#f7e1e8", "#b64e70"],
  ["#f5e7d8", "#b77b3e"],
  ["#e3e9fb", "#6179c4"],
  ["#e1e9f7", "#536fae"],
];

type Props = { user: CurrentUser; onManage: () => void };
type View = "agenda" | "week";
type Scope = "department" | "mine";

type WeekCellEntry = {
  entry: NonNullable<TimetableRecord["entries"]>[number];
  record: TimetableRecord;
  period: TimetablePeriod;
};

function dateISO(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function mondayOf(d: Date) {
  const x = new Date(d);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  x.setHours(12, 0, 0, 0);
  return x;
}

function timeLabel(start?: string | null, end?: string | null) {
  if (!start || !end) return "";
  return `${start.slice(0, 5)}–${end.slice(0, 5)}`;
}

function subjectLabel(entry: { subject_name?: string | null; custom_label?: string | null; block_type?: string | null }) {
  return entry.subject_name || entry.custom_label || entry.block_type || "Scheduled class";
}

function subjectKey(entry: { subject_name?: string | null; custom_label?: string | null; block_type?: string | null }) {
  return subjectLabel(entry).trim().toLowerCase();
}

function stableColor(subject: string): [string, string] {
  let hash = 0;
  for (let i = 0; i < subject.length; i += 1) hash = (hash * 31 + subject.charCodeAt(i)) | 0;
  return PALETTE[Math.abs(hash) % PALETTE.length];
}


function classLabel(record: TimetableRecord | undefined, sectionOverride?: string | null) {
  if (!record) return sectionOverride ? `Section ${sectionOverride}` : "Class";
  const code = String(record.semester_code || "").trim().toUpperCase();
  const yearToken = code.split("-")[0].replace(/[^IVX]/g, "");
  const yearMap: Record<string, string> = { I: "1st Year", II: "2nd Year", III: "3rd Year", IV: "4th Year" };
  const year = yearMap[yearToken] || String(record.semester_name || record.semester_code || "Semester");
  return `${year} CSD · Section ${record.section_name}`;
}

function sectionPeriods(periods: TimetablePeriod[], section: "MORNING" | "AFTERNOON") {
  return periods.filter((p) => p.section === section);
}

function entryForSlot(record: TimetableRecord, day: string, section: "MORNING" | "AFTERNOON", slot: number) {
  return record.entries.find((entry) =>
    entry.day === day &&
    entry.section === section &&
    slot >= entry.start_slot &&
    slot < entry.start_slot + entry.duration,
  );
}

function getEntryStartPeriod(record: TimetableRecord, entry: TimetableRecord["entries"][number]) {
  const periods = sectionPeriods(record.periods, entry.section);
  return periods[entry.start_slot] || periods[0] || null;
}

export function ScheduleView({ user, onManage }: Props) {
  const isHod = user.role === "HOD";
  const isFaculty = user.role === "FACULTY";
  const [view, setView] = useState<View>("agenda");
  const [scope, setScope] = useState<Scope>("department");
  const [date, setDate] = useState(() => new Date());
  const [records, setRecords] = useState<TimetableRecord[]>([]);
  const [agenda, setAgenda] = useState<DayScheduleEntry[]>([]);
  const [periodsDefault, setPeriodsDefault] = useState<TimetablePeriod[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);

  const effectiveScope: Scope = isHod ? scope : "mine";

  useEffect(() => {
    let live = true;
    setBusy(true);
    getTimetables({
      schedule_view: true,
      scope: isHod && effectiveScope === "mine" ? "mine" : undefined,
    })
      .then((data) => {
        if (!live) return;
        setRecords(data.timetables || []);
        setPeriodsDefault(data.periods_default || []);
      })
      .catch((err) => {
        if (live) setError(err instanceof ApiClientError ? err.message : "Could not load schedule");
      })
      .finally(() => {
        if (live) setBusy(false);
      });
    return () => {
      live = false;
    };
  }, [user.username, isHod, effectiveScope]);

  useEffect(() => {
    let live = true;
    getDaySchedule(dateISO(date))
      .then((data) => {
        if (live) setAgenda(data.entries || []);
      })
      .catch((err) => {
        if (live) setError(err instanceof ApiClientError ? err.message : "Could not load agenda");
      });
    return () => {
      live = false;
    };
  }, [date, user.username]);

  useEffect(() => {
    if (!isHod) setScope("mine");
  }, [isHod]);

  const visibleRecords = useMemo(() => {
    return records
      .map((record) => ({
        ...record,
        entries: record.entries.filter((entry) => !isFaculty || entry.faculty_username?.toLowerCase() === user.username.toLowerCase()),
      }))
      .map((record) => ({
        ...record,
        entries: isHod && scope === "mine"
          ? record.entries.filter((entry) => entry.faculty_username?.toLowerCase() === user.username.toLowerCase())
          : record.entries,
      }))
      .filter((record) => record.entries.length > 0);
  }, [records, isFaculty, isHod, scope, user.username]);

  const displayPeriods = useMemo(() => {
    const fromRecord = visibleRecords.find((record) => record.periods.length)?.periods;
    const fromData = fromRecord && fromRecord.length ? fromRecord : periodsDefault;
    const seen = new Set<string>();
    return fromData.filter((period) => {
      if (seen.has(period.key)) return false;
      seen.add(period.key);
      return true;
    });
  }, [periodsDefault, visibleRecords]);

  const morningPeriods = useMemo(() => sectionPeriods(displayPeriods, "MORNING"), [displayPeriods]);
  const afternoonPeriods = useMemo(() => sectionPeriods(displayPeriods, "AFTERNOON"), [displayPeriods]);
  const lunchStart = morningPeriods.at(-1)?.end || "12:35";
  const lunchEnd = afternoonPeriods[0]?.start || "13:20";

  const subjectNames = useMemo(() => {
    const names = new Map<string, string>();
    visibleRecords.forEach((record) => {
      record.entries.forEach((entry) => {
        const label = subjectLabel(entry);
        const key = subjectKey(entry);
        if (!names.has(key)) names.set(key, label);
      });
    });
    return Array.from(names.values()).sort((a, b) => a.localeCompare(b));
  }, [visibleRecords]);

  const weekStart = mondayOf(date);
  const weekDates = DAYS.map((_, i) => {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + i);
    return d;
  });

  const agendaDay = FULL_DAY_NAMES[DAYS[(date.getDay() + 6) % 7]];
  const shownAgenda = useMemo(() => {
    return agenda.filter((entry) => {
      if (isFaculty) return entry.regular_faculty_username?.toLowerCase() === user.username.toLowerCase();
      if (isHod && scope === "mine") return entry.regular_faculty_username?.toLowerCase() === user.username.toLowerCase();
      return true;
    });
  }, [agenda, isFaculty, isHod, scope, user.username]);

  const weekEntries = useMemo<WeekCellEntry[]>(() => {
    const result: WeekCellEntry[] = [];
    visibleRecords.forEach((record) => {
      record.entries.forEach((entry) => {
        const startPeriod = getEntryStartPeriod(record, entry);
        if (startPeriod) result.push({ entry, record, period: startPeriod });
      });
    });
    return result;
  }, [visibleRecords]);

  const subtitle = isHod
    ? scope === "department" ? "Department schedule" : "My Classes"
    : "Your teaching schedule";

  const dateLabel = view === "agenda"
    ? date.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })
    : `${weekDates[0].toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${weekDates[5].toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;

  function moveDate(delta: number) {
    setDate((current) => {
      const next = new Date(current);
      next.setDate(next.getDate() + delta);
      return next;
    });
  }

  function renderSubjectBlock(entry: TimetableRecord["entries"][number], record: TimetableRecord, showFaculty: boolean) {
    const subject = subjectLabel(entry);
    const [tint, color] = stableColor(subject);
    return (
      <div className="sv-subject-block" style={{ "--sv-subject": color, "--sv-tint": tint } as React.CSSProperties}>
        <strong>{subject}</strong>
        {showFaculty && <span>{entry.faculty_name || ""}</span>}
        <em>{classLabel(record)}</em>
      </div>
    );
  }

  function renderWeekSection(day: (typeof DAYS)[number], section: "MORNING" | "AFTERNOON", periods: TimetablePeriod[]) {
    const recordFor = (period: TimetablePeriod, slot: number) => {
      const candidates = weekEntries.filter((item) => item.entry.day === day && item.entry.section === section && item.entry.start_slot === slot);
      return candidates[0] || null;
    };

    const cells: JSX.Element[] = [];
    let index = 0;
    while (index < periods.length) {
      const current = recordFor(periods[index], index);
      if (!current) {
        cells.push(<td key={`${day}-${section}-${index}`} />);
        index += 1;
        continue;
      }

      const availableSpan = periods.length - index;
      const requestedSpan = Math.max(1, Math.min(current.entry.duration, availableSpan));
      const [sameLabel, sameFaculty] = [subjectLabel(current.entry), current.entry.faculty_username || ""];
      let span = requestedSpan;
      while (span < availableSpan) {
        const next = recordFor(periods[index + span], index + span);
        if (!next) break;
        if (subjectLabel(next.entry) !== sameLabel || (next.entry.faculty_username || "") !== sameFaculty || next.record.id !== current.record.id) break;
        span += 1;
      }

      cells.push(
        <td key={`${day}-${section}-${index}`} colSpan={span}>
          {renderSubjectBlock(current.entry, current.record, isHod && scope === "department")}
        </td>,
      );
      index += span;
    }
    return cells;
  }

  return (
    <section className="schedule-view">
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <header className="sv-head">
        <div>
          <div className="sv-kicker">ACADEMIC WORKSPACE</div>
          <h2>Schedule</h2>
          <p>{subtitle} · {view === "agenda" ? "Today" : "Week"}</p>
        </div>
      </header>

      <section className="sv-panel">
        <div className="sv-toolbar">
          <div className="sv-tabs">
            <button className={view === "agenda" ? "active" : ""} onClick={() => setView("agenda")}>Today · Agenda</button>
            <button className={view === "week" ? "active" : ""} onClick={() => setView("week")}>Week view</button>
          </div>
          <div className="sv-tools">
            <button className="sv-btn sv-icon" aria-label="Previous" onClick={() => moveDate(view === "week" ? -7 : -1)}>‹</button>
            <div className="sv-date-label">{dateLabel}</div>
            <button className="sv-btn sv-icon" aria-label="Next" onClick={() => moveDate(view === "week" ? 7 : 1)}>›</button>
            <button className="sv-btn" onClick={() => setDate(new Date())}>Today</button>
            {isHod && (
              <div className="sv-menu-wrap">
                <button className="sv-btn sv-icon" aria-label="More actions" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>⋮</button>
                {menuOpen && (
                  <div className="sv-menu">
                    <button onClick={() => { setMenuOpen(false); onManage(); }}>Edit timetable</button>
                    <button onClick={() => { setMenuOpen(false); onManage(); }}>Save draft</button>
                    <button onClick={() => { setMenuOpen(false); onManage(); }}>Publish timetable</button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {isHod && (
          <div className="sv-scope">
            <span>SCHEDULE</span>
            <button className={scope === "department" ? "active" : ""} onClick={() => setScope("department")}>Department</button>
            <button className={scope === "mine" ? "active" : ""} onClick={() => setScope("mine")}>My Classes</button>
            <span className="sv-scope-hint">{scope === "department" ? "All scheduled department classes" : "Your assigned teaching classes"}</span>
          </div>
        )}

        {busy ? (
          <div className="sv-empty">Loading schedule…</div>
        ) : view === "agenda" ? (
          <div className="sv-agenda">
            <div className="sv-dayline">
              <strong>{agendaDay} · Today</strong>
              <span>{shownAgenda.length} {shownAgenda.length === 1 ? "class" : "classes"}</span>
            </div>
            {shownAgenda.length ? shownAgenda.map((entry, index) => {
              const subject = subjectLabel(entry);
              const [tint, color] = stableColor(subject);
              return (
                <article
                  className="sv-agenda-row"
                  key={`${entry.timetable_entry_id}-${index}`}
                  style={{ "--sv-subject": color, "--sv-tint": tint } as React.CSSProperties}
                >
                  <div className="sv-time">{timeLabel(entry.start_time, entry.end_time)}<small>{entry.section === "AFTERNOON" ? "Afternoon" : "Class period"}</small></div>
                  <div className="sv-class"><div className="sv-classname">{subject}</div><div className="sv-faculty">{isHod && scope === "department" ? (entry.regular_faculty_name || entry.substitute_faculty_name || "Faculty not assigned") : "Tap to open attendance"}</div></div>
                  <div className="sv-meta"><span className="sv-badge">{classLabel(visibleRecords.find((record) => record.id === entry.timetable_id), entry.section_name)}</span>{(isHod && scope !== "department") || isFaculty ? <span className="sv-tag">My class</span> : null}</div>
                </article>
              );
            }) : <div className="sv-empty-inline">No classes scheduled for this day.</div>}
          </div>
        ) : (
          <>
            <div className="sv-week-wrap">
              <table className="sv-week-table">
                <thead>
                  <tr>
                    <th>DAY</th>
                    {morningPeriods.map((period) => <th key={period.key}>{timeLabel(period.start, period.end)}<small>{period.label}</small></th>)}
                    <th className="sv-lunch-head">LUNCH<br />{lunchStart}–{lunchEnd}</th>
                    {afternoonPeriods.map((period) => <th key={period.key}>{timeLabel(period.start, period.end)}<small>{period.label}</small></th>)}
                  </tr>
                </thead>
                <tbody>
                  {DAYS.map((day, dayIndex) => (
                    <tr key={day}>
                      <th scope="row">{DAY_LABELS[day].toUpperCase()}<small>{weekDates[dayIndex].getDate()}</small></th>
                      {renderWeekSection(day, "MORNING", morningPeriods)}
                      {dayIndex === 0 && <td className="sv-lunch-cell" rowSpan={DAYS.length}><span>L U N C H&nbsp; B R E A K</span></td>}
                      {renderWeekSection(day, "AFTERNOON", afternoonPeriods)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="sv-legend">
              {subjectNames.map((name) => {
                const [, color] = stableColor(name);
                return <span key={name}><i style={{ "--sv-dot": color } as React.CSSProperties} />{name}</span>;
              })}
            </div>
          </>
        )}
      </section>
    </section>
  );
}
