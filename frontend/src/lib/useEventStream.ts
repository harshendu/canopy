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
    source.onerror = () => source.close();
    return () => source.close();
  }, [enabled, qc]);
}
