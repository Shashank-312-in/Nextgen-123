import { useState, useEffect } from "react";
import { getStudentSelfEditSetting, updateStudentSelfEditSetting } from "../api/dashboard";
import { ApiClientError } from "../api/client";

interface Props {
  className?: string;
  onNotification?: (msg: string, type: "success" | "error") => void;
}

export function AdminStudentSelfEditCard({ className = "", onNotification }: Props) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [localMsg, setLocalMsg] = useState<{ text: string; type: "success" | "error" } | null>(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        setLoading(true);
        const res = await getStudentSelfEditSetting();
        if (mounted) {
          setEnabled(Boolean(res.student_self_edit_enabled));
        }
      } catch (err) {
        console.error("Failed to load student self-edit setting:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => { mounted = false; };
  }, []);

  async function handleToggle() {
    if (saving || loading) return;
    const nextState = !enabled;
    setSaving(true);
    setLocalMsg(null);
    try {
      const res = await updateStudentSelfEditSetting(nextState);
      const updated = Boolean(res.student_self_edit_enabled);
      setEnabled(updated);
      const text = updated
        ? "Student self-editing has been enabled. Students can now edit their profiles."
        : "Student self-editing has been disabled. Student profiles are now locked.";
      setLocalMsg({ text, type: "success" });
      onNotification?.(text, "success");
    } catch (err) {
      const text = err instanceof ApiClientError ? err.message : "Failed to update student self-edit setting";
      setLocalMsg({ text, type: "error" });
      onNotification?.(text, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      className={`admin-setting-card ${className}`}
      style={{
        background: "var(--card-glass)",
        border: "1.5px solid var(--border)",
        borderRadius: 18,
        padding: 22,
        boxShadow: "0 8px 28px rgba(0,0,0,.08)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div style={{ maxWidth: 540 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span
              style={{
                color: "var(--heading-accent)",
                fontSize: 11,
                fontWeight: 900,
                letterSpacing: 1.4,
                textTransform: "uppercase",
              }}
            >
              ADMIN MASTER CONTROLS
            </span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 800,
                padding: "2px 8px",
                borderRadius: 999,
                background: "linear-gradient(135deg, #0284c7, #2563eb)",
                color: "#ffffff",
                letterSpacing: 0.5,
              }}
            >
              ADMIN ONLY
            </span>
          </div>

          <h2 style={{ margin: "2px 0 6px", color: "var(--text)", fontSize: 20, fontWeight: 800 }}>
            Student Profile Self-Editing
          </h2>
          <p style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.5, margin: 0 }}>
            Controls whether students are permitted to edit their own profile fields (contact numbers, email, date of birth, address, etc.). When disabled, student profiles become read-only and a notice directs them to contact administration.
          </p>
        </div>

        {/* Toggle Switch Control */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                fontSize: 12,
                fontWeight: 800,
                padding: "4px 10px",
                borderRadius: 999,
                letterSpacing: 0.5,
                background: enabled ? "rgba(34, 197, 94, 0.12)" : "rgba(239, 68, 68, 0.12)",
                color: enabled ? "#16a34a" : "#dc2626",
                border: enabled ? "1px solid rgba(34, 197, 94, 0.25)" : "1px solid rgba(239, 68, 68, 0.25)",
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: enabled ? "#16a34a" : "#dc2626",
                  boxShadow: enabled ? "0 0 6px #16a34a" : "none",
                }}
              />
              {loading ? "Loading…" : enabled ? "Self-Editing Allowed" : "Self-Editing Disabled"}
            </span>

            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label="Toggle student self-editing"
              disabled={loading || saving}
              onClick={handleToggle}
              style={{
                position: "relative",
                width: 56,
                height: 30,
                borderRadius: 999,
                background: enabled
                  ? "linear-gradient(135deg, #10b981, #059669)"
                  : "var(--border)",
                border: "none",
                cursor: loading || saving ? "not-allowed" : "pointer",
                padding: 3,
                transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
                boxShadow: enabled
                  ? "0 4px 14px rgba(16, 185, 129, 0.4)"
                  : "inset 0 2px 4px rgba(0,0,0,0.1)",
                opacity: loading || saving ? 0.7 : 1,
                display: "inline-flex",
                alignItems: "center",
              }}
            >
              <span
                style={{
                  display: "block",
                  width: 24,
                  height: 24,
                  borderRadius: "50%",
                  background: "#ffffff",
                  boxShadow: "0 2px 6px rgba(0,0,0,0.25)",
                  transform: enabled ? "translateX(26px)" : "translateX(0px)",
                  transition: "transform 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
                }}
              />
            </button>
          </div>
          {saving && (
            <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 700 }}>
              Saving change…
            </span>
          )}
        </div>
      </div>

      {localMsg && (
        <div
          style={{
            marginTop: 14,
            padding: "10px 14px",
            borderRadius: 10,
            fontSize: 12,
            fontWeight: 700,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: localMsg.type === "success" ? "rgba(34, 197, 94, 0.1)" : "rgba(239, 68, 68, 0.1)",
            color: localMsg.type === "success" ? "#15803d" : "#b91c1c",
            border: localMsg.type === "success" ? "1px solid rgba(34, 197, 94, 0.2)" : "1px solid rgba(239, 68, 68, 0.2)",
          }}
        >
          <span>{localMsg.type === "success" ? "✓ " : "⚠ "}{localMsg.text}</span>
          <button
            type="button"
            onClick={() => setLocalMsg(null)}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              fontSize: 14,
              color: "inherit",
              padding: 0,
              marginLeft: 10,
            }}
          >
            ×
          </button>
        </div>
      )}
    </section>
  );
}
