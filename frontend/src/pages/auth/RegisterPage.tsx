// Student self-registration — matches LoginPage's Navy/Blue brand shell.
// Only STUDENT accounts can self-register this way (never FACULTY/HOD).
// Existing roll numbers (HOD-entered) just claim a login as before. New
// roll numbers also create the student record itself — gated server-side
// by database.is_open_registration_enabled().
//
// Email is mandatory. Registration is gated on an explicit OTP verification
// for that exact email before the account-creation request is sent.
import { useState, useEffect, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { register, sendOtp, verifyOtp } from "../../api/auth";
import { ApiClientError } from "../../api/client";
import { PasswordField } from "../../components/PasswordField";
import { ErrorPopup, WarningPopup } from "../../components/ErrorPopup";
import { ThemeToggle } from "../../components/ThemeToggle";

type EmailStatus = "idle" | "sending" | "sent" | "verifying" | "verified";

export function RegisterPage() {
  const navigate = useNavigate();
  const [rollNo, setRollNo] = useState("");
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [phone, setPhone] = useState("");
  const [yearOfStudy, setYearOfStudy] = useState("1");
  const [email, setEmail] = useState("");
  const [emailLocked, setEmailLocked] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [emailStatus, setEmailStatus] = useState<EmailStatus>("idle");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailNotice, setEmailNotice] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [timerSeconds, setTimerSeconds] = useState<number>(0);

  useEffect(() => {
    if (timerSeconds <= 0) return;
    const interval = setInterval(() => {
      setTimerSeconds((prev) => prev - 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [timerSeconds]);

  function formatTime(secs: number): string {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }

  function isValidEmail(value: string): boolean {
    return /\S+@\S+\.\S+/.test(value);
  }

  function resetOtpState() {
    setEmailStatus("idle");
    setEmailLocked(false);
    setOtpCode("");
    setEmailError(null);
    setEmailNotice(null);
    setTimerSeconds(0);
  }

  async function handleSendOtp(): Promise<boolean> {
    setEmailError(null);
    setEmailNotice(null);
    setWarning(null);
    const trimmed = email.trim().toLowerCase();
    if (!trimmed || !isValidEmail(trimmed)) {
      setWarning("Please enter a valid email address first");
      return false;
    }
    setEmailStatus("sending");
    try {
      const res = await sendOtp(trimmed, "REGISTER");
      setEmailStatus("sent");
      setEmailLocked(true);
      setEmailNotice(res.message);
      setTimerSeconds(600); // 10 minutes
      return true;
    } catch (err) {
      setEmailStatus("idle");
      if (err instanceof ApiClientError) {
        setEmailError(err.message);
      } else {
        setEmailError("Could not send code. Try again.");
      }
      return false;
    }
  }

  async function handleVerifyOtp() {
    setEmailError(null);
    setEmailNotice(null);
    setWarning(null);
    const trimmedEmail = email.trim().toLowerCase();
    const trimmedCode = otpCode.trim();
    if (timerSeconds <= 0 && emailStatus === "sent") {
      setWarning("OTP expired (10-minute limit). Click 'Resend New OTP' to receive a fresh code.");
      return;
    }
    if (!trimmedCode || trimmedCode.length !== 6) {
      setWarning("Enter the 6-digit verification code sent to your email");
      return;
    }
    setEmailStatus("verifying");
    try {
      await verifyOtp(trimmedEmail, "REGISTER", trimmedCode);
      setEmailStatus("verified");
      setTimerSeconds(0);
    } catch (err) {
      setEmailStatus("sent");
      if (err instanceof ApiClientError) {
        setEmailError(err.message);
      } else {
        setEmailError("Invalid code. Try again.");
      }
    }
  }

  function handleChangeEmail() {
    resetOtpState();
    setEmail("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setWarning(null);
    setSuccess(null);

    if (!rollNo.trim() || !username.trim() || !password || !confirmPassword || !email.trim()) {
      setWarning("Fill in every required field");
      return;
    }
    if (!isValidEmail(email.trim())) {
      setWarning("Enter a valid email address");
      return;
    }
    if (password !== confirmPassword) {
      setWarning("Passwords do not match");
      return;
    }
    if (password.length < 8) {
      setWarning("Password must be at least 8 characters");
      return;
    }
    if (emailStatus !== "verified") {
      if (emailStatus === "idle") {
        const sent = await handleSendOtp();
        if (sent) setWarning("Verification OTP sent. Enter the code from your email.");
        return;
      }
      if (emailStatus === "sent" && otpCode.trim().length === 6) {
        try {
          await verifyOtp(email.trim().toLowerCase(), "REGISTER", otpCode.trim());
          setEmailStatus("verified");
        } catch (err) {
          if (err instanceof ApiClientError) {
            setError(err.message);
          } else {
            setError("Invalid verification code. Please check the code and try again.");
          }
          return;
        }
      } else {
        setWarning("Please enter the 6-digit verification code sent to your email.");
        return;
      }
    }


    setSubmitting(true);
    try {
      const res = await register(
        rollNo.trim(),
        username.trim(),
        password,
        confirmPassword,
        fullName.trim(),
        email.trim().toLowerCase(),
        phone.trim(),
        yearOfStudy
      );
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
      <WarningPopup message={warning} onClose={() => setWarning(null)} />
      <ErrorPopup message={error || emailError} onClose={() => { setError(null); setEmailError(null); }} />
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
          <h2>Create Account</h2>
          <p className="sub">Register with your roll number — email verification is required</p>

          {success && (
            <div className="success-banner" style={{ marginBottom: 18 }}>
              <span>{success}</span>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="brandlogin-field">
              <label htmlFor="roll_no">Roll Number <span style={{ color: "#ef4444" }}>*</span></label>
              <input
                id="roll_no"
                name="roll_no"
                type="text"
                required
                autoFocus
                placeholder="e.g. 24BT1A6701"
                value={rollNo}
                onChange={(e) => setRollNo(e.target.value)}
              />
            </div>

            <div className="brandlogin-field">
              <label htmlFor="year_of_study">Year of Study & Batch <span style={{ color: "#ef4444" }}>*</span></label>
              <select
                id="year_of_study"
                name="year_of_study"
                value={yearOfStudy}
                onChange={(e) => setYearOfStudy(e.target.value)}
                style={{ height: 42, width: "100%", padding: "0 12px", border: "1.5px solid var(--border)", borderRadius: 10, fontSize: 14, background: "var(--input-bg)", color: "var(--text)" }}
              >
                <option value="1">1st Year (2026-2030 Batch)</option>
                <option value="2">2nd Year (2025-2029 Batch)</option>
                <option value="3">3rd Year (2024-2028 Batch)</option>
                <option value="4">4th Year (2023-2027 Batch)</option>
              </select>
            </div>

            <div className="brandlogin-field">
              <label htmlFor="phone">Mobile Number</label>
              <input
                id="phone"
                name="phone"
                type="tel"
                placeholder="Enter 10-digit mobile number"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </div>

            <div className="brandlogin-field">
              <label htmlFor="full_name">Full Name</label>
              <input
                id="full_name"
                name="full_name"
                type="text"
                placeholder="Enter your full name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </div>

            <div className="brandlogin-field">
              <label htmlFor="username">Choose a Username <span style={{ color: "#ef4444" }}>*</span></label>
              <input
                id="username"
                name="username"
                type="text"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>

            <PasswordField
              id="password"
              label="Password"
              value={password}
              onChange={setPassword}
            />

            <PasswordField
              id="confirm_password"
              label="Confirm Password"
              value={confirmPassword}
              onChange={setConfirmPassword}
            />

            {/* — Email verification (mandatory) */}
            <div className="brandlogin-field">
              <label htmlFor="email">Email Address <span style={{ color: "#ef4444" }}>*</span></label>
              <input
                id="email"
                name="email"
                type="email"
                required
                placeholder="Enter email to receive OTP verification code"
                value={email}
                disabled={emailLocked}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            {emailError && (
              <div className="error-banner" style={{ marginTop: 10, marginBottom: 0 }}>
                <span>{emailError}</span>
              </div>
            )}
            {emailNotice && emailStatus === "sent" && (
              <p className="otp-sent-to" style={{ marginTop: 10, fontSize: 13, color: "var(--heading-accent)", fontWeight: 600 }}>{emailNotice}</p>
            )}

            {email.trim() && emailStatus === "idle" && (
              <button
                type="button"
                className="otp-resend-btn"
                style={{ marginTop: 10, width: "100%", padding: "12px", borderRadius: 10, background: "linear-gradient(135deg, #0284c7, #2563eb)", color: "#fff", fontWeight: 700, border: "none", cursor: "pointer" }}
                onClick={handleSendOtp}
              >
                📩 Send Verification OTP
              </button>
            )}

            {emailStatus === "sending" && (
              <button type="button" className="otp-resend-btn" style={{ marginTop: 10, width: "100%", padding: "12px", borderRadius: 10 }} disabled>
                Sending OTP Code…
              </button>
            )}

            {(emailStatus === "sent" || emailStatus === "verifying") && (
              <div style={{ marginTop: 12, padding: 14, background: "var(--chip-bg-muted)", borderRadius: 12, border: "1px solid var(--border)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text)" }}>🔐 Enter 6-Digit OTP</span>
                  {timerSeconds > 0 ? (
                    <span style={{ fontSize: 12, fontWeight: 800, color: timerSeconds < 120 ? "#f43f5e" : "#10b981", background: "rgba(0,0,0,0.2)", padding: "2px 8px", borderRadius: 6 }}>
                      ⏱️ Valid for: {formatTime(timerSeconds)}
                    </span>
                  ) : (
                    <span style={{ fontSize: 12, fontWeight: 800, color: "#f43f5e" }}>
                      ❌ OTP Expired (10m)
                    </span>
                  )}
                </div>

                <div className="otp-row" style={{ display: "flex", gap: 10 }}>
                  <div className="brandlogin-field otp-code-input" style={{ flex: 1 }}>
                    <input
                      id="otp_code"
                      name="otp_code"
                      type="text"
                      inputMode="numeric"
                      maxLength={6}
                      placeholder="••••••"
                      value={otpCode}
                      onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
                      style={{ letterSpacing: "4px", textAlign: "center", fontWeight: 800, fontSize: 16, fontFamily: "monospace", padding: "10px", background: "var(--input-bg)", color: "var(--text)", borderRadius: 8, border: "1px solid var(--input-border)" }}
                    />
                  </div>
                  <button
                    type="button"
                    className="otp-resend-btn"
                    style={{ background: "linear-gradient(135deg, #10b981, #059669)", color: "#fff", fontWeight: 800, padding: "10px 18px", borderRadius: 8, border: "none", cursor: "pointer" }}
                    disabled={emailStatus === "verifying" || timerSeconds <= 0}
                    onClick={handleVerifyOtp}
                  >
                    {emailStatus === "verifying" ? "Verifying…" : "Confirm OTP"}
                  </button>
                </div>

                <div style={{ marginTop: 10, textAlign: "center" }}>
                  <button
                    type="button"
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--heading-accent)", fontSize: 12, fontWeight: 700, textDecoration: "underline" }}
                    onClick={handleSendOtp}
                  >
                    🔄 Resend New OTP Code
                  </button>
                </div>
              </div>
            )}

            {emailStatus === "verified" && (
              <div className="otp-verified-badge">
                ✓ Email verified
                <button
                  type="button"
                  onClick={handleChangeEmail}
                  style={{ background: "none", border: "none", color: "#93a0c4", cursor: "pointer", fontSize: 12, marginLeft: 8, textDecoration: "underline" }}
                >
                  change
                </button>
              </div>
            )}

            <button
              type="submit"
              id="register-submit"
              className="brandlogin-btn"
              disabled={submitting}
              style={{ marginTop: 20, cursor: submitting ? "not-allowed" : "pointer" }}
            >
              {submitting ? "Creating account…" : "Register / Create Account"}
            </button>

            <p className="brandlogin-switch">
              Already have an account? <Link to="/login">Sign in</Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
