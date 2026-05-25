import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { SessionInfo } from "../api/types";

/** The active session (GET /auth/session): the effective user + the admin behind it when
 *  impersonating. Backs the account switcher and the impersonation banner. */
export function useSession(enabled = true) {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => api.get<SessionInfo>("/auth/session"),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}
