// Forgot Password — step 1 of the OTP-based reset flow (per
// api/routes_auth.py: POST /api/auth/send-otp, purpose=RESET_PASSWORD).
// On success, forwards to /reset-password?email=... where the code +
// new password are entered. The backend deliberately returns the same
// generic message whether or not the email is registered (enumeration
// prevention — see send_otp's docstring), so this page can't and doesn't
// try to tell the user "no account with that email".
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { forgotPassword } from "../../api/auth";
import { ApiClientError } from "../../api/client";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ThemeToggle } from "../../components/ThemeToggle";

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    const trimmed = email.trim().toLowerCase();
    if (!trimmed || !/\S+@\S+\.\S+/.test(trimmed)) {
      setError("Enter a valid email address");
      return;
    }

    setSubmitting(true);
    try {
      await forgotPassword(trimmed);
      // WHY navigate regardless of whether the account exists: the backend
      // never reveals that (same enumeration-prevention reasoning as
      // /login's generic error) — so the UI always proceeds to the code
      // entry step, and a stranger's email will just never receive a code.
      navigate(`/reset-password?email=${encodeURIComponent(trimmed)}`);
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
          <div className="auth-header-with-icon">
            <div className="auth-icon-badge">
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <circle cx="7.5" cy="15.5" r="5.5" />
                <path d="m21 2-9.6 9.6" />
                <path d="m15.5 7.5 3 3" />
                <path d="m18.5 4.5 3 3" />
              </svg>
            </div>
            <h2>Forgot Password?</h2>
          </div>
          <p className="sub">Enter your account email and we'll send a verification code</p>

          <form onSubmit={handleSubmit}>
            <div className="brandlogin-field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                name="email"
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <button type="submit" className="brandlogin-btn" disabled={submitting}>
              {submitting ? "Sending…" : "Send Verification Code"}
            </button>
          </form>

          <p className="brandlogin-switch">
            <Link to="/login">Back to Login</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
