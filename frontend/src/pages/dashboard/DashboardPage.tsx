// Role-aware dashboard router.
// Navigates users to their Profile / Account page upon login.
import { Navigate } from "react-router-dom";
import { type CurrentUser } from "../../api/auth";

interface DashboardPageProps {
  user: CurrentUser;
  onLoggedOut: () => void;
}

export function DashboardPage({ user }: DashboardPageProps) {
  if (user.role === "STUDENT") {
    return <Navigate to="/me/profile" replace />;
  }

  // HOD, FACULTY, ADMIN
  return <Navigate to="/me/account" replace />;
}
