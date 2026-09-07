// Port of webapp/nav.py — nav_items_for(). Same per-role item list feeds
// both the desktop nav-rail and mobile bottom-nav (AppShell.tsx).
//
// Icons: inline SVG strings (Lucide-style, stroke-based, 24×24 viewBox).
// Using currentColor so they inherit the link's color and respond to
// dark/light mode and active states without extra CSS.

import type { Role } from "./api/auth";

export interface NavItem {
  href: string;
  icon: string; // inline SVG string
  label: string;
  key: string;
  disabled?: boolean;
}

// ── Reusable SVG icon strings ──────────────────────────────────────────────

const ICONS = {
  // User circle / profile
  profile: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="8" r="4"/>
    <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
  </svg>`,

  // Bar chart – attendance / mark attendance
  attendance: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="3" y="12" width="4" height="9" rx="1"/>
    <rect x="10" y="7" width="4" height="14" rx="1"/>
    <rect x="17" y="3" width="4" height="18" rx="1"/>
  </svg>`,

  // Trending up – HOD overview / summary
  trending: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
    <polyline points="16 7 22 7 22 13"/>
  </svg>`,

  // Graduation cap – faculty
  faculty: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
    <path d="M6 12v5c3 3 9 3 12 0v-5"/>
  </svg>`,

  // Book open – subjects
  subjects: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
  </svg>`,

  // Users – students
  students: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
  </svg>`,

  // Calendar – academic calendar
  calendar: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
    <line x1="16" y1="2" x2="16" y2="6"/>
    <line x1="8" y1="2" x2="8" y2="6"/>
    <line x1="3" y1="10" x2="21" y2="10"/>
  </svg>`,

  // Shield check – audit log
  audit: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    <polyline points="9 12 11 14 15 10"/>
  </svg>`,

  // Message square – SMS log
  sms: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    <line x1="9" y1="10" x2="9" y2="10"/>
    <line x1="12" y1="10" x2="12" y2="10"/>
    <line x1="15" y1="10" x2="15" y2="10"/>
  </svg>`,

  // Alert triangle – problem reports
  reports: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>`,
};

// ── Nav item definitions per role ──────────────────────────────────────────

export function navItemsFor(role: Role): NavItem[] {
  if (role === "STUDENT") {
    return [
      { href: "/me/profile", icon: ICONS.profile, label: "Profile", key: "profile" },
      { href: "/student-dashboard", icon: ICONS.trending, label: "Attendance Summary", key: "attendance-summary" },
      { href: "/academic-calendar", icon: ICONS.calendar, label: "Academic Calendar", key: "academic-calendar" },
    ];
  }
  if (role === "FACULTY") {
    return [
      { href: "/me/account", icon: ICONS.profile, label: "Profile", key: "account" },
      { href: "/attendance", icon: ICONS.attendance, label: "Mark Attendance", key: "attendance" },
      { href: "/students", icon: ICONS.students, label: "Students", key: "students" },
      { href: "/academic-calendar", icon: ICONS.calendar, label: "Academic Calendar", key: "academic-calendar" },
    ];
  }
  if (role === "ADMIN") {
    return [
      { href: "/me/account", icon: ICONS.profile, label: "Profile", key: "account" },
      { href: "/attendance", icon: ICONS.attendance, label: "Mark Attendance", key: "attendance" },
      { href: "/hod-dashboard", icon: ICONS.trending, label: "Admin Overview", key: "hod-dashboard" },
      { href: "/faculty", icon: ICONS.faculty, label: "Faculty", key: "faculty" },
      { href: "/subjects", icon: ICONS.subjects, label: "Subjects", key: "subjects" },
      { href: "/students", icon: ICONS.students, label: "Students", key: "students" },
      { href: "/academic-calendar", icon: ICONS.calendar, label: "Academic Calendar", key: "academic-calendar" },
      { href: "/audit-log", icon: ICONS.audit, label: "Audit Log", key: "audit" },
      { href: "/sms-log", icon: ICONS.sms, label: "SMS Log", key: "sms-log" },
      { href: "/problem-reports", icon: ICONS.reports, label: "Problem Reports", key: "problem-reports" },
    ];
  }
  // HOD
  return [
    { href: "/me/account", icon: ICONS.profile, label: "Profile", key: "account" },
    { href: "/hod-dashboard", icon: ICONS.trending, label: "HOD Overview", key: "hod-dashboard" },
    { href: "/faculty", icon: ICONS.faculty, label: "Faculty", key: "faculty" },
    { href: "/subjects", icon: ICONS.subjects, label: "Subjects", key: "subjects" },
    { href: "/students", icon: ICONS.students, label: "Students", key: "students" },
    { href: "/academic-calendar", icon: ICONS.calendar, label: "Academic Calendar", key: "academic-calendar" },
    { href: "/audit-log", icon: ICONS.audit, label: "Audit Log", key: "audit" },
    { href: "/sms-log", icon: ICONS.sms, label: "SMS Log", key: "sms-log" },
    { href: "/problem-reports", icon: ICONS.reports, label: "Problem Reports", key: "problem-reports" },
  ];
}