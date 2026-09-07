import { useEffect, useState } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { getAuditLogs, type AuditLogRow } from "../../api/logs";
import { ApiClientError } from "../../api/client";
import { type CurrentUser } from "../../api/auth";

interface Props { user: CurrentUser; onLoggedOut: () => void; }

export function AuditLogPage({ user, onLoggedOut }: Props) {
  const [rows, setRows] = useState<AuditLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"PEOPLE" | "ADMIN">(user.role === "ADMIN" ? "PEOPLE" : "PEOPLE");
  const [actorType, setActorType] = useState("ALL");
  const [activity, setActivity] = useState("ACTIONS");
  const [admin, setAdmin] = useState("");

  async function load() {
    setLoading(true); setError(null);
    try {
      const data = await getAuditLogs({
        actor_type: view === "ADMIN" ? "ADMIN" : actorType,
        activity,
        admin_username: view === "ADMIN" ? admin || undefined : undefined,
      });
      setRows(data);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load audit activity");
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [view, actorType, activity, admin]);

  return (
    <AppShell user={user} activeNav="audit" heading="Audit & Activity" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error} onClose={() => setError(null)} />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
        <button className={`btn btn-sm ${view === "PEOPLE" ? "btn-primary" : "btn-outline"}`} onClick={() => setView("PEOPLE")}>People Activity</button>
        {user.role === "ADMIN" && <button className={`btn btn-sm ${view === "ADMIN" ? "btn-primary" : "btn-outline"}`} onClick={() => setView("ADMIN")}>Admin Activity</button>}
      </div>

      <div className="collapsible" style={{ marginBottom: 16 }}>
        <div className="collapsible-body" style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end" }}>
          {view === "PEOPLE" ? (
            <label style={{ minWidth: 170 }}>
              <span style={{ display: "block", fontSize: 11, fontWeight: 800, marginBottom: 5 }}>WHO</span>
              <select className="input-field" value={actorType} onChange={e => setActorType(e.target.value)}>
                <option value="ALL">Everyone</option><option value="STUDENT">Students</option><option value="FACULTY">Faculty</option><option value="HOD">HOD</option>
              </select>
            </label>
          ) : (
            <label style={{ minWidth: 170 }}>
              <span style={{ display: "block", fontSize: 11, fontWeight: 800, marginBottom: 5 }}>ADMINISTRATOR</span>
              <input className="input-field" placeholder="All administrators" value={admin} onChange={e => setAdmin(e.target.value)} />
            </label>
          )}
          <label style={{ minWidth: 190 }}>
            <span style={{ display: "block", fontSize: 11, fontWeight: 800, marginBottom: 5 }}>ACTIVITY</span>
            <select className="input-field" value={activity} onChange={e => setActivity(e.target.value)}>
              <option value="ACTIONS">Actions only</option><option value="AUTH">Login & Logout</option><option value="ALL">All activity</option>
            </select>
          </label>
        </div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>When</th><th>Person</th><th>What happened</th></tr></thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ whiteSpace: "nowrap", color: "var(--muted)", fontSize: 12 }}>{r.created_at}</td>
                <td>
                  <strong>{r.username}</strong>
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>{r.actor_role || "System"}</div>
                </td>
                <td>{r.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <p className="empty-note">Loading activity…</p>}
        {!loading && rows.length === 0 && <p className="empty-note">No activity matches these filters.</p>}
      </div>
    </AppShell>
  );
}
