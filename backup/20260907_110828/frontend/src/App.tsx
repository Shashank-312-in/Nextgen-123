// Route guard per plan §3.3 / handoff item 6.
import { Navigate, Route, Routes } from "react-router-dom";
import { useCurrentUser } from "./hooks/useCurrentUser";
import { LoginPage } from "./pages/auth/LoginPage";
import { RegisterPage } from "./pages/auth/RegisterPage";
import { ForgotPasswordPage } from "./pages/auth/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/auth/ResetPasswordPage";
import { ForcePasswordChangePage } from "./pages/auth/ForcePasswordChangePage";
import { DashboardPage } from "./pages/dashboard/DashboardPage";
import { HodDashboard } from "./pages/dashboard/HodDashboard";
import { StudentDashboard } from "./pages/dashboard/StudentDashboard";
import { AttendanceSetupPage } from "./pages/attendance/AttendanceSetupPage";
import { AttendanceRegisterPage } from "./pages/attendance/AttendanceRegisterPage";
import { StudentsListPage } from "./pages/students/StudentsListPage";
import { StudentFormPage } from "./pages/students/StudentFormPage";
import { StudentViewPage } from "./pages/students/StudentViewPage";
import { FacultyPage } from "./pages/faculty/FacultyPage";
import { SubjectsPage } from "./pages/subjects/SubjectsPage";
import { AcademicCalendarPage } from "./pages/academic-calendar/AcademicCalendarPage";
import { AccountPage } from "./pages/me/AccountPage";
import { ProfilePage } from "./pages/me/ProfilePage";
import { AuditLogPage } from "./pages/dashboard/AuditLogPage";
import { SmsLogPage } from "./pages/dashboard/SmsLogPage";
import { ProblemReportsPage } from "./pages/dashboard/ProblemReportsPage";
import { SplashScreen } from "./components/SplashScreen";
import { WindowLogoLoader } from "./components/WindowLogoLoader";

function Guard({
  user,
  reload,
  condition,
  fallback,
  children,
}: {
  user: ReturnType<typeof useCurrentUser>["user"];
  reload: () => void;
  condition?: boolean;
  fallback?: string;
  children: React.ReactElement;
}) {
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/force-password-change" replace />;
  if (condition === false) return <Navigate to={fallback ?? "/"} replace />;
  return children;
}

export function App() {
  const { user, loading, reload, clearUser } = useCurrentUser();

  const handleLoggedOut = () => {
    clearUser();
  };


  if (loading) {
    return <SplashScreen />;
  }

  return (
    <>
      <WindowLogoLoader />
      <Routes>
      {/* ── Unauthenticated / gate routes ── */}
      <Route
        path="/login"
        element={
          !user ? (
            <LoginPage onLoggedIn={reload} />
          ) : user.must_change_password ? (
            <Navigate to="/force-password-change" replace />
          ) : (
            <Navigate to="/" replace />
          )
        }
      />
      <Route
        path="/register"
        element={!user ? <RegisterPage /> : <Navigate to="/" replace />}
      />
      <Route
        path="/forgot-password"
        element={!user ? <ForgotPasswordPage /> : <Navigate to="/" replace />}
      />
      <Route
        path="/reset-password"
        element={!user ? <ResetPasswordPage /> : <Navigate to="/" replace />}
      />
      <Route
        path="/force-password-change"
        element={
          user && user.must_change_password ? (
            <ForcePasswordChangePage user={user} onChanged={reload} onLoggedOut={handleLoggedOut} />
          ) : (
            <Navigate to={user ? "/" : "/login"} replace />
          )
        }
      />

      {/* ── Attendance (Group 3) ── */}
      <Route
        path="/attendance"
        element={
          <Guard user={user} reload={reload} condition={user?.role !== "STUDENT"} fallback="/">
            <AttendanceSetupPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />
      <Route
        path="/attendance/sessions/:sessionId"
        element={
          <Guard user={user} reload={reload} condition={user?.role !== "STUDENT"} fallback="/">
            <AttendanceRegisterPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Students (Group 4) ── */}
      <Route
        path="/students"
        element={
          <Guard user={user} reload={reload} condition={user?.role !== "STUDENT"} fallback="/me/profile">
            <StudentsListPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />
      <Route
        path="/students/new"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/students">
            <StudentFormPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />
      <Route
        path="/students/:studentId/edit"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/students">
            <StudentFormPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />
      <Route
        path="/students/:studentId"
        element={
          <Guard user={user} reload={reload} condition={user?.role !== "STUDENT"} fallback="/">
            <StudentViewPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Faculty (Group 5, HOD/Admin) ── */}
      <Route
        path="/faculty"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/">
            <FacultyPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Subjects (Group 5, HOD/Admin) ── */}
      <Route
        path="/subjects"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/">
            <SubjectsPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Academic Calendar (Group 5, all roles) ── */}
      <Route
        path="/academic-calendar"
        element={
          <Guard user={user} reload={reload}>
            <AcademicCalendarPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Audit Log (HOD/Admin) ── */}
      <Route
        path="/audit-log"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/">
            <AuditLogPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── SMS Log (HOD/Admin) ── */}
      <Route
        path="/sms-log"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/">
            <SmsLogPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      <Route
        path="/problem-reports"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/">
            <ProblemReportsPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── My Account (HOD/FACULTY/ADMIN, Group 6) ── */}
      <Route
        path="/me/account"
        element={
          <Guard user={user} reload={reload} condition={user?.role !== "STUDENT"} fallback="/me/profile">
            <AccountPage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── My Profile (STUDENT, Group 6) ── */}
      <Route
        path="/me/profile"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "STUDENT"} fallback="/me/account">
            <ProfilePage user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Dashboards ── */}
      <Route
        path="/hod-dashboard"
        element={
          <Guard user={user} reload={reload} condition={user?.role === "HOD" || user?.role === "ADMIN"} fallback="/attendance">
            <HodDashboard user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />
      <Route
        path="/student-dashboard"
        element={
          <Guard user={user} reload={reload}>
            <StudentDashboard user={user!} onLoggedOut={handleLoggedOut} />
          </Guard>
        }
      />

      {/* ── Default / Dashboard (catch-all) ── */}
      <Route
        path="/*"
        element={
          !user ? (
            <Navigate to="/login" replace />
          ) : user.must_change_password ? (
            <Navigate to="/force-password-change" replace />
          ) : (
            <DashboardPage user={user} onLoggedOut={handleLoggedOut} />
          )
        }
      />
    </Routes>
    </>
  );
}
