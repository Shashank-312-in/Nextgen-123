import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { type CurrentUser, logout } from "../api/auth";
import { navItemsFor } from "../nav";
import { getMySmsAccess } from "../api/logs";
import { ReportProblemModal } from "./ReportProblemModal";
import { ClassReminders } from "./ClassReminders";

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
  const mobileCloseButtonRef = useRef<HTMLButtonElement | null>(null);
  const mobileNavItemRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const restoreFocusRef = useRef<HTMLElement | null>(null);

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

  const navItemSignature = items.map((item) => item.key).join("|");

  useEffect(() => {
    const activeItem = mobileNavItemRefs.current[activeNav];
    if (!activeItem) return;
    const id = window.requestAnimationFrame(() => {
      activeItem.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    });
    return () => window.cancelAnimationFrame(id);
  }, [activeNav, navItemSignature]);

  useEffect(() => {
    if (!mobileNavOpen) return;
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusId = window.requestAnimationFrame(() => mobileCloseButtonRef.current?.focus());

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileNavOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.cancelAnimationFrame(focusId);
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      window.setTimeout(() => restoreFocusRef.current?.focus(), 0);
    };
  }, [mobileNavOpen]);

  const closeMobileNav = () => setMobileNavOpen(false);
  const openMobileNav = () => setMobileNavOpen(true);

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
        <nav className="nav-links ng-nav-links" aria-label="Primary navigation">
          {items.map((item) => (
            <Link key={item.key} to={item.href} className={`nav-link ng-nav-link${item.key === activeNav ? " active" : ""}`}>
              <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className="ng-sidebar-bottom">
          <button className="ng-sidebar-action" type="button" onClick={() => setIsReportModalOpen(true)}>Report a problem</button>
          <button className="ng-sidebar-action danger" type="button" onClick={handleLogout}>Log out</button>
        </div>
      </aside>

      {user.role === "FACULTY" && <ClassReminders />}
      <main className="main-area ng-main">
        <header className="main-top ng-topbar">
          <div className="ng-mobile-brand">
            <button
              type="button"
              className="ng-mobile-brand-action"
              onClick={openMobileNav}
              aria-label="Open navigation"
              aria-expanded={mobileNavOpen}
              aria-controls="mobile-navigation-sheet"
            >
              <img src="/logo.png" alt="NextGen SMS" />
            </button>
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

      <nav className="bottom-nav ng-mobile-nav" aria-label="Quick navigation">
        <div className="ng-mobile-nav-scroll" tabIndex={0}>
          {items.map((item) => (
            <Link
              key={item.key}
              ref={(node) => { mobileNavItemRefs.current[item.key] = node; }}
              to={item.href}
              className={`ng-mobile-nav-item${item.key === activeNav ? " active" : ""}`}
              aria-current={item.key === activeNav ? "page" : undefined}
            >
              <span className="nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
              <span>{item.label}</span>
            </Link>
          ))}
        </div>
      </nav>

      {mobileNavOpen && (
        <div className="ng-mobile-sheet-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeMobileNav(); }}>
          <section
            id="mobile-navigation-sheet"
            className="ng-mobile-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mobile-navigation-title"
          >
            <div className="ng-sheet-handle" aria-hidden="true" />
            <div className="ng-sheet-head">
              <div>
                <span className="ng-section-kicker">Navigation</span>
                <h2 id="mobile-navigation-title">NextGen SMS</h2>
              </div>
              <button ref={mobileCloseButtonRef} type="button" className="ng-close" onClick={closeMobileNav} aria-label="Close navigation">×</button>
            </div>

            <nav className="ng-sheet-grid" aria-label="All application destinations">
              {items.map((item) => (
                <Link
                  key={item.key}
                  to={item.href}
                  onClick={closeMobileNav}
                  className={`ng-sheet-item${item.key === activeNav ? " active" : ""}`}
                  aria-current={item.key === activeNav ? "page" : undefined}
                >
                  <span className="ng-sheet-item-icon nav-icon" dangerouslySetInnerHTML={{ __html: item.icon }} />
                  <span className="ng-sheet-item-label">{item.label}</span>
                  {item.key === activeNav && <span className="ng-sheet-check" aria-hidden="true">✓</span>}
                </Link>
              ))}
              <button type="button" className="ng-sheet-item ng-sheet-utility" onClick={() => { closeMobileNav(); setIsReportModalOpen(true); }}>
                <span className="ng-sheet-item-label">Report a problem</span>
              </button>
              <button type="button" className="ng-sheet-item ng-sheet-utility danger" onClick={handleLogout}>
                <span className="ng-sheet-item-label">Log out</span>
              </button>
            </nav>
          </section>
        </div>
      )}

      <ReportProblemModal isOpen={isReportModalOpen} onClose={() => setIsReportModalOpen(false)} />
    </div>
  );
}
