import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { getToken } from "../api/client";

/**
 * Subscribe to backend SSE and invalidate caches on change events so the UI
 * refreshes live. EventSource can't set headers, so the token rides in the URL.
 */
export function useEventStream(enabled: boolean): void {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    if (!token) return;
    const source = new EventSource(`/api/v1/events/stream?token=${encodeURIComponent(token)}`);
    source.onmessage = () => {
      void qc.invalidateQueries();
    };
    // Do NOT close on error: EventSource auto-reconnects after a transient drop (network blip,
    // proxy idle-timeout, backend redeploy). Calling close() here would set state to CLOSED and
    // permanently kill live-refresh for the rest of the session. The unmount cleanup closes it.
    return () => source.close();
  }, [enabled, qc]);
}
