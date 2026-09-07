import { useState, type FormEvent } from "react";
import { submitProblemReport } from "../api/reports";
import { ApiClientError } from "../api/client";
import { ErrorPopup } from "./ErrorPopup";

interface ReportProblemModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const CATEGORIES = [
  "General",
  "Bug / Error",
  "Attendance Issue",
  "Login / Access",
  "UI / Layout",
  "Feature Request",
  "Performance / Slow Load",
];

export function ReportProblemModal({ isOpen, onClose }: ReportProblemModalProps) {
  const [category, setCategory] = useState("General");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!subject.trim()) {
      setError("Please enter a subject or title for the problem");
      return;
    }
    if (!description.trim()) {
      setError("Please describe the problem you encountered");
      return;
    }

    setSubmitting(true);
    try {
      const res = await submitProblemReport({
        category,
        subject: subject.trim(),
        description: description.trim(),
      });
      setSuccess(res.message);
      setSubject("");
      setDescription("");
      setCategory("General");
      setTimeout(() => {
        setSuccess(null);
        onClose();
      }, 1800);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="report-modal-overlay" onClick={onClose}>
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <div className="report-modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="report-modal-header">
          <div className="report-modal-title">
            <span className="report-icon">⚠️</span>
            <h3>Report a Problem</h3>
          </div>
          <button type="button" className="report-modal-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <p className="report-modal-sub">
          Facing an issue? Submit details below — only system administrators will see your report.
        </p>

        {success && (
          <div className="success-banner" style={{ marginBottom: 14 }}>
            <span>{success}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="brandlogin-field" style={{ marginBottom: 14 }}>
            <label htmlFor="report-category">Problem Category</label>
            <select
              id="report-category"
              className="report-select"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
          </div>

          <div className="brandlogin-field" style={{ marginBottom: 14 }}>
            <label htmlFor="report-subject">Subject / Summary *</label>
            <input
              id="report-subject"
              type="text"
              required
              placeholder="e.g. Attendance page not updating"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>

          <div className="brandlogin-field" style={{ marginBottom: 18 }}>
            <label htmlFor="report-description">Problem Details *</label>
            <textarea
              id="report-description"
              rows={4}
              required
              placeholder="Describe what happened, error messages, or steps to reproduce..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={{
                width: "100%",
                padding: "10px 14px",
                borderRadius: "8px",
                border: "1px solid rgba(255, 255, 255, 0.15)",
                background: "rgba(15, 23, 42, 0.6)",
                color: "#fff",
                fontSize: "14px",
                fontFamily: "inherit",
                resize: "vertical",
              }}
            />
          </div>

          <div className="report-modal-actions">
            <button type="button" className="btn btn-outline" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="brandlogin-btn" style={{ width: "auto", padding: "10px 22px" }} disabled={submitting}>
              {submitting ? "Submitting…" : "Submit Report"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
