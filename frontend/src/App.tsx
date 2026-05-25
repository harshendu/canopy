import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./lib/auth";
import { useCurrentUser } from "./lib/useCurrentUser";
import { personaHome } from "./lib/persona";
import { useEventStream } from "./lib/useEventStream";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import ProjectView from "./pages/ProjectView";
import Initiatives from "./pages/Initiatives";
import InitiativeView from "./pages/InitiativeView";
import ScenarioList from "./pages/ScenarioList";
import ScenarioWorkspace from "./pages/ScenarioWorkspace";
import Connectors from "./pages/Connectors";
import Decisions from "./pages/Decisions";
import MyWorkspace from "./pages/MyWorkspace";
import MyToday from "./pages/MyToday";
import AdminUsers from "./pages/AdminUsers";
import AdminIntegrations from "./pages/AdminIntegrations";
import Team from "./pages/Team";

const Portfolio = lazy(() => import("./pages/Portfolio")); // Recharts — load on demand

function Loading() {
  return <div className="p-6 text-sm text-slate-400">Loading…</div>;
}

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { isAuthenticated, logout } = useAuth();
  const location = useLocation();
  useEventStream(isAuthenticated); // live-refresh caches on backend change events
  const { data: me } = useCurrentUser(isAuthenticated);
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
          <NavLink to="/me" className={navClass}>
            My work
          </NavLink>
          <NavLink to="/portfolio" className={navClass}>
            Portfolio
          </NavLink>
          <NavLink to="/initiatives" className={navClass}>
            Initiatives
          </NavLink>
          <NavLink to="/projects" className={navClass}>
            Projects
          </NavLink>
          <NavLink to="/decisions" className={navClass}>
            Decisions
          </NavLink>
          <NavLink to="/team" className={navClass}>
            Team
          </NavLink>
          <NavLink to="/connectors" className={navClass}>
            Connectors
          </NavLink>
          {me?.role === "admin" && (
            <NavLink to="/admin/users" className={navClass}>
              Users
            </NavLink>
          )}
          {me?.role === "admin" && (
            <NavLink to="/admin/integrations" className={navClass}>
              Integrations
            </NavLink>
          )}
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

/** Land each persona on their default surface (a lens, not a wall — see lib/persona). */
function PersonaHome() {
  const { data: me, isLoading } = useCurrentUser();
  if (isLoading) return <Loading />;
  return <Navigate to={personaHome(me?.function)} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedLayout>
            <PersonaHome />
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
        path="/initiatives"
        element={
          <ProtectedLayout>
            <Initiatives />
          </ProtectedLayout>
        }
      />
      <Route
        path="/initiatives/:initiativeId"
        element={
          <ProtectedLayout>
            <InitiativeView />
          </ProtectedLayout>
        }
      />
      <Route
        path="/initiatives/:initiativeId/scenarios"
        element={
          <ProtectedLayout>
            <ScenarioList />
          </ProtectedLayout>
        }
      />
      <Route
        path="/initiatives/:initiativeId/scenarios/:scenarioId"
        element={
          <ProtectedLayout>
            <ScenarioWorkspace />
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
        path="/me"
        element={
          <ProtectedLayout>
            <MyWorkspace />
          </ProtectedLayout>
        }
      />
      <Route
        path="/me/today"
        element={
          <ProtectedLayout>
            <MyToday />
          </ProtectedLayout>
        }
      />
      <Route
        path="/decisions"
        element={
          <ProtectedLayout>
            <Decisions />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/users"
        element={
          <ProtectedLayout>
            <AdminUsers />
          </ProtectedLayout>
        }
      />
      <Route
        path="/admin/integrations"
        element={
          <ProtectedLayout>
            <AdminIntegrations />
          </ProtectedLayout>
        }
      />
      <Route
        path="/team"
        element={
          <ProtectedLayout>
            <Team />
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
