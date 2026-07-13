import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon } from "./icons";

/** One node in a breadcrumb trail. The last (current) crumb omits `to`. */
export interface Crumb {
  label: string;
  to?: string;
}

/** The last crumb that still has a link target — the logical parent, used for the back arrow. */
function parentCrumb(items: Crumb[]): Crumb | undefined {
  for (let i = items.length - 2; i >= 0; i--) {
    if (items[i].to) return items[i];
  }
  return undefined;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-xs text-slate-400">
      {items.map((c, i) => {
        const last = i === items.length - 1;
        return (
          <span key={`${c.label}-${i}`} className="flex min-w-0 items-center gap-1">
            {i > 0 && <Icon name="chevron-right" size={12} className="shrink-0 text-slate-300" />}
            {c.to && !last ? (
              <Link
                to={c.to}
                className="max-w-[16rem] truncate rounded hover:text-slate-700 hover:underline"
              >
                {c.label}
              </Link>
            ) : (
              <span
                className={`max-w-[20rem] truncate ${last ? "font-medium text-slate-500" : ""}`}
                aria-current={last ? "page" : undefined}
              >
                {c.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

/** A compact back affordance — an arrow to a parent route. */
export function BackButton({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      aria-label={`Back to ${label}`}
      title={`Back to ${label}`}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 hover:text-slate-800"
    >
      <Icon name="arrow-left" size={16} />
    </Link>
  );
}

/**
 * The standard page header used across every screen: an optional breadcrumb row with a
 * quick back arrow to the parent, then the title (with adornments/badges) and right-aligned
 * actions. Keeping the layout in one place is what makes wayfinding consistent app-wide.
 */
export function PageHeader({
  title,
  subtitle,
  breadcrumbs,
  back,
  actions,
  titleAdornment,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  breadcrumbs?: Crumb[];
  /** Overrides the back target derived from breadcrumbs. Pass `null` to suppress the arrow. */
  back?: { to: string; label: string } | null;
  actions?: ReactNode;
  titleAdornment?: ReactNode;
}) {
  const derivedParent = breadcrumbs ? parentCrumb(breadcrumbs) : undefined;
  const backTarget =
    back === null
      ? undefined
      : back ?? (derivedParent?.to ? { to: derivedParent.to, label: derivedParent.label } : undefined);

  return (
    <div className="mb-6 space-y-2">
      {(backTarget || (breadcrumbs && breadcrumbs.length > 1)) && (
        <div className="flex items-center gap-2">
          {backTarget && <BackButton to={backTarget.to} label={backTarget.label} />}
          {breadcrumbs && breadcrumbs.length > 1 && <Breadcrumbs items={breadcrumbs} />}
        </div>
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {typeof title === "string" ? <h1 className="text-2xl font-bold">{title}</h1> : title}
            {titleAdornment}
          </div>
          {subtitle && <div className="mt-1 text-sm text-slate-500">{subtitle}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
