import { useTheme } from "../context/ThemeContext";

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className={`theme-switch-btn ${isDark ? "is-dark" : "is-light"} ${className ?? ""}`}
      onClick={toggleTheme}
      title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
      aria-label="Toggle dark and light mode switch"
      role="switch"
      aria-checked={!isDark}
    >
      <div className="theme-switch-track">
        <span className="theme-switch-icon moon-icon">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
          </svg>
        </span>
        <span className="theme-switch-icon sun-icon">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <circle cx="12" cy="12" r="4" fill="currentColor" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
          </svg>
        </span>
        <div className="theme-switch-knob">
          {isDark ? (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="4" fill="currentColor" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
            </svg>
          )}
        </div>
      </div>
    </button>
  );
}
