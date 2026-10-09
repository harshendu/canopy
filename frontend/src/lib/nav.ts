import type { IconName } from "../components/icons";

/**
 * Declarative sidebar navigation catalog. Kept pure (no React) so the
 * role/feature-gating that decides which links show is unit-testable — the
 * `Sidebar` component just renders whatever `visibleNavItems` returns.
 */
export type NavGroup = "primary" | "admin";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  group: NavGroup;
  /** Which live badge (if any) to render next to the label. */
  badge?: "reviews";
}

export interface NavContext {
  role: string | undefined;
  isAdmin: boolean;
  canContribute: boolean;
  isFeatureOn: (feature: string) => boolean;
}

interface NavDef extends NavItem {
  visible: (ctx: NavContext) => boolean;
}

const ALWAYS = (): boolean => true;

const NAV: NavDef[] = [
  { to: "/me", label: "My work", icon: "my-work", group: "primary", visible: ALWAYS },
  {
    to: "/reviews",
    label: "Reviews",
    icon: "reviews",
    group: "primary",
    badge: "reviews",
    visible: (c) => c.isFeatureOn("ai.proposals"),
  },
  {
    to: "/review",
    label: "Business review",
    icon: "business-review",
    group: "primary",
    visible: (c) => c.isFeatureOn("portfolio.leadership"),
  },
  { to: "/portfolio", label: "Portfolio", icon: "portfolio", group: "primary", visible: ALWAYS },
  {
    to: "/initiatives",
    label: "Initiatives",
    icon: "initiatives",
    group: "primary",
    visible: (c) => c.isFeatureOn("portfolio.initiatives"),
  },
  { to: "/projects", label: "Projects", icon: "projects", group: "primary", visible: ALWAYS },
  {
    to: "/decisions",
    label: "Decisions",
    icon: "decisions",
    group: "primary",
    visible: (c) => c.isFeatureOn("architecture"),
  },
  { to: "/team", label: "Team", icon: "team", group: "primary", visible: ALWAYS },
  {
    to: "/agent-setup",
    label: "Agent Setup",
    icon: "agent-setup",
    group: "primary",
    visible: ALWAYS,
  },
  {
    to: "/connectors",
    label: "Connectors",
    icon: "connectors",
    group: "primary",
    visible: (c) => c.canContribute && c.isFeatureOn("integrations"),
  },
  {
    to: "/admin/users",
    label: "Users",
    icon: "admin-users",
    group: "admin",
    visible: (c) => c.isAdmin,
  },
  {
    to: "/admin/features",
    label: "Features",
    icon: "admin-features",
    group: "admin",
    visible: (c) => c.isAdmin,
  },
  {
    to: "/admin/integrations",
    label: "Integrations",
    icon: "admin-integrations",
    group: "admin",
    visible: (c) => c.isAdmin,
  },
  {
    to: "/admin/demo",
    label: "Demo data",
    icon: "admin-demo",
    group: "admin",
    visible: (c) => c.isAdmin,
  },
];

/** The nav items visible to the given user/feature context, in display order. */
export function visibleNavItems(ctx: NavContext): NavItem[] {
  return NAV.filter((n) => n.visible(ctx)).map((n) => ({
    to: n.to,
    label: n.label,
    icon: n.icon,
    group: n.group,
    ...(n.badge ? { badge: n.badge } : {}),
  }));
}
