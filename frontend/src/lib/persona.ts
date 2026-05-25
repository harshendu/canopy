import type { UserFunction } from "../api/types";

/** The default landing surface for a user's cross-functional persona. Personas are a *lens, not
 *  a wall* — reads stay open everywhere; this only sets where you land. (AI_NATIVE_EXECUTION.md §5.) */
export function personaHome(fn: UserFunction | undefined): string {
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
