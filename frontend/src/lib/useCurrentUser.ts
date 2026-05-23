import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { User } from "../api/types";

/** The logged-in user (GET /auth/me), cached for role-gating and the /me workspace. */
export function useCurrentUser(enabled = true) {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/auth/me"),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}
