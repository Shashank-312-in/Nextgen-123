// Shared password input with a show/hide eye-icon toggle — used by Login,
// Register, and Reset Password pages so the toggle behavior/markup lives
// in one place instead of being copy-pasted three times.
import { useState } from "react";

interface PasswordFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
  placeholder?: string;
  autoComplete?: string;
}

export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoFocus,
  placeholder = "Enter password",
  autoComplete = "new-password",
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="brandlogin-field">
      <label htmlFor={id}>{label}</label>
      <div className="brandlogin-password-wrap">
        <input
          id={id}
          name={id}
          type={visible ? "text" : "password"}
          required
          autoFocus={autoFocus}
          autoComplete={autoComplete}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          className="brandlogin-eye"
          aria-label={visible ? "Hide password" : "Show password"}
          onClick={() => setVisible((v) => !v)}
        >
          {visible ? (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
              <line x1="3" y1="21" x2="21" y2="3" />
            </svg>
          ) : (
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
