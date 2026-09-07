// ProfileAvatar — A clickable profile icon shown on every dashboard's top header.
// On click, opens a small popover to upload a photo.
// The photo is stored in localStorage (keyed by username) so it persists
// across sessions without needing a backend upload endpoint.
// Shows the uploaded photo if available, otherwise falls back to the SVG person icon.

import { useRef, useState, useEffect } from "react";

interface ProfileAvatarProps {
  username: string;
  tooltipLabel?: string;
}

const STORAGE_KEY = (username: string) => `profile_photo_${username}`;

export function ProfileAvatar({ username, tooltipLabel }: ProfileAvatarProps) {
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Load saved photo from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY(username));
    if (saved) setPhotoUrl(saved);
  }, [username]);

  // Close popover when clicking outside
  useEffect(() => {
    if (!popoverOpen) return;
    function handleOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setPopoverOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [popoverOpen]);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const url = ev.target?.result as string;
      localStorage.setItem(STORAGE_KEY(username), url);
      setPhotoUrl(url);
      setPopoverOpen(false);
    };
    reader.readAsDataURL(file);
  }

  function handleRemovePhoto() {
    localStorage.removeItem(STORAGE_KEY(username));
    setPhotoUrl(null);
    setPopoverOpen(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const title = tooltipLabel ?? `${username} — click to change photo`;

  return (
    <div className="profile-avatar-wrap" ref={wrapperRef} style={{ position: "relative", display: "inline-block" }}>
      <button
        className="whoami-icon"
        title={title}
        onClick={() => setPopoverOpen((v) => !v)}
        aria-label={`Profile picture for ${username}`}
        type="button"
        style={{
          width: 40,
          height: 40,
          borderRadius: "50%",
          padding: 0,
          border: "2px solid var(--heading-accent)",
          background: "var(--input-bg)",
          color: "var(--heading-accent)",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
          overflow: "hidden",
          transition: "transform 0.2s ease, box-shadow 0.2s ease",
        }}
      >
        {photoUrl ? (
          <img
            src={photoUrl}
            alt={username}
            style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "50%" }}
          />
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        )}

        {/* Small Camera Icon Badge Overlay */}
        <div style={{
          position: "absolute",
          bottom: 0,
          right: 0,
          left: 0,
          height: "38%",
          background: "rgba(0, 0, 0, 0.55)",
          backdropFilter: "blur(2px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#ffffff",
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
            <circle cx="12" cy="13" r="4"/>
          </svg>
        </div>
      </button>

      {popoverOpen && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            zIndex: 1100,
            background: "var(--card-glass)",
            backdropFilter: "blur(24px)",
            WebkitBackdropFilter: "blur(24px)",
            border: "1.5px solid var(--border)",
            borderRadius: 18,
            padding: "16px",
            boxShadow: "0 16px 40px rgba(0,0,0,0.35)",
            minWidth: 150,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12,
            animation: "fadeIn 0.2s ease",
          }}
        >
          {/* Avatar Preview */}
          <div style={{ position: "relative", width: 64, height: 64 }}>
            {photoUrl ? (
              <img
                src={photoUrl}
                alt="Current profile"
                style={{ width: 64, height: 64, borderRadius: "50%", objectFit: "cover", border: "2px solid var(--heading-accent)" }}
              />
            ) : (
              <div style={{
                width: 64, height: 64, borderRadius: "50%",
                background: "var(--chip-bg-muted)", border: "2px dashed var(--heading-accent)",
                display: "flex", alignItems: "center", justifyContent: "center", color: "var(--heading-accent)"
              }}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </div>
            )}
          </div>

          <div style={{ fontWeight: 800, fontSize: 13, color: "var(--text)" }}>{username}</div>

          {/* Pure Icon Action Buttons — NO TEXT LABELS */}
          <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "center" }}>
            {/* Upload / Camera Icon Button */}
            <button
              title={photoUrl ? "Change Photo" : "Upload Photo"}
              aria-label="Upload photo"
              onClick={() => fileInputRef.current?.click()}
              type="button"
              style={{
                width: 42,
                height: 42,
                borderRadius: 12,
                border: "none",
                background: "linear-gradient(135deg, #0284c7, #2563eb)",
                color: "#ffffff",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 4px 14px rgba(56, 189, 248, 0.4)",
                transition: "transform 0.2s ease",
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
                <circle cx="12" cy="13" r="4"/>
              </svg>
            </button>

            {/* Remove / Trash Icon Button */}
            {photoUrl && (
              <button
                title="Remove Photo"
                aria-label="Remove photo"
                onClick={handleRemovePhoto}
                type="button"
                style={{
                  width: 42,
                  height: 42,
                  borderRadius: 12,
                  border: "none",
                  background: "linear-gradient(135deg, #ef4444, #dc2626)",
                  color: "#ffffff",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  boxShadow: "0 4px 14px rgba(239, 68, 68, 0.4)",
                  transition: "transform 0.2s ease",
                }}
              >
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
        </div>
      )}
    </div>
  );
}
