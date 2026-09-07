// Ports webapp/templates/auth/force_password_change.html 1:1 — same three
// fields, same show-passwords checkbox (toggles all three), same
// "Log out instead" secondary action. Handoff item 5.
//
// Same staggered entrance animation as LoginPage.tsx, for consistency —
// see that file's header comment for where the technique came from.
import { useState, type FormEvent, type CSSProperties } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword, logout, type CurrentUser } from "../../api/auth";
import { ApiClientError } from "../../api/client";
import { PasswordField } from "../../components/PasswordField";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ThemeToggle } from "../../components/ThemeToggle";

type StaggerStyle = CSSProperties & { "--i"?: number };

function stagger(i: number): StaggerStyle {
  return { "--i": i };
}

interface ForcePasswordChangePageProps {
  user: CurrentUser;
  onChanged: () => void;
  onLoggedOut: () => void;
}

export function ForcePasswordChangePage({ user, onChanged, onLoggedOut }: ForcePasswordChangePageProps) {
  const navigate = useNavigate();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await changePassword(oldPassword, newPassword, confirmPassword);
      onChanged();
      navigate(res.redirect);
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

  async function handleLogout() {
    await logout();
    onLoggedOut();
    navigate("/login");
  }

  return (
    <div className="login-shell">
      <ThemeToggle className="auth-theme-toggle" />
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <div className="login-side" style={{ width: "40%", background: "linear-gradient(145deg, #070e24 0%, #0d1b40 50%, #050a1b 100%)" }}>
        <div className="brandlogin-logo-container">
          <div className="brandlogin-logo-glow" />
          <img
            src="/logo.png"
            alt="NextGen SMS Logo"
            className="brandlogin-logo-img"
          />
        </div>
        <h1 className="brandlogin-headline">NextGen SMS</h1>
        <div className="brandlogin-tag-badge">STUDENT MANAGEMENT SYSTEM</div>
      </div>
      <div className="login-area">
        <div className="login-card">
          <h2 className="login-animate" style={stagger(0)}>Change Your Password</h2>
          <p className="sub login-animate" style={stagger(1)}>
            Your account still has its default password. Set a new one to continue to {user.username}'s account.
          </p>
          <form onSubmit={handleSubmit}>
            <div className="login-animate" style={stagger(2)}>
              <PasswordField
                id="old_password"
                label="Current password"
                value={oldPassword}
                onChange={setOldPassword}
                autoFocus
              />
            </div>
            <div className="login-animate" style={stagger(3)}>
              <PasswordField
                id="new_password"
                label="New password (minimum 8 characters)"
                value={newPassword}
                onChange={setNewPassword}
              />
            </div>
            <div className="login-animate" style={stagger(4)}>
              <PasswordField
                id="confirm_password"
                label="Confirm new password"
                value={confirmPassword}
                onChange={setConfirmPassword}
              />
            </div>
            <button
              type="submit"
              className="btn btn-block login-animate"
              style={{ height: 45, marginTop: 12, ...stagger(6) }}
              disabled={submitting}
            >
              {submitting ? "Changing..." : "Change Password"}
            </button>
          </form>
          <form
            onSubmit={(e) => { e.preventDefault(); handleLogout(); }}
            className="login-animate"
            style={{ marginTop: 12, ...stagger(7) }}
          >
            <button type="submit" className="btn btn-outline btn-block">
              Log out instead
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
