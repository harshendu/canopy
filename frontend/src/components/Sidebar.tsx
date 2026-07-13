import { useState } from "react";
import { NavLink } from "react-router-dom";

import type { NavItem } from "../lib/nav";
import ChangePassword from "./ChangePassword";
import UserSwitcher from "./UserSwitcher";
import { Icon } from "./icons";

const COLLAPSE_KEY = "canopy_sidebar_collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * The left navigation rail. Collapses to an icon-only rail (persisted in localStorage) so the
 * architect can reclaim horizontal space for the Gantt / graphs; every link carries an SVG
 * glyph so it stays legible collapsed, with the label as a native tooltip.
 */
export default function Sidebar({
  items,
  reviewCount,
  onSignOut,
}: {
  items: NavItem[];
  reviewCount: number;
  onSignOut: () => void;
}) {
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);

  const toggle = () => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* ignore private-mode storage failures */
      }
      return next;
    });
  };

  const primary = items.filter((i) => i.group === "primary");
  const admin = items.filter((i) => i.group === "admin");

  const renderItem = (item: NavItem) => {
    const showBadge = item.badge === "reviews" && reviewCount > 0;
    return (
      <NavLink
        key={item.to}
        to={item.to}
        title={collapsed ? item.label : undefined}
        className={({ isActive }) =>
          `group relative flex items-center rounded px-3 py-2 text-sm font-medium ${
            collapsed ? "justify-center" : "gap-3"
          } ${
            isActive
              ? "bg-canopy-500 text-white"
              : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
          }`
        }
      >
        <span className="relative flex shrink-0 items-center justify-center">
          <Icon name={item.icon} size={18} />
          {collapsed && showBadge && (
            <span className="absolute -right-1.5 -top-1.5 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white" />
          )}
        </span>
        {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
        {!collapsed && showBadge && (
          <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
            {reviewCount}
          </span>
        )}
      </NavLink>
    );
  };

  return (
    <aside
      className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 ${
        collapsed ? "w-16" : "w-56"
      }`}
    >
      <div
        className={`flex items-center px-3 py-4 ${collapsed ? "justify-center" : "justify-between"}`}
      >
        {!collapsed && <span className="text-lg font-bold text-canopy-700">canopy</span>}
        <button
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-8 w-8 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <Icon name={collapsed ? "chevron-right" : "chevron-left"} size={18} />
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-2">
        {primary.map(renderItem)}
        {admin.length > 0 && (
          <div className="pt-3">
            {collapsed ? (
              <div className="mx-2 border-t border-slate-100" />
            ) : (
              <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Admin
              </div>
            )}
            <div className="space-y-1 pt-1">{admin.map(renderItem)}</div>
          </div>
        )}
      </nav>

      <div className="mt-2 border-t border-slate-100 px-2 py-3">
        {collapsed ? (
          <button
            onClick={onSignOut}
            aria-label="Sign out"
            title="Sign out"
            className="flex h-9 w-full items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <Icon name="sign-out" size={18} />
          </button>
        ) : (
          <div className="flex flex-col items-start gap-1.5 px-1">
            <ChangePassword />
            <button onClick={onSignOut} className="text-xs text-slate-400 hover:text-slate-600">
              Sign out
            </button>
          </div>
        )}
        <div className="mt-2">
          <UserSwitcher collapsed={collapsed} />
        </div>
      </div>
    </aside>
  );
}
