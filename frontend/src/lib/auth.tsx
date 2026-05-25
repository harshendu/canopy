import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, getToken, login as apiLogin, setToken } from "../api/client";
import type { Token } from "../api/types";

interface AuthState {
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Admin-only: act as another user (their id), or pass your own id to step back to yourself. */
  impersonate: (userId: number) => Promise<void>;
  /** Drop impersonation and return to the acting admin's own account. */
  stopImpersonating: () => Promise<void>;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getToken());
  const qc = useQueryClient();

  const value = useMemo<AuthState>(() => {
    // Identity changed — wipe every cached query so all data refetches as the new principal.
    const applyToken = (newToken: string | null) => {
      setToken(newToken);
      setTokenState(newToken);
      qc.clear();
    };
    return {
      token,
      isAuthenticated: Boolean(token),
      login: async (email, password) => {
        applyToken(await apiLogin(email, password));
      },
      logout: () => applyToken(null),
      impersonate: async (userId) => {
        const { access_token } = await api.post<Token>(`/auth/impersonate/${userId}`);
        applyToken(access_token);
      },
      stopImpersonating: async () => {
        const { access_token } = await api.post<Token>("/auth/impersonate/stop");
        applyToken(access_token);
      },
    };
  }, [token, qc]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
