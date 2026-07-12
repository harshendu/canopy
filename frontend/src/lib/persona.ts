import type { UserFunction } from "../api/types";
import { featureOn } from "./useFeatures";

/** The default landing surface for a user's cross-functional persona. Personas are a *lens, not
 *  a wall* — reads stay open everywhere; this only sets where you land. (AI_NATIVE_EXECUTION.md §5.)
 *  When the preferred surface is feature-gated off, fall back to /projects (always on). */
export function personaHome(
  fn: UserFunction | undefined,
  features: Record<string, boolean> = {},
): string {
  const preferred = (() => {
    switch (fn) {
      case "leadership": // executive — outcome + confidence at the portfolio altitude
      case "product": // PM — outcomes, roadmap, the program layer
        return "/initiatives";
      case "management": // EM / director — team flow + capacity
        return "/team";
      case "design": // UX — work via the initiative/project they support
        return "/initiatives";
      case "architecture": // staff / architect — decisions + coherence
        return "/decisions";
      case "engineering": // engineers land on their own work
        return "/me";
      default:
        return "/projects";
    }
  })();
  if (preferred === "/initiatives" && !featureOn(features, "portfolio.initiatives")) {
    return "/projects";
  }
  if (preferred === "/decisions" && !featureOn(features, "architecture")) {
    return "/projects";
  }
  return preferred;
}

const FUNCTION_LABEL: Record<UserFunction, string> = {
  engineering: "Engineering",
  product: "Product",
  design: "Design / UX",
  architecture: "Architecture",
  management: "Management",
  leadership: "Leadership",
};

export function functionLabel(fn: UserFunction | undefined): string {
  return fn ? FUNCTION_LABEL[fn] : "Engineering";
}
