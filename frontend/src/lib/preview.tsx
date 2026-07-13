import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { PreviewTarget } from "./previewTarget";

interface PreviewContextValue {
  target: PreviewTarget | null;
  openPreview: (target: PreviewTarget) => void;
  closePreview: () => void;
}

const PreviewContext = createContext<PreviewContextValue | null>(null);

/**
 * Holds the entity currently shown in the right-side preview drawer. Mounted once, high in
 * the authenticated tree, so any list/card can open a peek (via `PreviewLink`) without
 * navigating away — the "preview before you commit" pattern the whole app shares.
 */
export function PreviewProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<PreviewTarget | null>(null);
  const openPreview = useCallback((t: PreviewTarget) => setTarget(t), []);
  const closePreview = useCallback(() => setTarget(null), []);
  const value = useMemo<PreviewContextValue>(
    () => ({ target, openPreview, closePreview }),
    [target, openPreview, closePreview],
  );
  return <PreviewContext.Provider value={value}>{children}</PreviewContext.Provider>;
}

export function usePreview(): PreviewContextValue {
  const ctx = useContext(PreviewContext);
  if (!ctx) throw new Error("usePreview must be used within a PreviewProvider");
  return ctx;
}
