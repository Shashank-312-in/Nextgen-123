// Reset Password — step 2 of the OTP-based flow, landed on from
// ForgotPasswordPage (?email=...). Verifies the code and sets the new
// password in one call: POST /api/auth/reset-password-otp.
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { forgotPassword, resetPasswordOtp } from "../../api/auth";
import { ApiClientError } from "../../api/client";
import { PasswordField } from "../../components/PasswordField";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ThemeToggle } from "../../components/ThemeToggle";

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const email = (searchParams.get("email") ?? "").trim().toLowerCase();

  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendNotice, setResendNotice] = useState<string | null>(null);

  async function handleResend() {
    setError(null);
    setResendNotice(null);
    setResending(true);
    try {
      const res = await forgotPassword(email);
      setResendNotice(res.message);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("Could not resend the code. Please try again.");
      }
    } finally {
      setResending(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!email) {
      setError("Missing email — request a new code from Forgot Password");
      return;
    }
    if (!code.trim()) {
      setError("Enter the 6-digit code sent to your email");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setSubmitting(true);
    try {
      const res = await resetPasswordOtp(email, code.trim(), newPassword, confirmPassword);
      setSuccess(res.message);
      setTimeout(() => navigate("/login"), 1500);
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
    <div className="brandlogin-shell">
      <ThemeToggle className="auth-theme-toggle" />
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <div className="brandlogin-side">
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
        <p className="brandlogin-tagline">Smart Campus. Smarter Management.</p>
      </div>

      <div className="brandlogin-area">
        <div className="brandlogin-card">
          <h2>Reset Password</h2>
          {email ? (
            <p className="otp-sent-to">Enter the code sent to <strong>{email}</strong></p>
          ) : (
            <p className="sub">Choose a new password for your account</p>
          )}

          {success && (
            <div className="success-banner" style={{ marginBottom: 18 }}>
              <span>{success}</span>
            </div>
          )}
          {resendNotice && !success && (
            <div className="success-banner" style={{ marginBottom: 18 }}>
              <span>{resendNotice}</span>
            </div>
          )}

          {!email && !success && (
            <p className="sub">
              This link is missing its email. Request a new code from{" "}
              <Link to="/forgot-password" className="forgot-password-link">
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }}
                >
                  <circle cx="7.5" cy="15.5" r="5.5" />
                  <path d="m21 2-9.6 9.6" />
                  <path d="m15.5 7.5 3 3" />
                  <path d="m18.5 4.5 3 3" />
                </svg>
                <span>Forgot Password</span>
              </Link>.
            </p>
          )}

          {email && !success && (
            <form onSubmit={handleSubmit}>
              <div className="brandlogin-field otp-code-input">
                <label htmlFor="code">Verification Code</label>
                <input
                  id="code"
                  name="code"
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  required
                  autoFocus
                  placeholder="6-digit code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                />
              </div>

              <button
                type="button"
                className="brandlogin-switch"
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, width: "100%", textAlign: "center", marginTop: 10 }}
                onClick={handleResend}
                disabled={resending}
              >
                {resending ? "Resending…" : "Resend code"}
              </button>

              <PasswordField
                id="new_password"
                label="New Password"
                value={newPassword}
                onChange={setNewPassword}
              />

              <PasswordField
                id="confirm_password"
                label="Confirm New Password"
                value={confirmPassword}
                onChange={setConfirmPassword}
              />

              <button type="submit" className="brandlogin-btn" disabled={submitting}>
                {submitting ? "Updating…" : "Update Password"}
              </button>
            </form>
          )}

          <p className="brandlogin-switch">
            <Link to="/login">Back to Login</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
