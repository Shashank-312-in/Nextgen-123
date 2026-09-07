import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
  approveSmsBatch,
  createSmsGateway,
  getSmsApproval,
  getSmsGateways,
  getSmsLogs,
  getSmsSettings,
  saveSmsSettings,
  testSmsGateway,
  testSmsGatewayConnection,
  updateSmsGateway,
  setSmsGatewayAutoSend,
  approveSmsRow,
  rejectSmsRow,
  getSmsBatches,
  getSmsTemplates,
  saveSmsTemplate,
  sendGeneralNotice,
  type SmsApprovalRow,
  type SmsGateway,
  type SmsLogRow,
  type SmsSettings,
} from "../../api/logs";
import { ApiClientError } from "../../api/client";
import { getFacultyPage, type UserAccount } from "../../api/faculty";
import { AdminStudentSelfEditCard } from "../../components/AdminStudentSelfEditCard";

interface Props {
  user: { username: string; role: string };
  onLoggedOut: () => void;
}

type GatewayForm = {
  gateway_name: string;
  gateway_mode: "cloud" | "local" | "modem";
  device_id: string;
  local_url: string;
  username: string;
  password: string;
  modem_port: string;
  modem_baud: string;
  sim_number: string;
  active: boolean;
  hod_username?: string;
};

const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

const blankGateway: GatewayForm = {
  gateway_name: "SMSGate Phone",
  gateway_mode: "cloud",
  device_id: "",
  local_url: "",
  username: "",
  password: "",
  modem_port: "",
  modem_baud: "115200",
  sim_number: "",
  active: true,
  hod_username: "",
};

function formFromGateway(g: SmsGateway): GatewayForm {
  return {
    gateway_name: g.gateway_name,
    gateway_mode: g.gateway_mode === "local" || g.gateway_mode === "modem" ? g.gateway_mode : "cloud",
    device_id: g.device_id || "",
    local_url: g.local_url || "",
    username: g.username || "",
    password: "",
    modem_port: g.modem_port || "",
    modem_baud: g.modem_baud || "115200",
    sim_number: g.sim_number ? String(g.sim_number) : "",
    active: g.active,
    hod_username: g.hod_username,
  };
}

export function SmsLogPage({ user, onLoggedOut }: Props) {
  const [settings, setSettings] = useState<SmsSettings>({ sms_enabled: "1", sms_daily_cap: "62", sms_absentee_cutoff_time: "10:15" });
  const [messageType, setMessageType] = useState<"ABSENTEE_ALERT" | "GENERAL_NOTICE">("ABSENTEE_ALERT");
  const [templates, setTemplates] = useState<Record<string, string>>({});
  const [composeText, setComposeText] = useState("");
  const [batches, setBatches] = useState<{ id: number; name: string; code: string; student_count: number }[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const [gateways, setGateways] = useState<SmsGateway[]>([]);
  const [gateway, setGateway] = useState<GatewayForm>(blankGateway);
  const [selectedGatewayId, setSelectedGatewayId] = useState<number | null>(null);
  const [hodAccounts, setHodAccounts] = useState<UserAccount[]>([]);
  const [selectedHodUsername, setSelectedHodUsername] = useState("");
  const [approvalDate, setApprovalDate] = useState(today());
  const [approvalRows, setApprovalRows] = useState<SmsApprovalRow[]>([]);
  const [logs, setLogs] = useState<SmsLogRow[]>([]);
  const [testPhone, setTestPhone] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isAdmin = user.role === "ADMIN";
  const currentGateway = useMemo(() => {
    if (isAdmin) {
      return gateways.find((g) => g.hod_username === selectedHodUsername) || null;
    }
    return gateways.find((g) => g.id === selectedGatewayId) || gateways[0] || null;
  }, [gateways, selectedGatewayId, selectedHodUsername, isAdmin]);
  const scopeHodUsername = isAdmin ? selectedHodUsername : user.username;
  const gatewayConfigured = Boolean(currentGateway && (
    (currentGateway.gateway_mode === "cloud" && currentGateway.device_id_configured && currentGateway.username && currentGateway.password_set) ||
    (currentGateway.gateway_mode === "local" && currentGateway.local_url) ||
    (currentGateway.gateway_mode === "modem" && currentGateway.modem_port)
  ));

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [settingsData, gatewayData, logData, approvalData, facultyData] = await Promise.all([
        getSmsSettings(),
        getSmsGateways(),
        getSmsLogs(),
        getSmsApproval(approvalDate),
        isAdmin ? getFacultyPage() : Promise.resolve(null),
      ]);
      setSettings(settingsData);
      setGateways(gatewayData);
      setLogs(logData);
      setApprovalRows(approvalData);
      const templateData = facultyData ? await getSmsTemplates() : await getSmsTemplates();
      setTemplates(templateData);
      setComposeText(templateData[messageType] || "");
      const batchData = await getSmsBatches();
      setBatches(batchData);
      if (selectedBatchId === null && batchData.length) setSelectedBatchId(batchData[0].id);
      setHodAccounts(facultyData ? facultyData.accounts.filter((a) => a.role === "HOD" && a.active) : []);
      if (gatewayData.length) {
        const chosen = isAdmin
          ? (gatewayData.find((g) => g.hod_username === selectedHodUsername) || gatewayData.find((g) => g.id === selectedGatewayId) || gatewayData[0])
          : (gatewayData.find((g) => g.id === selectedGatewayId) || gatewayData[0]);
        setSelectedGatewayId(chosen.id);
        setGateway(formFromGateway(chosen));
        setSelectedHodUsername(chosen.hod_username || "");
      } else {
        setSelectedGatewayId(null);
        setGateway({ ...blankGateway, hod_username: isAdmin ? selectedHodUsername : user.username });
      }
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not load SMS configuration");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [approvalDate]);

  const saveGateway = async () => {
    setBusy("gateway");
    setError(null);
    try {
      const payload = {
        ...gateway,
        ...(isAdmin && !currentGateway ? { hod_username: selectedHodUsername } : {}),
        sim_number: gateway.sim_number ? Number(gateway.sim_number) : null,
      };
      if (isAdmin && !currentGateway && !selectedHodUsername) {
        setError("Select the responsible HOD before creating a gateway.");
        setBusy(null);
        return;
      }
      const saved = currentGateway
        ? await updateSmsGateway(currentGateway.id, payload)
        : await createSmsGateway(payload);
      setGateways((old) => {
        const without = old.filter((g) => g.id !== saved.id);
        return [...without, saved];
      });
      setSelectedGatewayId(saved.id);
      setGateway(formFromGateway(saved));
      setSuccess("SMS gateway configuration saved.");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not save gateway");
    } finally {
      setBusy(null);
    }
  };

  const testConnection = async () => {
    if (!currentGateway) return;
    setBusy("connection");
    setError(null);
    try {
      const result = await testSmsGatewayConnection(currentGateway.id);
      setSuccess(result.mode === "cloud" ? "Cloud credentials and device ID are valid." : "Gateway connection check passed.");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Gateway connection test failed");
    } finally {
      setBusy(null);
    }
  };

  const sendTest = async () => {
    if (!currentGateway) {
      setError("Configure an SMS gateway first.");
      return;
    }
    if (!testPhone.trim()) {
      setError("Enter a test phone number.");
      return;
    }
    setBusy("test-sms");
    setError(null);
    try {
      await testSmsGateway(testPhone.trim(), currentGateway.id);
      setSuccess("Test SMS accepted by the configured gateway.");
      setTestPhone("");
      const nextLogs = await getSmsLogs();
      setLogs(nextLogs);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Test SMS failed");
    } finally {
      setBusy(null);
    }
  };

  const approve = async () => {
    if (!approvalRows.length) return;
    if (!window.confirm(`Approve ${approvalRows.length} absentee SMS message(s) for ${approvalDate}? They can then be sent by the worker.`)) return;
    setBusy("approve");
    setError(null);
    try {
      const result = await approveSmsBatch(approvalDate);
      setSuccess(`${result.approved_count} message(s) approved. The worker may now send them.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not approve SMS batch");
    } finally {
      setBusy(null);
    }
  };

  const saveOperationsSettings = async () => {
    setBusy("settings");
    setError(null);
    try {
      await saveSmsSettings(settings);
      setSuccess("SMS sending settings saved.");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not save SMS settings");
    } finally {
      setBusy(null);
    }
  };

  return (
    <AppShell user={user as any} activeNav="sms-log" heading="Absentee SMS" onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <ToastPopup message={success} onClose={() => setSuccess(null)} />

      <div style={{ display: "grid", gap: 18, maxWidth: 1100, margin: "0 auto" }}>
        <section style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <div style={eyebrow}>SMS ROUTING</div>
              <h2 style={titleStyle}>{isAdmin ? "HOD SMSGate connections" : "Your SMSGate connection"}</h2>
              <p style={muted}>{isAdmin ? "Each HOD has one assigned SMSGate gateway. Choose the responsible HOD to administer that gateway; physical phone location does not affect routing." : "This gateway belongs to your HOD scope. The phone may be physically anywhere; absentee SMS for your students is routed only through this assigned gateway."}</p>
            </div>
            <span style={pill(!currentGateway?.active ? "muted" : gatewayConfigured ? "good" : "bad")}>{!currentGateway?.active ? "INACTIVE" : gatewayConfigured ? "READY" : "NOT CONFIGURED"}</span>
          </div>

          {isAdmin && (
            <div style={{ display: "grid", gap: 7, marginBottom: 14 }}>
              <label style={{ color: "var(--text)", fontSize: 13, fontWeight: 700 }}>Responsible HOD</label>
              <select
                value={scopeHodUsername}
                onChange={(e) => {
                  const username = e.target.value;
                  setSelectedHodUsername(username);
                  const g = gateways.find((x) => x.hod_username === username);
                  if (g) {
                    setSelectedGatewayId(g.id);
                    setGateway(formFromGateway(g));
                  } else {
                    setSelectedGatewayId(null);
                    setGateway({ ...blankGateway, hod_username: username });
                  }
                }}
                style={inputStyle}
              >
                <option value="">Select an HOD</option>
                {hodAccounts.map((h) => <option key={h.username} value={h.username}>{h.full_name || h.username} ({h.username})</option>)}
              </select>
              <p style={muted}>This chooses the HOD whose students and absentee messages use this gateway. Physical phone location does not affect routing.</p>
            </div>
          )}

          {!isAdmin && (
            <div style={{ ...emptyStyle, textAlign: "left", marginBottom: 14 }}>
              <strong style={{ color: "var(--text)" }}>Assigned to you</strong>
              <div style={{ marginTop: 4 }}>{user.username}</div>
              <div style={{ marginTop: 4 }}>Only this HOD's absentee SMS can use this gateway.</div>
            </div>
          )}

          <div style={gridStyle}>
            <Field label="Gateway name"><input style={inputStyle} value={gateway.gateway_name} onChange={(e) => setGateway({ ...gateway, gateway_name: e.target.value })} /></Field>
            <Field label="Mode">
              <select style={inputStyle} value={gateway.gateway_mode} onChange={(e) => setGateway({ ...gateway, gateway_mode: e.target.value as GatewayForm["gateway_mode"] })}>
                <option value="cloud">Cloud Server</option>
                <option value="local">Local Server</option>
                <option value="modem">USB / Serial Modem</option>
              </select>
            </Field>
          </div>

          {gateway.gateway_mode === "cloud" && <div style={gridStyle}>
            <Field label="Device ID"><input style={inputStyle} value={gateway.device_id} onChange={(e) => setGateway({ ...gateway, device_id: e.target.value })} placeholder={currentGateway?.device_id_masked || "Enter device ID"} /></Field>
            <Field label="Cloud username"><input style={inputStyle} value={gateway.username} onChange={(e) => setGateway({ ...gateway, username: e.target.value })} /></Field>
            <Field label={`Cloud password${currentGateway?.password_set ? " (leave blank to keep)" : ""}`}><input type="password" style={inputStyle} value={gateway.password} onChange={(e) => setGateway({ ...gateway, password: e.target.value })} /></Field>
            <Field label="SIM slot (optional)"><input type="number" min={1} max={3} style={inputStyle} value={gateway.sim_number} onChange={(e) => setGateway({ ...gateway, sim_number: e.target.value })} placeholder="1" /></Field>
          </div>}

          {gateway.gateway_mode === "local" && <div style={gridStyle}>
            <Field label="Local server URL"><input style={inputStyle} value={gateway.local_url} onChange={(e) => setGateway({ ...gateway, local_url: e.target.value })} placeholder="http://phone-ip:8080" /></Field>
            <Field label="Username"><input style={inputStyle} value={gateway.username} onChange={(e) => setGateway({ ...gateway, username: e.target.value })} /></Field>
            <Field label="Password"><input type="password" style={inputStyle} value={gateway.password} onChange={(e) => setGateway({ ...gateway, password: e.target.value })} /></Field>
          </div>}

          {gateway.gateway_mode === "modem" && <div style={gridStyle}>
            <Field label="Serial port"><input style={inputStyle} value={gateway.modem_port} onChange={(e) => setGateway({ ...gateway, modem_port: e.target.value })} placeholder="COM3 or /dev/ttyUSB0" /></Field>
            <Field label="Baud rate"><input style={inputStyle} value={gateway.modem_baud} onChange={(e) => setGateway({ ...gateway, modem_baud: e.target.value })} /></Field>
          </div>}

          <label style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, color: "var(--text)", fontWeight: 700 }}>
            <input type="checkbox" checked={gateway.active} onChange={(e) => setGateway({ ...gateway, active: e.target.checked })} /> Gateway enabled
          </label>
          {currentGateway && !isAdmin && (
            <label style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10, color: "var(--text)", fontWeight: 700 }}>
              <input type="checkbox" checked={Boolean(currentGateway.auto_send)} onChange={async (e) => {
                try { const res = await setSmsGatewayAutoSend(currentGateway.id, e.target.checked); setGateways(old => old.map(g => g.id === currentGateway.id ? { ...g, auto_send: res.auto_send } : g)); setSuccess(res.auto_send ? "Auto-send enabled for this gateway scope." : "Auto-send disabled; approval is required."); }
                catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not change auto-send setting"); }
              }} /> Auto-send approved SMS (no manual approval)
            </label>
          )}

          <div style={actionsStyle}>
            <button className="btn btn-primary" onClick={() => void saveGateway()} disabled={busy !== null}>{busy === "gateway" ? "Saving…" : "Save gateway"}</button>
            {currentGateway && <button className="btn btn-outline" onClick={() => void testConnection()} disabled={busy !== null}>{busy === "connection" ? "Testing…" : "Test connection"}</button>}
          </div>
        </section>

        {!isAdmin && <section style={cardStyle}>
          <div style={headerStyle}><div><div style={eyebrow}>MESSAGE COMPOSER</div><h2 style={titleStyle}>Choose what to send</h2></div></div>
          <div style={{ display: "grid", gap: 12 }}>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend style={{ color: "var(--text)", fontWeight: 800, marginBottom: 8 }}>Message Type: ⦿ Absentee Alert ○ General Notice</legend>
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
                <label><input type="radio" checked={messageType === "ABSENTEE_ALERT"} onChange={() => { setMessageType("ABSENTEE_ALERT"); setComposeText(templates.ABSENTEE_ALERT || ""); }} /> Absentee Alert</label>
                <label><input type="radio" checked={messageType === "GENERAL_NOTICE"} onChange={() => { setMessageType("GENERAL_NOTICE"); setComposeText(templates.GENERAL_NOTICE || ""); }} /> General Notice</label>
              </div>
            </fieldset>
            <p style={muted}>{messageType === "ABSENTEE_ALERT" ? "Absentee Alert sends an individual message only to parents of students marked absent. General Notice sends your custom message to every parent in the selected batch, regardless of attendance." : "General Notice sends your custom message to every parent in the selected batch, regardless of attendance."}</p>
            <Field label="Saved message template"><textarea style={{ ...inputStyle, minHeight: 100, resize: "vertical" }} value={composeText} onChange={(e) => setComposeText(e.target.value)} placeholder={messageType === "ABSENTEE_ALERT" ? "Dear Parent, {student} has not attended college today ({date}). - VCET CSD Dept" : "Enter a saved notice; use {student} for personalization if needed."} /></Field>
            <div style={actionsStyle}>
              <button className="btn btn-outline" onClick={async () => { try { const r = await saveSmsTemplate(messageType, composeText); setTemplates(t => ({ ...t, [messageType]: r.template })); setSuccess("Message template saved for this scope."); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not save message template"); } }}>Save template</button>
              {messageType === "GENERAL_NOTICE" && <select style={{ ...inputStyle, width: 260 }} value={selectedBatchId ?? ""} onChange={e => setSelectedBatchId(Number(e.target.value))}>
                <option value="">Select batch</option>{batches.map(b => <option key={b.id} value={b.id}>{b.code || b.name} ({b.student_count})</option>)}
              </select>}
              {messageType === "GENERAL_NOTICE" && <button className="btn btn-primary" disabled={busy !== null || !selectedBatchId || !composeText.trim()} onClick={async () => { if (!selectedBatchId) return; if (!window.confirm("Queue this General Notice for every parent in the selected batch?")) return; setBusy("general"); try { const r = await sendGeneralNotice(selectedBatchId, composeText); setSuccess(`${r.queued_count} General Notice message(s) queued.`); await load(); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not queue General Notice"); } finally { setBusy(null); } }}>{busy === "general" ? "Queuing…" : "Queue General Notice"}</button>}
            </div>
          </div>
        </section>}

        <section style={cardStyle}>
          <div style={headerStyle}>
            <div><div style={eyebrow}>SAFETY GATE</div><h2 style={titleStyle}>Review before sending</h2><p style={muted}>Attendance only creates a queued batch. Nothing is sent until this batch is approved. {isAdmin ? "You are viewing the college-wide approval scope." : "You are viewing only your HOD scope."}</p></div>
            <input type="date" value={approvalDate} onChange={(e) => setApprovalDate(e.target.value)} style={{ ...inputStyle, width: 170 }} />
          </div>
          {approvalRows.length === 0 ? <div style={emptyStyle}>No unapproved absentee SMS messages for this date.</div> : <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 12 }}>
              <strong style={{ color: "var(--text)" }}>{approvalRows.length} message(s) awaiting approval</strong>
              <button className="btn btn-primary" onClick={() => void approve()} disabled={busy !== null}>{busy === "approve" ? "Approving…" : "Approve batch"}</button>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              {approvalRows.map((r) => <div key={r.id} style={rowStyle}>
                <div><strong style={{ color: "var(--text)" }}>{r.roll_no} — {r.student_name}</strong><div style={muted}>{r.parent_phone}</div></div>
                <div style={{ flex: 1, color: "var(--text)", fontSize: 13 }}>{r.message}</div>
                <div style={{ minWidth: 220, textAlign: "right" }}><div><span style={pill(r.gateway_id && r.gateway_active && !r.error ? "good" : "bad")}>{r.error ? "BLOCKED" : r.gateway_name || "NO GATEWAY"}</span></div><div style={{ ...muted, marginTop: 4 }}>{r.hod_username || "No HOD"}</div><div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}><button className="btn btn-sm btn-primary" disabled={busy !== null || Boolean(r.error)} onClick={async () => { if (!window.confirm(`Approve SMS for ${r.student_name}?`)) return; setBusy(`approve-${r.id}`); try { await approveSmsRow(r.id); setSuccess(`SMS approved for ${r.roll_no}.`); await load(); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not approve SMS"); } finally { setBusy(null); } }}>Approve</button><button className="btn btn-sm btn-outline" disabled={busy !== null} onClick={async () => { if (!window.confirm(`Reject SMS for ${r.student_name}? It will remain in the audit trail.`)) return; setBusy(`reject-${r.id}`); try { await rejectSmsRow(r.id); setSuccess(`SMS rejected for ${r.roll_no}.`); await load(); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not reject SMS"); } finally { setBusy(null); } }}>Reject</button></div></div>
              </div>)}
            </div>
          </>}
        </section>

        {(isAdmin || user.username === "admin") && (
          <AdminStudentSelfEditCard
            onNotification={(msg, type) => {
              if (type === "success") setSuccess(msg);
              else setError(msg);
            }}
          />
        )}

        <section style={cardStyle}>
          <div style={headerStyle}><div><div style={eyebrow}>OPERATIONS</div><h2 style={titleStyle}>Sending controls</h2></div></div>
          <div style={gridStyle}>
            <Field label="Daily SMS cap"><input type="number" min={1} style={inputStyle} value={settings.sms_daily_cap} onChange={(e) => setSettings({ ...settings, sms_daily_cap: e.target.value })} /></Field>
            <Field label="Absentee cutoff (HH:MM)"><input type="time" style={inputStyle} value={settings.sms_absentee_cutoff_time} onChange={(e) => setSettings({ ...settings, sms_absentee_cutoff_time: e.target.value })} /></Field>
            <Field label="Automatic worker"><select style={inputStyle} value={settings.sms_enabled} onChange={(e) => setSettings({ ...settings, sms_enabled: e.target.value })}><option value="1">Enabled</option><option value="0">Disabled</option></select></Field>
            <Field label="Test recipient"><input style={inputStyle} value={testPhone} onChange={(e) => setTestPhone(e.target.value)} placeholder="10-digit mobile number" /></Field>
          </div>
          <div style={actionsStyle}>
            <button className="btn btn-primary" onClick={() => void saveOperationsSettings()} disabled={busy !== null}>{busy === "settings" ? "Saving…" : "Save settings"}</button>
            <button className="btn btn-outline" onClick={() => void sendTest()} disabled={busy !== null || !currentGateway}>{busy === "test-sms" ? "Sending…" : "Send test SMS"}</button>
          </div>
          <p style={{ ...muted, marginTop: 12 }}>A test SMS is independent of the absentee approval queue and uses only the currently selected HOD gateway. It never changes absentee routing.</p>
        </section>

        <section style={cardStyle}>
          <div style={headerStyle}><div><div style={eyebrow}>HISTORY</div><h2 style={titleStyle}>Recent SMS activity</h2></div></div>
          {loading ? <div style={emptyStyle}>Loading…</div> : logs.length === 0 ? <div style={emptyStyle}>No SMS activity yet.</div> : <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", color: "var(--text)" }}>
              <thead><tr>{["Date", "Student", "Gateway", "Status", "Error"].map((h) => <th key={h} style={thStyle}>{h}</th>)}</tr></thead>
              <tbody>{logs.map((r) => <tr key={r.id}><td style={tdStyle}>{r.created_at}</td><td style={tdStyle}>{r.roll_no}{r.student_name ? ` — ${r.student_name}` : ""}</td><td style={tdStyle}>{r.gateway_name || "Unassigned"}</td><td style={tdStyle}><span style={pill(r.status === "SENT" ? "good" : r.status === "FAILED" ? "bad" : "muted")}>{r.status}</span></td><td style={{ ...tdStyle, color: "var(--muted)" }}>{r.error || "—"}</td></tr>)}</tbody>
            </table>
          </div>}
        </section>
      </div>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label style={{ display: "grid", gap: 7, color: "var(--text)", fontSize: 13, fontWeight: 700 }}>{label}{children}</label>;
}

const cardStyle: CSSProperties = { background: "var(--card-glass)", border: "1px solid var(--border)", borderRadius: 18, padding: 20, boxShadow: "0 8px 28px rgba(0,0,0,.08)" };
const headerStyle: CSSProperties = { display: "flex", justifyContent: "space-between", gap: 18, alignItems: "flex-start", marginBottom: 18 };
const titleStyle: CSSProperties = { margin: "3px 0 5px", color: "var(--text)", fontSize: 21 };
const muted: CSSProperties = { color: "var(--muted)", fontSize: 13, lineHeight: 1.5, margin: 0 };
const eyebrow: CSSProperties = { color: "var(--heading-accent)", fontSize: 11, fontWeight: 900, letterSpacing: 1.4 };
const gridStyle: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 14 };
const inputStyle: CSSProperties = { width: "100%", boxSizing: "border-box", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)" };
const actionsStyle: CSSProperties = { display: "flex", gap: 10, flexWrap: "wrap", marginTop: 16 };
const emptyStyle: CSSProperties = { padding: 18, borderRadius: 12, background: "var(--chip-bg-muted)", color: "var(--muted)", textAlign: "center" };
const rowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 14, padding: 12, border: "1px solid var(--border)", borderRadius: 12, flexWrap: "wrap" };
const thStyle: CSSProperties = { textAlign: "left", padding: "9px 8px", borderBottom: "1px solid var(--border)", fontSize: 11, color: "var(--muted)", textTransform: "uppercase" };
const tdStyle: CSSProperties = { padding: "10px 8px", borderBottom: "1px solid var(--border)", fontSize: 12, verticalAlign: "top" };

function pill(kind: "good" | "bad" | "muted"): CSSProperties {
  return {
    display: "inline-flex", padding: "4px 8px", borderRadius: 999, fontSize: 10, fontWeight: 900, letterSpacing: .5,
    background: kind === "good" ? "rgba(16,185,129,.12)" : kind === "bad" ? "rgba(239,68,68,.12)" : "var(--chip-bg-muted)",
    color: kind === "good" ? "#059669" : kind === "bad" ? "#dc2626" : "var(--muted)"
  };
}
