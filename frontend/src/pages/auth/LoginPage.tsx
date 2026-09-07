// Login page component — matches new Navy/Blue brand login design.
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login } from "../../api/auth";
import { ApiClientError } from "../../api/client";
import { PasswordField } from "../../components/PasswordField";
import { ErrorPopup } from "../../components/ErrorPopup";
import { ThemeToggle } from "../../components/ThemeToggle";

interface LoginPageProps {
  onLoggedIn: () => void;
}

export function LoginPage({ onLoggedIn }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Enter username and password");
      return;
    }
    setSubmitting(true);
    try {
      const res = await login(username.trim(), password);
      onLoggedIn();
      if (res.user.must_change_password) {
        navigate("/force-password-change");
      } else {
        navigate(res.redirect || "/");
      }
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
      <ErrorPopup message={error} onClose={() => setError(null)} />
      <ThemeToggle className="auth-theme-toggle" />
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
          <h2>Login</h2>
          <p className="sub">Sign in to continue</p>

          <form onSubmit={handleSubmit}>
            <div className="brandlogin-field">
              <label htmlFor="username">Username</label>
              <input
                id="username"
                name="username"
                type="text"
                required
                autoFocus
                autoComplete="username"
                placeholder="Enter username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            <PasswordField
              id="password"
              label="Password"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              placeholder="Enter password"
            />

            <div className="brandlogin-links">
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
                >
                  <circle cx="7.5" cy="15.5" r="5.5" />
                  <path d="m21 2-9.6 9.6" />
                  <path d="m15.5 7.5 3 3" />
                  <path d="m18.5 4.5 3 3" />
                </svg>
                <span>Forgot password?</span>
              </Link>
            </div>

            <button type="submit" id="login-submit" className="brandlogin-btn" disabled={submitting}>
              {submitting ? "Signing in…" : "Login"}
            </button>

            <p className="brandlogin-switch">
              New here? <Link to="/register">Create an account</Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
