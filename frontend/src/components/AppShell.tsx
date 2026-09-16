import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { type CurrentUser, logout } from "../api/auth";
import { navItemsFor } from "../nav";
import { getMySmsAccess } from "../api/logs";
import { ReportProblemModal } from "./ReportProblemModal";
import { ProfileAvatar } from "./ProfileAvatar";

interface AppShellProps {
  user: CurrentUser;
  activeNav: string;
  heading: string;
  whoami?: string;
  onLoggedOut: () => void;
  children: ReactNode;
}

function roleLabel(role: CurrentUser["role"]) {
  if (role === "ADMIN") return "Administrator";
  if (role === "HOD") return "Head of Department";
  if (role === "FACULTY") return "Faculty";
  return "Student";
}

export function AppShell({ user, activeNav, heading, whoami, onLoggedOut, children }: AppShellProps) {
  const navigate = useNavigate();
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [smsGatewayAccess, setSmsGatewayAccess] = useState(user.role !== "FACULTY");

  useEffect(() => {
    let cancelled = false;
    if (user.role !== "FACULTY") {
      setSmsGatewayAccess(true);
      return () => { cancelled = true; };
    }
    setSmsGatewayAccess(false);
    void getMySmsAccess().then((access) => {
      if (!cancelled) setSmsGatewayAccess(Boolean(access.enabled));
    }).catch(() => {
      if (!cancelled) setSmsGatewayAccess(false);
    });
    return () => { cancelled = true; };
  }, [user.role, user.username]);

  const items = navItemsFor(user.role, { smsGatewayAccess }).filter((item) => !item.disabled);
  const role = roleLabel(user.role);

  async function handleLogout() {
    try { await logout(); } catch (err) { console.warn("Logout failed:", err); }
    finally { onLoggedOut(); navigate("/login"); }
  }

  return (
    <div className="app-shell ng-shell">
      <aside className="nav-rail ng-sidebar">
        <Link to="/" className="ng-brand" aria-label="NextGen SMS home">
          <img src="/logo.png" alt="NextGen SMS" className="ng-brand-logo" />
          <span className="ng-brand-copy">
            <strong>NextGen SMS</strong>
            <small>{role}</small>
          </span>
        </Link>

        <div className="ng-nav-label">Workspace</div>
        <nav className="nav-links ng-nav-links">
          {items.map((item) => (
            <Link key={item.key} to={item.href} className={`nav-link ng-nav-link${item.key === activeNav ? " active" : ""}`}>
              <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className="ng-sidebar-bottom">
          <div className="ng-user-card">
            <ProfileAvatar username={user.username} />
            <div className="ng-user-copy">
              <strong>{user.username}</strong>
              <span>{role}</span>
            </div>
          </div>
          <button className="ng-sidebar-action" type="button" onClick={() => setIsReportModalOpen(true)}>Report a problem</button>
          <button className="ng-sidebar-action danger" type="button" onClick={handleLogout}>Log out</button>
        </div>
      </aside>

      <main className="main-area ng-main">
        <header className="main-top ng-topbar">
          <div className="ng-mobile-brand">
            <button type="button" className="ng-mobile-menu" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation">☰</button>
            <img src="/logo.png" alt="NextGen SMS" />
          </div>
          <div className="ng-page-heading">
            <span className="ng-section-kicker">NextGen SMS</span>
            <h1>{heading}</h1>
            {whoami && <p>{whoami}</p>}
          </div>
          <div className="ng-topbar-role">{role}</div>
        </header>
        <div className="main-body ng-main-body">{children}</div>
      </main>

      <nav className="bottom-nav ng-mobile-nav" aria-label="Mobile navigation">
        {items.slice(0, 4).map((item) => (
          <Link key={item.key} to={item.href} className={`ng-mobile-nav-item${item.key === activeNav ? " active" : ""}`}>
            <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
            <span>{item.label}</span>
          </Link>
        ))}
        <button type="button" className={`ng-mobile-nav-item${mobileNavOpen ? " active" : ""}`} onClick={() => setMobileNavOpen(true)}>
          <span className="nav-icon">•••</span><span>More</span>
        </button>
      </nav>

      {mobileNavOpen && (
        <div className="ng-mobile-sheet-backdrop" onClick={() => setMobileNavOpen(false)}>
          <section className="ng-mobile-sheet" onClick={(e) => e.stopPropagation()} aria-label="More navigation">
            <div className="ng-sheet-handle" />
            <div className="ng-sheet-head">
              <div>
                <span className="ng-section-kicker">Navigation</span>
                <h2>NextGen SMS</h2>
              </div>
              <button type="button" className="ng-close" onClick={() => setMobileNavOpen(false)} aria-label="Close navigation">×</button>
            </div>
            <div className="ng-sheet-grid">
              {items.map((item) => (
                <Link key={item.key} to={item.href} onClick={() => setMobileNavOpen(false)} className={`ng-sheet-item${item.key === activeNav ? " active" : ""}`}>
                  <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
                  <span>{item.label}</span>
                </Link>
              ))}
            </div>
            <div className="ng-sheet-actions">
              <button type="button" onClick={() => { setMobileNavOpen(false); setIsReportModalOpen(true); }}>Report a problem</button>
              <button type="button" className="danger" onClick={handleLogout}>Log out</button>
            </div>
          </section>
        </div>
      )}

      <ReportProblemModal isOpen={isReportModalOpen} onClose={() => setIsReportModalOpen(false)} />
    </div>
  );
}
