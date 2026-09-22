import { useCallback, useEffect, useRef, useState } from "react";
import { getPendingClassNotifications, type PendingClassNotification } from "../api/dashboard";
import { ToastPopup } from "./ToastPopup";

const POLL_MS = 30_000;

// scheduled_for is an app-local wall-clock string ("YYYY-MM-DD HH:MM:SS").
// Read the time part directly — new Date() would re-interpret it in the browser's zone.
function timeOf(s: string): string {
  const m = /(\d{2}):(\d{2})/.exec(s);
  return m ? `${m[1]}:${m[2]}` : "";
}

function describe(n: PendingClassNotification): string {
  const what = n.subject_name || n.custom_label || "Your class";
  const bits = [n.section_name ? `Section ${n.section_name}` : "", n.room ? `Room ${n.room}` : ""].filter(Boolean);
  const at = timeOf(n.scheduled_for);
  return `${what}${at ? ` at ${at}` : " is starting soon"}${bits.length ? ` · ${bits.join(" · ")}` : ""}`;
}

// Faculty-only. Polls for due class reminders every 30s and shows each once as a toast.
// Pauses while the tab is hidden and checks immediately when it becomes visible again.
export function ClassReminders() {
  const [queue, setQueue] = useState<string[]>([]);
  const inFlight = useRef(false);

  const poll = useCallback(async () => {
    if (inFlight.current || document.hidden) return;
    inFlight.current = true;
    try {
      const res = await getPendingClassNotifications();
      const msgs = (res.notifications ?? []).map(describe);
      if (msgs.length) setQueue(q => [...q, ...msgs]);
    } catch {
      // Best-effort: a failed poll must never interrupt the user. The next tick retries.
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void poll();
    const id = window.setInterval(() => void poll(), POLL_MS);
    const onVisible = () => { if (!document.hidden) void poll(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [poll]);

  return (
    <ToastPopup
      type="info"
      title="Class starting soon"
      message={queue[0] ?? null}
      onClose={() => setQueue(q => q.slice(1))}
      autoDismissMs={12000}
    />
  );
}
