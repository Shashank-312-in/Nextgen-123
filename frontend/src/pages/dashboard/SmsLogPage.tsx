import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ToastPopup } from "../../components/ToastPopup";
import {
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
  approveSmsBatch,
  getSmsBatches,
  getSmsTemplates,
  saveSmsTemplate,
  sendGeneralNotice,
  getMySmsAccess,
  type SmsApprovalRow,
  type SmsGateway,
  type SmsLogRow,
  type SmsSettings,
  type SmsBatch,
  type SmsAccessMe,
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

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

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
  const isAdmin = user.role === "ADMIN";
  const isHod = user.role === "HOD";
  const isFaculty = user.role === "FACULTY";

  const [settings, setSettings] = useState<SmsSettings>({ sms_enabled: "1", sms_daily_cap: "1000", sms_absentee_cutoff_time: "10:15" });
  const [messageType, setMessageType] = useState<"ABSENTEE_ALERT" | "GENERAL_NOTICE">("ABSENTEE_ALERT");
  const [templates, setTemplates] = useState<Record<string, string>>({});
  const [composeText, setComposeText] = useState("");
  const [batches, setBatches] = useState<SmsBatch[]>([]);
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
  const [facultyAccess, setFacultyAccess] = useState<SmsAccessMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const currentGateway = useMemo(() => {
    if (isAdmin) return gateways.find((g) => g.hod_username === selectedHodUsername) || null;
    if (isFaculty) return gateways.find((g) => g.owner_username === user.username) || gateways[0] || null;
    return gateways.find((g) => g.id === selectedGatewayId) || gateways[0] || null;
  }, [gateways, selectedGatewayId, selectedHodUsername, isAdmin, isFaculty, user.username]);

  const gatewayConfigured = Boolean(currentGateway && (
    (currentGateway.gateway_mode === "cloud" && currentGateway.device_id_configured && currentGateway.username && currentGateway.password_set) ||
    (currentGateway.gateway_mode === "local" && currentGateway.local_url) ||
    (currentGateway.gateway_mode === "modem" && currentGateway.modem_port)
  ));

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      if (isFaculty) {
        const access = await getMySmsAccess();
        setFacultyAccess(access);
        if (!access.enabled) {
          setGateways([]);
          setBatches([]);
          setLogs([]);
          return;
        }
        const [gatewayData, logData, batchData, templateData] = await Promise.all([
          getSmsGateways(), getSmsLogs(), getSmsBatches(), getSmsTemplates(),
        ]);
        setGateways(gatewayData);
        setLogs(logData);
        setBatches(batchData);
        setTemplates(templateData);
        setComposeText(templateData.GENERAL_NOTICE || "Dear Parent, {student}: {message} - VCET CSD Dept");
        const chosen = gatewayData.find((g) => g.owner_username === user.username) || gatewayData[0];
        if (chosen) {
          setSelectedGatewayId(chosen.id);
          setGateway(formFromGateway(chosen));
        } else {
          setSelectedGatewayId(null);
          setGateway({ ...blankGateway, hod_username: access.hod_username || "" });
        }
        if (selectedBatchId === null && batchData.length) setSelectedBatchId(batchData[0].id);
        return;
      }

      const [settingsData, gatewayData, logData, approvalData, templateData, batchData, facultyData] = await Promise.all([
        getSmsSettings(), getSmsGateways(), getSmsLogs(), getSmsApproval(approvalDate), getSmsTemplates(), getSmsBatches(),
        isAdmin ? getFacultyPage() : Promise.resolve(null),
      ]);
      setSettings(settingsData);
      setGateways(gatewayData);
      setLogs(logData);
      setApprovalRows(approvalData);
      setTemplates(templateData);
      setComposeText(templateData[messageType] || "");
      setBatches(batchData);
      if (selectedBatchId === null && batchData.length) setSelectedBatchId(batchData[0].id);
      const facultyHods = facultyData ? facultyData.accounts.filter((a) => a.role === "HOD" && a.active) : [];
      // Keep the Admin HOD selector usable even when the Faculty roster is
      // temporarily unavailable: the gateway response itself carries the
      // authoritative HOD scope for already-configured gateways.
      const fallbackHods = gatewayData
        .map((g) => g.hod_username)
        .filter((u, i, all) => Boolean(u) && all.indexOf(u) === i)
        .map((username) => ({ username, full_name: username, role: "HOD", active: true } as UserAccount));
      setHodAccounts(facultyHods.length ? facultyHods : fallbackHods);
      if (gatewayData.length) {
        const chosen = isAdmin
          ? (gatewayData.find((g) => g.hod_username === selectedHodUsername) || gatewayData[0])
          : (gatewayData.find((g) => g.id === selectedGatewayId) || gatewayData[0]);
        setSelectedGatewayId(chosen.id);
        setGateway(formFromGateway(chosen));
        if (isAdmin) setSelectedHodUsername(chosen.hod_username || "");
      } else {
        setSelectedGatewayId(null);
        setGateway({ ...blankGateway, hod_username: isAdmin ? selectedHodUsername : user.username });
      }
    } catch (err) {
      if (isFaculty && err instanceof ApiClientError && err.status === 403) {
        setFacultyAccess({ enabled: false, hod_username: null, allowed_batches: [], gateway_configured: false });
        setError(err.message);
      } else {
        setError(err instanceof ApiClientError ? err.message : "Could not load SMS configuration");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [approvalDate]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveGateway = async () => {
    setBusy("gateway"); setError(null);
    try {
      const payload = {
        ...gateway,
        ...(isAdmin && !currentGateway ? { hod_username: selectedHodUsername } : {}),
        sim_number: gateway.sim_number ? Number(gateway.sim_number) : null,
      };
      if (isAdmin && !currentGateway && !selectedHodUsername) {
        setError("Select the responsible HOD before creating a gateway."); setBusy(null); return;
      }
      const saved = currentGateway ? await updateSmsGateway(currentGateway.id, payload) : await createSmsGateway(payload);
      setGateways((old) => [...old.filter((g) => g.id !== saved.id), saved]);
      setSelectedGatewayId(saved.id); setGateway(formFromGateway(saved));
      setSuccess("SMS gateway configuration saved.");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Could not save gateway");
    } finally { setBusy(null); }
  };

  const testConnection = async () => {
    if (!currentGateway) return;
    setBusy("connection"); setError(null);
    try {
      const result = await testSmsGatewayConnection(currentGateway.id);
      setSuccess(result.mode === "cloud" ? "Cloud credentials and device ID are valid." : "Gateway connection check passed.");
    } catch (err) { setError(err instanceof ApiClientError ? err.message : "Gateway connection test failed"); }
    finally { setBusy(null); }
  };

  const sendTest = async () => {
    if (!currentGateway) { setError("Configure an SMS gateway first."); return; }
    if (!testPhone.trim()) { setError("Enter a test phone number."); return; }
    setBusy("test-sms"); setError(null);
    try {
      await testSmsGateway(testPhone.trim(), currentGateway.id);
      setSuccess("Test SMS accepted by the configured gateway."); setTestPhone(""); setLogs(await getSmsLogs());
    } catch (err) { setError(err instanceof ApiClientError ? err.message : "Test SMS failed"); }
    finally { setBusy(null); }
  };

  const sendGeneral = async () => {
    if (!selectedBatchId || !composeText.trim()) return;
    if (!window.confirm(isFaculty ? "Send this SMS to every parent in the selected delegated batch?" : "Queue this General Notice for every parent in the selected batch?")) return;
    setBusy("general"); setError(null);
    try {
      const result = await sendGeneralNotice(selectedBatchId, composeText);
      setSuccess(`${result.queued_count} message(s) queued.`);
      await load();
    } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not queue SMS"); }
    finally { setBusy(null); }
  };

  const approve = async () => {
    if (!approvalRows.length) return;
    if (!window.confirm(`Approve ${approvalRows.length} absentee SMS message(s) for ${approvalDate}?`)) return;
    setBusy("approve"); setError(null);
    try { const result = await approveSmsBatch(approvalDate); setSuccess(`${result.approved_count} message(s) approved.`); await load(); }
    catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not approve SMS batch"); }
    finally { setBusy(null); }
  };

  const saveOperationsSettings = async () => {
    setBusy("settings"); setError(null);
    try { await saveSmsSettings(settings); setSuccess("SMS sending settings saved."); }
    catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not save SMS settings"); }
    finally { setBusy(null); }
  };

  if (isFaculty && !loading && facultyAccess && !facultyAccess.enabled) {
    return (
      <AppShell user={user as any} activeNav="sms-log" heading="SMS Gateway" onLoggedOut={onLoggedOut}>
        <ErrorPopup message={error} onClose={() => setError(null)} />
        <div style={{ ...cardStyle, maxWidth: 760, margin: "48px auto" }}>
          <div style={eyebrow}>SMS GATEWAY ACCESS</div>
          <h2 style={titleStyle}>Access not granted</h2>
          <p style={muted}>Your HOD has not granted SMS Gateway permission to this Faculty account. No gateway, batch or recipient controls are available until delegation is enabled.</p>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell user={user as any} activeNav="sms-log" heading={isFaculty ? "SMS Gateway" : "Absentee SMS"} onLoggedOut={onLoggedOut}>
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <ToastPopup message={success} onClose={() => setSuccess(null)} />
      <div style={{ display: "grid", gap: 18, maxWidth: 1100, margin: "0 auto" }}>

        {isFaculty && facultyAccess && (
          <section style={cardStyle}>
            <div style={headerStyle}>
              <div><div style={eyebrow}>SMS ACCESS</div><h2 style={titleStyle}>Delegated batches</h2><p style={muted}>Your SMS permission is owned by your HOD. Recipient selection is restricted to the batches shown here and is rechecked by the server on every send.</p></div>
              <span style={pill("good")}>ENABLED</span>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {facultyAccess.allowed_batches.map((b) => <span key={b.id} style={batchPillStyle}>{b.code || b.name} · {b.student_count}</span>)}
            </div>
            {facultyAccess.allowed_batches.length === 0 && <div style={emptyStyle}>No batches have been delegated. Your gateway is not usable until at least one batch is assigned.</div>}
          </section>
        )}

        <section style={cardStyle}>
          <div style={headerStyle}>
            <div>
              <div style={eyebrow}>SMS ROUTING</div>
              <h2 style={titleStyle}>{isAdmin ? "HOD SMSGate connections" : isFaculty ? "Your SMSGate connection" : "Your SMSGate connection"}</h2>
              <p style={muted}>{isAdmin ? "Choose the responsible HOD to administer that HOD's gateway. Physical phone location does not affect routing." : isFaculty ? "This gateway is owned by your Faculty account. You may configure only your own credentials." : "This gateway belongs to your HOD scope."}</p>
            </div>
            <span style={pill(!currentGateway?.active ? "muted" : gatewayConfigured ? "good" : "bad")}>{!currentGateway?.active ? "INACTIVE" : gatewayConfigured ? "READY" : "NOT CONFIGURED"}</span>
          </div>

          {isAdmin && (
            <div style={{ display: "grid", gap: 7, marginBottom: 14 }}>
              <label style={fieldLabel}>Responsible HOD</label>
              <select value={selectedHodUsername} onChange={(e) => { const username = e.target.value; setSelectedHodUsername(username); const g = gateways.find((x) => x.hod_username === username); if (g) { setSelectedGatewayId(g.id); setGateway(formFromGateway(g)); } else { setSelectedGatewayId(null); setGateway({ ...blankGateway, hod_username: username }); } }} style={inputStyle}>
                <option value="">Select an HOD</option>
                {hodAccounts.map((h) => <option key={h.username} value={h.username}>{h.full_name || h.username} ({h.username})</option>)}
              </select>
              {!hodAccounts.length && <p style={muted}>No active HOD accounts were returned. Check the Faculty account roster.</p>}
            </div>
          )}

          {isFaculty && !currentGateway && <div style={{ ...emptyStyle, textAlign: "left", marginBottom: 14 }}><strong style={{ color: "var(--text)" }}>No gateway configured yet.</strong><div style={{ marginTop: 4 }}>Add your own gateway below. Other Faculty gateway credentials are never exposed to this account.</div></div>}

          <div style={gridStyle}>
            <Field label="Gateway name"><input style={inputStyle} value={gateway.gateway_name} onChange={(e) => setGateway({ ...gateway, gateway_name: e.target.value })} /></Field>
            <Field label="Mode"><select style={inputStyle} value={gateway.gateway_mode} onChange={(e) => setGateway({ ...gateway, gateway_mode: e.target.value as GatewayForm["gateway_mode"] })}><option value="cloud">Cloud Server</option><option value="local">Local Server</option><option value="modem">USB / Serial Modem</option></select></Field>
          </div>
          {gateway.gateway_mode === "cloud" && <div style={gridStyle}>
            <Field label="Device ID"><input style={inputStyle} value={gateway.device_id} onChange={(e) => setGateway({ ...gateway, device_id: e.target.value })} placeholder={currentGateway?.device_id_masked || "Enter device ID"} /></Field>
            <Field label="Cloud username"><input style={inputStyle} value={gateway.username} onChange={(e) => setGateway({ ...gateway, username: e.target.value })} /></Field>
            <Field label={`Cloud password${currentGateway?.password_set ? " (leave blank to keep)" : ""}`}><input type="password" style={inputStyle} value={gateway.password} onChange={(e) => setGateway({ ...gateway, password: e.target.value })} /></Field>
            <Field label="SIM slot (optional)"><input type="number" min={1} max={3} style={inputStyle} value={gateway.sim_number} onChange={(e) => setGateway({ ...gateway, sim_number: e.target.value })} /></Field>
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
          <label style={checkStyle}><input type="checkbox" checked={gateway.active} onChange={(e) => setGateway({ ...gateway, active: e.target.checked })} /> Gateway enabled</label>
          {currentGateway && !isAdmin && <label style={checkStyle}><input type="checkbox" checked={Boolean(currentGateway.auto_send)} onChange={async (e) => { try { const res = await setSmsGatewayAutoSend(currentGateway.id, e.target.checked); setGateways(old => old.map(g => g.id === currentGateway.id ? { ...g, auto_send: res.auto_send } : g)); setSuccess(res.auto_send ? "Auto-send enabled for your gateway." : "Auto-send disabled."); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not change auto-send setting"); } }} /> Auto-send approved SMS</label>}
          <div style={actionsStyle}><button className="btn btn-primary" onClick={() => void saveGateway()} disabled={busy !== null || (isFaculty && !facultyAccess?.enabled)}>{busy === "gateway" ? "Saving…" : "Save gateway"}</button>{currentGateway && <button className="btn btn-outline" onClick={() => void testConnection()} disabled={busy !== null}>{busy === "connection" ? "Testing…" : "Test connection"}</button>}</div>
        </section>

        {isFaculty ? (
          <section style={cardStyle}>
            <div style={headerStyle}><div><div style={eyebrow}>SEND SMS</div><h2 style={titleStyle}>Send to a delegated batch</h2><p style={muted}>Only the selected delegated batch is eligible. The server validates every student and the gateway owner before enqueueing.</p></div></div>
            <div style={gridStyle}>
              <Field label="Allowed batch"><select style={inputStyle} value={selectedBatchId ?? ""} onChange={e => setSelectedBatchId(Number(e.target.value))}><option value="">Select batch</option>{batches.map(b => <option key={b.id} value={b.id}>{b.code || b.name} ({b.student_count})</option>)}</select></Field>
              <Field label="Message"><textarea style={{ ...inputStyle, minHeight: 118, resize: "vertical" }} value={composeText} onChange={e => setComposeText(e.target.value)} placeholder="Dear Parent, {student}: {message}" /></Field>
            </div>
            <div style={actionsStyle}><button className="btn btn-primary" disabled={busy !== null || !selectedBatchId || !composeText.trim() || !gatewayConfigured} onClick={() => void sendGeneral()}>{busy === "general" ? "Sending…" : "Send SMS to batch"}</button></div>
            <p style={{ ...muted, marginTop: 10 }}>Individual-student Reject/Skip behavior used by the existing absentee flow is unchanged. This faculty flow never creates recipients outside the delegated batch.</p>
          </section>
        ) : (
          <section style={cardStyle}>
            <div style={headerStyle}><div><div style={eyebrow}>MESSAGE COMPOSER</div><h2 style={titleStyle}>Choose what to send</h2></div></div>
            <div style={{ display: "grid", gap: 12 }}>
              <fieldset style={{ border: 0, padding: 0, margin: 0 }}><legend style={{ color: "var(--text)", fontWeight: 800, marginBottom: 8 }}>Message Type</legend><div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}><label><input type="radio" checked={messageType === "ABSENTEE_ALERT"} onChange={() => { setMessageType("ABSENTEE_ALERT"); setComposeText(templates.ABSENTEE_ALERT || ""); }} /> Absentee Alert</label><label><input type="radio" checked={messageType === "GENERAL_NOTICE"} onChange={() => { setMessageType("GENERAL_NOTICE"); setComposeText(templates.GENERAL_NOTICE || ""); }} /> General Notice</label></div></fieldset>
              <Field label="Saved message template"><textarea style={{ ...inputStyle, minHeight: 100, resize: "vertical" }} value={composeText} onChange={(e) => setComposeText(e.target.value)} /></Field>
              <div style={actionsStyle}><button className="btn btn-outline" onClick={async () => { try { const r = await saveSmsTemplate(messageType, composeText); setTemplates(t => ({ ...t, [messageType]: r.template })); setSuccess("Message template saved for this scope."); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not save message template"); } }}>Save template</button>{messageType === "GENERAL_NOTICE" && <select style={{ ...inputStyle, width: 260 }} value={selectedBatchId ?? ""} onChange={e => setSelectedBatchId(Number(e.target.value))}><option value="">Select batch</option>{batches.map(b => <option key={b.id} value={b.id}>{b.code || b.name} ({b.student_count})</option>)}</select>}{messageType === "GENERAL_NOTICE" && <button className="btn btn-primary" disabled={busy !== null || !selectedBatchId || !composeText.trim()} onClick={() => void sendGeneral()}>{busy === "general" ? "Queuing…" : "Queue General Notice"}</button>}</div>
            </div>
          </section>
        )}

        {!isFaculty && <section style={cardStyle}>
          <div style={headerStyle}><div><div style={eyebrow}>SAFETY GATE</div><h2 style={titleStyle}>Review before sending</h2><p style={muted}>Attendance creates a queued batch. Nothing is sent until approved unless the configured HOD gateway is set to auto-send.</p></div><input type="date" value={approvalDate} onChange={(e) => setApprovalDate(e.target.value)} style={{ ...inputStyle, width: 170 }} /></div>
          {approvalRows.length === 0 ? <div style={emptyStyle}>No unapproved absentee SMS messages for this date.</div> : <><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}><strong style={{ color: "var(--text)" }}>{approvalRows.length} message(s) awaiting approval</strong><button className="btn btn-primary" onClick={() => void approve()} disabled={busy !== null}>{busy === "approve" ? "Approving…" : "Approve batch"}</button></div><div style={{ display: "grid", gap: 8 }}>{approvalRows.map((r) => <div key={r.id} style={rowStyle}><div><strong style={{ color: "var(--text)" }}>{r.roll_no} — {r.student_name}</strong><div style={muted}>{r.parent_phone}</div></div><div style={{ flex: 1, color: "var(--text)", fontSize: 13 }}>{r.message}</div><div style={{ minWidth: 220, textAlign: "right" }}><span style={pill(r.gateway_id && r.gateway_active && !r.error ? "good" : "bad")}>{r.error ? "BLOCKED" : r.gateway_name || "NO GATEWAY"}</span><div style={{ ...muted, marginTop: 4 }}>{r.hod_username || "No HOD"}</div><div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}><button className="btn btn-sm btn-primary" disabled={busy !== null || Boolean(r.error)} onClick={async () => { if (!window.confirm(`Approve SMS for ${r.student_name}?`)) return; setBusy(`approve-${r.id}`); try { await approveSmsRow(r.id); setSuccess(`SMS approved for ${r.roll_no}.`); await load(); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not approve SMS"); } finally { setBusy(null); } }}>Approve</button><button className="btn btn-sm btn-outline" disabled={busy !== null} onClick={async () => { if (!window.confirm(`Reject SMS for ${r.student_name}?`)) return; setBusy(`reject-${r.id}`); try { await rejectSmsRow(r.id); setSuccess(`SMS rejected for ${r.roll_no}.`); await load(); } catch (err) { setError(err instanceof ApiClientError ? err.message : "Could not reject SMS"); } finally { setBusy(null); } }}>Reject</button></div></div></div>)}</div></>}
        </section>}

        {(isAdmin || user.username === "admin") && <AdminStudentSelfEditCard onNotification={(msg, type) => type === "success" ? setSuccess(msg) : setError(msg)} />}

        {!isFaculty && <section style={cardStyle}>
          <div style={headerStyle}><div><div style={eyebrow}>OPERATIONS</div><h2 style={titleStyle}>Sending controls</h2></div></div>
          <div style={gridStyle}><Field label="Daily SMS cap"><input type="number" min={1} style={inputStyle} value={settings.sms_daily_cap} onChange={(e) => setSettings({ ...settings, sms_daily_cap: e.target.value })} /></Field><Field label="Absentee cutoff (HH:MM)"><input type="time" style={inputStyle} value={settings.sms_absentee_cutoff_time} onChange={(e) => setSettings({ ...settings, sms_absentee_cutoff_time: e.target.value })} /></Field><Field label="Automatic worker"><select style={inputStyle} value={settings.sms_enabled} onChange={(e) => setSettings({ ...settings, sms_enabled: e.target.value })}><option value="1">Enabled</option><option value="0">Disabled</option></select></Field><Field label="Test recipient"><input style={inputStyle} value={testPhone} onChange={(e) => setTestPhone(e.target.value)} placeholder="10-digit mobile number" /></Field></div>
          <div style={actionsStyle}><button className="btn btn-primary" onClick={() => void saveOperationsSettings()} disabled={busy !== null}>{busy === "settings" ? "Saving…" : "Save settings"}</button><button className="btn btn-outline" onClick={() => void sendTest()} disabled={busy !== null || !currentGateway}>{busy === "test-sms" ? "Sending…" : "Send test SMS"}</button></div>
        </section>}

        <section style={cardStyle}>
          <div style={headerStyle}><div><div style={eyebrow}>HISTORY</div><h2 style={titleStyle}>Recent SMS activity</h2></div></div>
          {loading ? <div style={emptyStyle}>Loading…</div> : logs.length === 0 ? <div style={emptyStyle}>No SMS activity yet.</div> : <div style={{ overflowX: "auto" }}><table style={{ width: "100%", borderCollapse: "collapse", color: "var(--text)" }}><thead><tr>{["Date", "Student", "Gateway", "Status", "Error"].map((h) => <th key={h} style={thStyle}>{h}</th>)}</tr></thead><tbody>{logs.map((r) => <tr key={r.id}><td style={tdStyle}>{r.created_at}</td><td style={tdStyle}>{r.roll_no}{r.student_name ? ` — ${r.student_name}` : ""}</td><td style={tdStyle}>{r.gateway_name || "Unassigned"}</td><td style={tdStyle}><span style={pill(r.status === "SENT" ? "good" : r.status === "FAILED" ? "bad" : "muted")}>{r.status}</span></td><td style={{ ...tdStyle, color: "var(--muted)" }}>{r.error || "—"}</td></tr>)}</tbody></table></div>}
        </section>
      </div>
    </AppShell>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) { return <label style={fieldLabel}>{label}{children}</label>; }
const cardStyle: CSSProperties = { background: "var(--card-glass)", border: "1px solid var(--border)", borderRadius: 18, padding: 20, boxShadow: "0 8px 28px rgba(0,0,0,.08)" };
const headerStyle: CSSProperties = { display: "flex", justifyContent: "space-between", gap: 18, alignItems: "flex-start", marginBottom: 18 };
const titleStyle: CSSProperties = { margin: "3px 0 5px", color: "var(--text)", fontSize: 21 };
const muted: CSSProperties = { color: "var(--muted)", fontSize: 13, lineHeight: 1.5, margin: 0 };
const eyebrow: CSSProperties = { color: "var(--heading-accent)", fontSize: 11, fontWeight: 900, letterSpacing: 1.4 };
const fieldLabel: CSSProperties = { display: "grid", gap: 7, color: "var(--text)", fontSize: 13, fontWeight: 700 };
const gridStyle: CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 14 };
const inputStyle: CSSProperties = { width: "100%", boxSizing: "border-box", padding: "10px 12px", borderRadius: 10, border: "1px solid var(--input-border)", background: "var(--input-bg)", color: "var(--text)" };
const actionsStyle: CSSProperties = { display: "flex", gap: 10, flexWrap: "wrap", marginTop: 16 };
const emptyStyle: CSSProperties = { padding: 18, borderRadius: 12, background: "var(--chip-bg-muted)", color: "var(--muted)", textAlign: "center" };
const rowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 14, padding: 12, border: "1px solid var(--border)", borderRadius: 12, flexWrap: "wrap" };
const thStyle: CSSProperties = { textAlign: "left", padding: "9px 8px", borderBottom: "1px solid var(--border)", fontSize: 11, color: "var(--muted)", textTransform: "uppercase" };
const tdStyle: CSSProperties = { padding: "10px 8px", borderBottom: "1px solid var(--border)", fontSize: 12, verticalAlign: "top" };
const checkStyle: CSSProperties = { display: "flex", gap: 10, alignItems: "center", marginTop: 12, color: "var(--text)", fontWeight: 700 };
const batchPillStyle: CSSProperties = { display: "inline-flex", alignItems: "center", padding: "8px 10px", borderRadius: 999, background: "var(--chip-bg-muted)", border: "1px solid var(--border)", color: "var(--text)", fontSize: 12, fontWeight: 800 };
function pill(kind: "good" | "bad" | "muted"): CSSProperties { return { display: "inline-flex", padding: "4px 8px", borderRadius: 999, fontSize: 10, fontWeight: 900, letterSpacing: .5, background: kind === "good" ? "rgba(16,185,129,.12)" : kind === "bad" ? "rgba(239,68,68,.12)" : "var(--chip-bg-muted)", color: kind === "good" ? "#059669" : kind === "bad" ? "#dc2626" : "var(--muted)" }; }
