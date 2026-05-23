import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./lib/auth";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import ProjectView from "./pages/ProjectView";
import Connectors from "./pages/Connectors";

const Portfolio = lazy(() => import("./pages/Portfolio")); // Recharts — load on demand

function Loading() {
  return <div className="p-6 text-sm text-slate-400">Loading…</div>;
}

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { isAuthenticated, logout } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded px-3 py-2 text-sm font-medium ${
      isActive ? "bg-canopy-500 text-white" : "text-slate-600 hover:bg-slate-200"
    }`;
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-white p-4">
        <div className="mb-6 text-lg font-bold text-canopy-700">canopy</div>
        <nav className="space-y-1">
          <NavLink to="/portfolio" className={navClass}>
            Portfolio
          </NavLink>
          <NavLink to="/projects" className={navClass}>
            Projects
          </NavLink>
          <NavLink to="/connectors" className={navClass}>
            Connectors
          </NavLink>
        </nav>
        <button
          onClick={logout}
          className="mt-8 text-xs text-slate-400 hover:text-slate-600"
        >
          Sign out
        </button>
      </aside>
      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedLayout>
            <Navigate to="/projects" replace />
          </ProtectedLayout>
        }
      />
      <Route
        path="/portfolio"
        element={
          <ProtectedLayout>
            <Suspense fallback={<Loading />}>
              <Portfolio />
            </Suspense>
          </ProtectedLayout>
        }
      />
      <Route
        path="/projects"
        element={
          <ProtectedLayout>
            <Projects />
          </ProtectedLayout>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <ProtectedLayout>
            <ProjectView />
          </ProtectedLayout>
        }
      />
      <Route
        path="/connectors"
        element={
          <ProtectedLayout>
            <Connectors />
          </ProtectedLayout>
        }
      />
    </Routes>
  );
}
