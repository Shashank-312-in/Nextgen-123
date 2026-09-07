import { useEffect } from "react";

export type ToastType = "warning" | "error" | "success" | "info";

export interface ToastPopupProps {
  type?: ToastType;
  title?: string;
  message: string | null;
  onClose: () => void;
  autoDismissMs?: number;
}

export function ToastPopup({
  type = "warning",
  title,
  message,
  onClose,
  autoDismissMs = 2500,
}: ToastPopupProps) {
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => {
      onClose();
    }, autoDismissMs);
    return () => clearTimeout(timer);
  }, [message, onClose, autoDismissMs]);

  if (!message) return null;

  const defaultTitles: Record<ToastType, string> = {
    warning: "Warning",
    error: "Error",
    success: "Success",
    info: "Notice",
  };

  let displayTitle = title ?? defaultTitles[type];
  const cleanMsg = message.trim();
  const cleanTitle = displayTitle.trim();

  // Deduplicate: if title is identical to message or message starts with title, use clean single-word badge
  if (
    cleanTitle.toLowerCase() === cleanMsg.toLowerCase() ||
    cleanMsg.toLowerCase().startsWith(cleanTitle.toLowerCase())
  ) {
    displayTitle = defaultTitles[type];
  }

  const icons: Record<ToastType, JSX.Element> = {
    warning: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
    ),
    error: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
    ),
    success: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
        <polyline points="22 4 12 14.01 9 11.01" />
      </svg>
    ),
    info: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
    ),
  };

  return (
    <div className={`toast-overlay toast-type-${type}`}>
      <div className={`toast-card toast-${type}`} role="alert" aria-live="assertive">
        <div className="toast-content">
          <div className="toast-icon-badge">{icons[type]}</div>
          <div className="toast-text">
            <strong className="toast-title">{displayTitle}</strong>
            <p className="toast-message">{cleanMsg}</p>
          </div>
        </div>
        <button
          type="button"
          className="toast-close-btn"
          onClick={onClose}
          aria-label="Close notification"
        >
          &times;
        </button>
        {/* 3D Time Limit Progress Bar */}
        <div className="toast-timer-bar-wrapper">
          <div
            className="toast-timer-bar-fill"
            style={{ animationDuration: `${autoDismissMs}ms` }}
          />
        </div>
      </div>
    </div>
  );
}

export function WarningPopup(props: Omit<ToastPopupProps, "type">) {
  return <ToastPopup {...props} type="warning" />;
}

export function ErrorPopup(props: Omit<ToastPopupProps, "type">) {
  return <ToastPopup {...props} type="error" title={props.title ?? "Error"} />;
}
