// Group 4 — Student create/edit form. Mirrors webapp/routes/students.py's
// student_new_form()/student_edit_form()/_save_student() +
// templates/students/form.html — one component handles both /students/new
// and /students/:id/edit, same as the OG's one Jinja template did.
import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  getNewStudentForm, getEditStudentForm, createStudent, updateStudent,
  FIELD_SPECS, EDUCATION_SPECS, type StudentRecord,
} from "../../api/students";
import { ApiClientError, formatPhotoUrl } from "../../api/client";
import { type CurrentUser } from "../../api/auth";
import { AppShell } from "../../components/AppShell";
import { ErrorPopup } from "../../components/ErrorPopup";

interface StudentFormPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

const CATEGORY_OPTIONS = ["OC", "BC-A", "BC-B", "BC-C", "BC-D", "BC-E", "SC", "ST", "EWS"];
const SEAT_CATEGORY_OPTIONS = ["Convenor (A-Category)", "Management (B-Category)", "NRI / Spot Admission"];
const CERTIFICATE_OPTIONS = [
  "10th Marks Memo",
  "12th / Diploma Memo",
  "Transfer Certificate (TC)",
  "Study & Conduct Certificate",
  "Aadhaar Card Copy",
  "Caste / EWS Certificate"
];

export function StudentFormPage({ user, onLoggedOut }: StudentFormPageProps) {
  const { studentId } = useParams<{ studentId: string }>();
  const navigate = useNavigate();
  const isEdit = studentId !== undefined;
  const id = isEdit ? Number(studentId) : null;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [semesters, setSemesters] = useState<Array<{ id: number; code: string; name: string }>>([]);
  const [existingRow, setExistingRow] = useState<StudentRecord | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [currentSemesterId, setCurrentSemesterId] = useState<number | "">("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = isEdit ? await getEditStudentForm(id!) : await getNewStudentForm();
      setSemesters(res.semesters);
      setExistingRow(res.student);
      const initial: Record<string, string> = {};
      for (const [, key] of [...FIELD_SPECS, ...EDUCATION_SPECS]) {
        initial[key] = res.student ? ((res.student as unknown as Record<string, string | null>)[key] ?? "") : "";
      }
      setValues(initial);
      setCurrentSemesterId(res.student?.current_semester_id ?? "");
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to load form");
    } finally {
      setLoading(false);
    }
  }, [isEdit, id]);

  useEffect(() => { load(); }, [load]);

  function setField(key: string, val: string) {
    setValues((v) => ({ ...v, [key]: val }));
  }

  function handleToggleCertificate(fieldKey: "certificates_submitted" | "certificates_due", cert: string) {
    const currentStr = values[fieldKey] || "";
    const list = currentStr ? currentStr.split(",").map(s => s.trim()) : [];
    let updated: string[];
    if (list.includes(cert)) {
      updated = list.filter(item => item !== cert);
    } else {
      updated = [...list, cert];
    }
    setField(fieldKey, updated.join(", "));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);

    // Front-end Pre-submit Validation Checks
    if (values.email && !/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(values.email)) {
      setError("Please enter a valid email address (e.g. student@gmail.com)");
      setSaving(false);
      return;
    }

    if (values.phone && values.phone.replace(/\D/g, "").length !== 10) {
      setError("Student Mobile Phone Number must be exactly 10 digits");
      setSaving(false);
      return;
    }

    if (values.parent_phone && values.parent_phone.replace(/\D/g, "").length !== 10) {
      setError("Parent Phone Number must be exactly 10 digits");
      setSaving(false);
      return;
    }

    if (values.aadhaar_number && values.aadhaar_number.replace(/\D/g, "").length !== 12) {
      setError("Aadhaar Number must be exactly 12 digits (e.g. 1234 5678 9012)");
      setSaving(false);
      return;
    }

    try {
      const semId = currentSemesterId === "" ? null : Number(currentSemesterId);
      const result = isEdit
        ? await updateStudent(id!, values, semId)
        : await createStudent(values, semId);
      if (result.created_credentials) {
        const { username, password } = result.created_credentials;
        navigate(`/students?created=${encodeURIComponent(`Username: ${username} · Temporary password: ${password}`)}`);
      } else {
        navigate(`/students/${result.id}?notice=${encodeURIComponent("Student updated")}`);
      }
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Failed to save student");
    } finally {
      setSaving(false);
    }
  }

  const renderSmartFieldInput = (label: string, key: string) => {
    // 1. Gender Pill Selector
    if (key === "gender") {
      const current = (values.gender || "").toUpperCase();
      return (
        <div style={{ display: "flex", gap: 10, marginTop: 4, flexWrap: "wrap" }}>
          {[
            { label: "👨 Male", value: "MALE" },
            { label: "👩 Female", value: "FEMALE" },
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setField("gender", item.value)}
              style={{
                flex: 1,
                minWidth: 100,
                padding: "10px 14px",
                borderRadius: 10,
                fontWeight: 700,
                fontSize: 13,
                cursor: "pointer",
                border: current === item.value ? "2px solid var(--heading-accent)" : "1px solid var(--border)",
                background: current === item.value ? "linear-gradient(135deg, #0284c7, #2563eb)" : "var(--chip-bg-muted)",
                color: current === item.value ? "#ffffff" : "var(--text)",
                boxShadow: current === item.value ? "0 6px 16px rgba(56, 189, 248, 0.4)" : "none",
                transition: "all 0.2s ease",
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      );
    }

    // 2. Category Select + Quick Pills
    if (key === "category") {
      const current = values.category || "";
      return (
        <div>
          <select
            id={key}
            className="input-field"
            value={current}
            onChange={(e) => setField("category", e.target.value)}
            style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }}
          >
            <option value="">— Select Category —</option>
            {CATEGORY_OPTIONS.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
            {CATEGORY_OPTIONS.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setField("category", cat)}
                style={{
                  fontSize: 11,
                  padding: "3px 8px",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontWeight: current === cat ? 700 : 500,
                  border: current === cat ? "1px solid var(--heading-accent)" : "1px solid var(--border)",
                  background: current === cat ? "rgba(56, 189, 248, 0.25)" : "var(--chip-bg-muted)",
                  color: current === cat ? "var(--heading-accent)" : "var(--muted)",
                }}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>
      );
    }

    // 3. Seat Category Select
    if (key === "seat_category") {
      const current = values.seat_category || "";
      return (
        <div>
          <select
            id={key}
            className="input-field"
            value={current}
            onChange={(e) => setField("seat_category", e.target.value)}
            style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }}
          >
            <option value="">— Select Seat Category —</option>
            {SEAT_CATEGORY_OPTIONS.map((seat) => (
              <option key={seat} value={seat}>{seat}</option>
            ))}
          </select>
        </div>
      );
    }

    // 4. Date of Birth Picker
    if (key === "dob") {
      return (
        <input
          type="date"
          id={key}
          className="input-field"
          value={values[key] ?? ""}
          onChange={(e) => setField(key, e.target.value)}
          style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }}
        />
      );
    }

    // 5. Certificates Submitted / Due Multi-Selector
    if (key === "certificates_submitted" || key === "certificates_due") {
      const currentStr = values[key] || "";
      const selectedList = currentStr ? currentStr.split(",").map(s => s.trim()) : [];
      return (
        <div>
          <input
            type="text"
            id={key}
            value={currentStr}
            onChange={(e) => setField(key, e.target.value)}
            placeholder="Selected certificates will appear here..."
            style={{ width: "100%", padding: "8px 12px", borderRadius: 8, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontSize: 12, marginBottom: 8 }}
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {CERTIFICATE_OPTIONS.map((cert) => {
              const isSel = selectedList.includes(cert);
              return (
                <button
                  key={cert}
                  type="button"
                  onClick={() => handleToggleCertificate(key as "certificates_submitted" | "certificates_due", cert)}
                  style={{
                    fontSize: 11,
                    padding: "4px 9px",
                    borderRadius: 6,
                    cursor: "pointer",
                    fontWeight: isSel ? 700 : 500,
                    border: isSel ? "1px solid var(--heading-accent)" : "1px solid var(--border)",
                    background: isSel ? "linear-gradient(135deg, #0284c7, #2563eb)" : "var(--chip-bg-muted)",
                    color: isSel ? "#ffffff" : "var(--text)",
                  }}
                >
                  {isSel ? "✓ " : "+ "}{cert}
                </button>
              );
            })}
          </div>
        </div>
      );
    }

    // 6. Aadhaar Number with Auto 4-Digit Spacing & 12 Digit Limit
    if (key === "aadhaar_number") {
      const raw = values.aadhaar_number || "";
      const handleAadhaarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const digitsOnly = e.target.value.replace(/\D/g, "").slice(0, 12);
        const formatted = digitsOnly.replace(/(\d{4})(?=\d)/g, "$1 ").trim();
        setField("aadhaar_number", formatted);
      };

      return (
        <div>
          <input
            type="text"
            id={key}
            className="input-field"
            maxLength={14}
            placeholder="1234 5678 9012"
            value={raw}
            onChange={handleAadhaarChange}
            style={{
              width: "100%",
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--input-bg)",
              border: "1px solid var(--input-border)",
              color: "var(--text)",
              fontWeight: 700,
              letterSpacing: "1.5px",
              fontFamily: "monospace, sans-serif"
            }}
          />
          <small style={{ color: "var(--muted)", fontSize: 11, marginTop: 4, display: "block" }}>
            {raw.replace(/\D/g, "").length} / 12 digits entered (Auto-spaced format)
          </small>
        </div>
      );
    }

    // 7. Email Validation Handler
    if (key === "email") {
      const emailVal = values.email || "";
      const isValidEmail = !emailVal || /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(emailVal);
      return (
        <div>
          <input
            type="email"
            id={key}
            className="input-field"
            placeholder="student@gmail.com"
            value={emailVal}
            onChange={(e) => setField("email", e.target.value)}
            style={{
              width: "100%",
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--input-bg)",
              border: emailVal && !isValidEmail ? "2px solid #f43f5e" : "1px solid var(--input-border)",
              color: "var(--text)",
            }}
          />
          {emailVal ? (
            <small style={{ color: isValidEmail ? "#10b981" : "#f43f5e", fontSize: 11, marginTop: 4, display: "block", fontWeight: 700 }}>
              {isValidEmail ? "✓ Valid Email Address" : "❌ Invalid Email (must include @ and domain like .com)"}
            </small>
          ) : (
            <small style={{ color: "var(--muted)", fontSize: 11, marginTop: 4, display: "block" }}>
              e.g. student@gmail.com
            </small>
          )}
        </div>
      );
    }

    // 8. Mobile Phone & Parent Phone Handler (10 Digits Strict)
    if (key === "phone" || key === "parent_phone") {
      const phoneVal = values[key] || "";
      const digitsOnly = phoneVal.replace(/\D/g, "").slice(0, 10);
      const isValidPhone = !phoneVal || digitsOnly.length === 10;
      return (
        <div>
          <input
            type="text"
            id={key}
            className="input-field"
            maxLength={10}
            placeholder="9876543210"
            value={phoneVal}
            onChange={(e) => setField(key, e.target.value.replace(/\D/g, "").slice(0, 10))}
            style={{
              width: "100%",
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--input-bg)",
              border: phoneVal && !isValidPhone ? "2px solid #f43f5e" : "1px solid var(--input-border)",
              color: "var(--text)",
              fontWeight: 600,
            }}
          />
          {phoneVal ? (
            <small style={{ color: isValidPhone ? "#10b981" : "#f43f5e", fontSize: 11, marginTop: 4, display: "block", fontWeight: 700 }}>
              {isValidPhone ? `✓ Valid 10-Digit Mobile Number` : `❌ ${digitsOnly.length} / 10 digits entered`}
            </small>
          ) : (
            <small style={{ color: "var(--muted)", fontSize: 11, marginTop: 4, display: "block" }}>
              Must be exactly 10 digits
            </small>
          )}
        </div>
      );
    }

    // Default Input Box
    return (
      <input
        type="text"
        id={key}
        className="input-field"
        value={values[key] ?? ""}
        onChange={(e) => setField(key, e.target.value)}
        style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)" }}
      />
    );
  };

  return (
    <AppShell
      user={user}
      activeNav="students"
      heading={isEdit ? "Edit CSD Data Science Student" : "Add CSD Data Science Student"}
      onLoggedOut={onLoggedOut}
    >
      <ErrorPopup message={error} onClose={() => setError(null)} />
      {loading && <div className="empty-note">Loading…</div>}

      {!loading && (
        <div className="card card-pad" style={{ background: "var(--card-glass)", border: "1px solid var(--border)", borderRadius: 16, padding: 24, boxShadow: "0 20px 45px rgba(0,0,0,0.15)" }}>
          {isEdit && existingRow && (
            <div style={{ marginBottom: 20, display: "flex", alignItems: "center", gap: 14 }}>
              {existingRow.photo_path && formatPhotoUrl(existingRow.photo_path) ? (
                <img src={formatPhotoUrl(existingRow.photo_path)!} alt="" style={{ width: 64, height: 64, borderRadius: 14, objectFit: "cover", border: "2px solid var(--heading-accent)" }} />
              ) : (
                <div style={{ fontSize: 42 }}>👤</div>
              )}
              <div>
                <strong style={{ display: "block", fontSize: 16, color: "var(--text)" }}>{existingRow.name} ({existingRow.roll_no})</strong>
                <Link to={`/students/${id}`} className="btn btn-outline btn-sm" style={{ fontSize: 12, textDecoration: "none", marginTop: 4, display: "inline-block" }}>
                  📷 Manage photo on profile page
                </Link>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="form-grid">
              {FIELD_SPECS.map(([label, key]) => (
                <div className="field" key={key} style={{ background: "var(--chip-bg-muted)", padding: 12, borderRadius: 12, border: "1px solid var(--border-light)" }}>
                  <label htmlFor={key} style={{ fontWeight: 800, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>
                    {label}
                  </label>
                  {renderSmartFieldInput(label, key)}
                </div>
              ))}
              <div className="field" style={{ background: "var(--chip-bg-muted)", padding: 12, borderRadius: 12, border: "1px solid var(--border-light)" }}>
                <label htmlFor="current_semester_id" style={{ fontWeight: 800, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>
                  Current Semester
                </label>
                <select
                  id="current_semester_id"
                  className="input-field"
                  value={currentSemesterId}
                  onChange={(e) => setCurrentSemesterId(e.target.value === "" ? "" : Number(e.target.value))}
                  style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)", fontWeight: 600 }}
                >
                  <option value="">— Not set —</option>
                  {semesters.map((sem) => (
                    <option key={sem.id} value={sem.id}>{sem.code} &middot; {sem.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <h3 style={{ margin: "24px 0 12px", fontSize: 16, color: "var(--heading-accent)", fontWeight: 800, borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
              🎓 Education Qualification
            </h3>
            <div className="form-grid">
              {EDUCATION_SPECS.map(([label, key]) => (
                <div className="field" key={key} style={{ background: "var(--chip-bg-muted)", padding: 12, borderRadius: 12, border: "1px solid var(--border-light)" }}>
                  <label htmlFor={key} style={{ fontWeight: 800, fontSize: 12, color: "var(--heading-accent)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 6, display: "block" }}>
                    {label}
                  </label>
                  <input
                    type="text"
                    id={key}
                    className="input-field"
                    value={values[key] ?? ""}
                    onChange={(e) => setField(key, e.target.value)}
                    style={{ width: "100%", padding: "10px 14px", borderRadius: 10, background: "var(--input-bg)", border: "1px solid var(--input-border)", color: "var(--text)" }}
                  />
                </div>
              ))}
            </div>

            <div style={{ display: "flex", gap: 12, marginTop: 24 }}>
              <button type="submit" className="btn btn-primary" style={{ background: "linear-gradient(135deg, #0284c7, #2563eb)", color: "#ffffff", fontWeight: 700, padding: "12px 24px", borderRadius: 10, border: "none", boxShadow: "0 8px 20px rgba(56, 189, 248, 0.35)", cursor: "pointer" }} disabled={saving}>
                {saving ? "Saving Student…" : "💾 Save Student Profile"}
              </button>
              <Link to="/students" className="btn btn-outline" style={{ textDecoration: "none", padding: "12px 20px", borderRadius: 10 }}>Cancel</Link>
            </div>
          </form>
        </div>
      )}
    </AppShell>
  );
}
