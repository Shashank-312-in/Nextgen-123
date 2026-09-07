// Plan §4.2 hooks/ dir, handoff item 6. Loads the current user on app
// mount and exposes it to route guards. Because the access token lives
// only in memory (client.ts), a hard page refresh always starts with no
// token — this hook's first job is a silent POST /api/auth/refresh (the
// httpOnly refresh cookie survives a refresh) before it even tries
// GET /api/auth/me, otherwise every page reload would bounce a logged-in
// user to /login.
import { useEffect, useState } from "react";
import { me, refresh, type CurrentUser } from "../api/auth";
import { ApiClientError } from "../api/client";

interface UseCurrentUserResult {
  user: CurrentUser | null;
  loading: boolean;
  /** Re-run after a successful login/change-password so guards see fresh state without a full reload. */
  reload: () => Promise<void>;
  /** Immediately clear current user in state without triggering silent refresh. */
  clearUser: () => void;
}

export function useCurrentUser(): UseCurrentUserResult {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      // Try silent refresh first — a fresh page load has no in-memory
      // access token yet, only whatever refresh cookie the browser held
      // onto. If there's no valid cookie either, this just fails and we
      // fall through to /me failing too, which is the correct "not logged
      // in" outcome.
      await refresh();
    } catch {
      // No valid refresh cookie — fine, /me below will 401 and user stays null.
    }

    try {
      const u = await me();
      setUser(u);
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "MUST_CHANGE_PASSWORD") {
        // — shouldn't happen: /api/auth/me uses get_current_user_allow_pending,
        // which never raises this code. Kept as a defensive branch only.
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const clearUser = () => {
    setUser(null);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { user, loading, reload: load, clearUser };
}

