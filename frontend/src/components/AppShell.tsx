// Shared shell for every authenticated page — ported from webapp/templates/
// base.html's app-shell/nav-rail/bottom-nav markup. Before this component,
// HodDashboard/StudentDashboard/AttendanceSetupPage each hand-rolled their
// own copy of this nav with different hardcoded active/disabled links
// (see git history if this ever needs comparing) — that meant adding a
// real Students link required editing 3 files. Now it's edited in one
// place: nav.ts's per-role list.
//
// Usage: wrap a page's content in <AppShell user=... activeNav="..."
// heading="..." onLoggedOut={...}> ... </AppShell>. `activeNav` must match
// one of nav.ts's `key` values for that role, or nothing highlights —
// that's a deliberate signal (not a crash) that the page passed the wrong
// key, easy to spot visually.
import { useState, type ReactNode } from "react";
import { useNavigate, Link } from "react-router-dom";
import { type CurrentUser, logout } from "../api/auth";
import { navItemsFor } from "../nav";
import { ReportProblemModal } from "./ReportProblemModal";
import { ThemeToggle } from "./ThemeToggle";
import { ProfileAvatar } from "./ProfileAvatar";

interface AppShellProps {
  user: CurrentUser;
  activeNav: string;
  heading: string;
  whoami?: string; // defaults to "username (ROLE)" — pages override for richer context (e.g. roll_no)
  onLoggedOut: () => void;
  children: ReactNode;
}

export function AppShell({ user, activeNav, heading, whoami, onLoggedOut, children }: AppShellProps) {
  const navigate = useNavigate();
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const items = navItemsFor(user.role).filter((item) => !item.disabled);

  // Reserve 1 slot for the always-visible Logout button
  // If items count > 3, split into primary (first 3) and overflow items (remaining) + More tab
  const showMoreTab = items.length > 3;
  const primaryItems = showMoreTab ? items.slice(0, 3) : items;
  const overflowItems = showMoreTab ? items.slice(3) : [];
  const isOverflowActive = showMoreTab && overflowItems.some((it) => it.key === activeNav);

  async function handleLogout() {
    try {
      await logout();
    } catch (err) {
      console.warn("Logout failed:", err);
    } finally {
      onLoggedOut();
      navigate("/login");
    }
  }


  return (
    <div className="app-shell">
      <nav className="nav-rail">
        <div className="nav-brand-header" style={{ padding: "0 12px", marginBottom: 20, display: "flex", alignItems: "center", gap: 12 }}>
          <img
            src="/logo.png"
            alt="NextGen SMS Logo"
            style={{ width: 44, height: 44, borderRadius: 10, objectFit: "cover", boxShadow: "0 4px 12px rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.2)" }}
          />
          <div>
            <div style={{
              fontFamily: "'Outfit', sans-serif",
              fontSize: 17,
              fontWeight: 800,
              color: "#ffffff",
              letterSpacing: "-0.02em",
              lineHeight: 1.2
            }}>
              NextGen SMS
            </div>
            <div style={{ fontSize: 11, color: "#7dd3fc", fontWeight: 800, letterSpacing: "0.8px", textTransform: "uppercase", marginTop: 3 }}>
              {user.role === "ADMIN" ? "Admin" : user.role === "HOD" ? "HOD" : user.role} Portal
            </div>
          </div>
        </div>
        <div className="nav-links">
          {navItemsFor(user.role).map((item) =>
            item.disabled ? (
              <button key={item.key} className="nav-link" disabled title="Coming soon">
                <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} /> {item.label}
              </button>
            ) : (
              <Link
                key={item.key}
                to={item.href}
                className={`nav-link${item.key === activeNav ? " active" : ""}`}
              >
                <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} /> {item.label}
              </Link>
            )
          )}
        </div>
        <div className="nav-footer">
          <div style={{ padding: "0 14px", color: "#e2e8f0", fontSize: 12, fontWeight: 700, marginBottom: 10 }}>
            {user.username} &middot; {user.role === "ADMIN" ? "Administrator" : user.role === "HOD" ? "Head of Department" : user.role}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <button
              className="nav-link"
              onClick={() => setIsReportModalOpen(true)}
              style={{ color: "#fde047", fontWeight: 700 }}
              title="Report an issue or bug with the application"
            >
              <span className="nav-icon" style={{ color: "#fde047" }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </span> Report Problem
            </button>
            <button className="nav-link" onClick={handleLogout} style={{ color: "#fca5a5", fontWeight: 700 }}>
              <span className="nav-icon" style={{ color: "#fca5a5" }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
              </span> Log out
            </button>
          </div>
        </div>
      </nav>

      <div className="main-area">
        <div className="main-top">
          <h1>{heading}</h1>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <ThemeToggle />
          </div>
        </div>
        <div className="main-body">{children}</div>
      </div>

      {/* macOS Mobile Sliding Floating Dock Navigation */}
      <nav className="bottom-nav mac-dock-nav">
        <div className="mac-dock-container">
          <div className="mac-dock-track">
            {items.map((item) => {
              const isActive = item.key === activeNav;
              return (
                <Link
                  key={item.key}
                  to={item.href}
                  className={`mac-dock-item ${isActive ? "active" : ""}`}
                >
                  <div className="mac-dock-icon-box">
                    <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
                    {isActive && <span className="mac-active-dot" />}
                  </div>
                  <span className="mac-dock-label">{item.label}</span>
                </Link>
              );
            })}

            <div className="mac-dock-divider" />

            <button
              type="button"
              className="mac-dock-item mac-dock-action-btn"
              onClick={() => setIsReportModalOpen(true)}
              title="Report Problem"
            >
              <div className="mac-dock-icon-box warn">
                <span className="nav-icon">
                  <svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                    <line x1="12" y1="9" x2="12" y2="13" />
                    <line x1="12" y1="17" x2="12.01" y2="17" />
                  </svg>
                </span>
              </div>
              <span className="mac-dock-label">Report</span>
            </button>

            <button
              type="button"
              className="mac-dock-item mac-dock-logout-btn"
              onClick={handleLogout}
              title="Log out"
            >
              <div className="mac-dock-icon-box danger">
                <span className="nav-icon">
                  <svg xmlns="http://www.w3.org/2000/svg" width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                </span>
              </div>
              <span className="mac-dock-label">Logout</span>
            </button>
          </div>
        </div>
      </nav>

      {/* Mobile Android Bottom Sheet Drawer */}
      {isDrawerOpen && (
        <div className="mobile-drawer-overlay" onClick={() => setIsDrawerOpen(false)}>
          <div className="mobile-drawer-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-handle-bar" />

            <div className="drawer-header">
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <ProfileAvatar username={user.username} />
                <div>
                  <div style={{ fontWeight: 700, fontSize: 16, color: "var(--fg)" }}>{user.username}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", fontWeight: 600 }}>{user.role} Portal</div>
                </div>
              </div>
              <button className="drawer-close-btn" onClick={() => setIsDrawerOpen(false)}>✕</button>
            </div>

            <div className="drawer-grid">
              {items.map((item) => {
                const isActive = item.key === activeNav;
                return (
                  <Link
                    key={item.key}
                    to={item.href}
                    className={`drawer-card ${isActive ? "active" : ""}`}
                    onClick={() => setIsDrawerOpen(false)}
                  >
                    <span className="drawer-card-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
                    <span className="drawer-card-label">{item.label}</span>
                  </Link>
                );
              })}
            </div>

            <div className="drawer-actions">
              <button
                className="drawer-action-btn report"
                onClick={() => {
                  setIsDrawerOpen(false);
                  setIsReportModalOpen(true);
                }}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                Report Problem
              </button>
              <button
                className="drawer-action-btn logout"
                onClick={handleLogout}
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <polyline points="16 17 21 12 16 7" />
                  <line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                Log Out
              </button>
            </div>
          </div>
        </div>
      )}

      <ReportProblemModal
        isOpen={isReportModalOpen}
        onClose={() => setIsReportModalOpen(false)}
      />
    </div>
  );
}