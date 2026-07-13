import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "./api/client";
import type { Proposal } from "./api/types";
import { useAuth } from "./lib/auth";
import { useCurrentUser } from "./lib/useCurrentUser";
import { canContribute } from "./lib/permissions";
import { personaHome } from "./lib/persona";
import { useEventStream } from "./lib/useEventStream";
import { featureOn, useFeatures } from "./lib/useFeatures";
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
import Reviews from "./pages/Reviews";
import AdminUsers from "./pages/AdminUsers";
import AdminIntegrations from "./pages/AdminIntegrations";
import AdminFeatures from "./pages/AdminFeatures";
import DemoData from "./pages/DemoData";
import Team from "./pages/Team";
import AgentSetup from "./pages/AgentSetup";
import ChangePassword from "./components/ChangePassword";
import ImpersonationBanner from "./components/ImpersonationBanner";
import UserSwitcher from "./components/UserSwitcher";

const Portfolio = lazy(() => import("./pages/Portfolio")); // Recharts — load on demand

function Loading() {
  return <div className="p-6 text-sm text-slate-400">Loading…</div>;
}

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { isAuthenticated, logout } = useAuth();
  const location = useLocation();
  useEventStream(isAuthenticated); // live-refresh caches on backend change events
  const { data: me } = useCurrentUser(isAuthenticated);
  const features = useFeatures(isAuthenticated);
  // The review-queue badge: staged changes awaiting a human. SSE keeps it live.
  const openProposals = useQuery({
    queryKey: ["proposals", "open"],
    queryFn: () => api.get<Proposal[]>("/proposals?status=open"),
    enabled: isAuthenticated && featureOn(features, "ai.proposals"),
    staleTime: 30 * 1000,
  });
  const reviewCount = openProposals.data?.length ?? 0;
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  const navClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded px-3 py-2 text-sm font-medium ${
      isActive ? "bg-canopy-500 text-white" : "text-slate-600 hover:bg-slate-200"
    }`;
  return (
    <div className="flex min-h-screen flex-col">
      <ImpersonationBanner />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white p-4">
          <div className="mb-6 text-lg font-bold text-canopy-700">canopy</div>
          <nav className="space-y-1">
            <NavLink to="/me" className={navClass}>
              My work
            </NavLink>
            {featureOn(features, "ai.proposals") && (
              <NavLink to="/reviews" className={navClass}>
                <span className="flex items-center justify-between">
                  Reviews
                  {reviewCount > 0 && (
                    <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
                      {reviewCount}
                    </span>
                  )}
                </span>
              </NavLink>
            )}
            <NavLink to="/portfolio" className={navClass}>
              Portfolio
            </NavLink>
            {featureOn(features, "portfolio.initiatives") && (
              <NavLink to="/initiatives" className={navClass}>
                Initiatives
              </NavLink>
            )}
            <NavLink to="/projects" className={navClass}>
              Projects
            </NavLink>
            {featureOn(features, "architecture") && (
              <NavLink to="/decisions" className={navClass}>
                Decisions
              </NavLink>
            )}
            <NavLink to="/team" className={navClass}>
              Team
            </NavLink>
            <NavLink to="/agent-setup" className={navClass}>
              Agent Setup
            </NavLink>
            {canContribute(me?.role) && featureOn(features, "integrations") && (
              <NavLink to="/connectors" className={navClass}>
                Connectors
              </NavLink>
            )}
            {me?.role === "admin" && (
              <NavLink to="/admin/users" className={navClass}>
                Users
              </NavLink>
            )}
            {me?.role === "admin" && (
              <NavLink to="/admin/features" className={navClass}>
                Features
              </NavLink>
            )}
            {me?.role === "admin" && (
              <NavLink to="/admin/integrations" className={navClass}>
                Integrations
              </NavLink>
            )}
            {me?.role === "admin" && (
              <NavLink to="/admin/demo" className={navClass}>
                Demo data
              </NavLink>
            )}
          </nav>
          <div className="mt-8 flex flex-col items-start gap-1.5">
            <ChangePassword />
            <button
              onClick={logout}
              className="text-xs text-slate-400 hover:text-slate-600"
            >
              Sign out
            </button>
          </div>
          <div className="mt-auto">
            <UserSwitcher />
          </div>
        </aside>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}

/** Land each persona on their default surface (a lens, not a wall — see lib/persona). */
function PersonaHome() {
  const { data: me, isLoading } = useCurrentUser();
  const features = useFeatures();
  if (isLoading) return <Loading />;
  return <Navigate to={personaHome(me?.function, features)} replace />;
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
        path="/reviews"
        element={
          <ProtectedLayout>
            <Reviews />
          </ProtectedLayout>
        }
      />
      <Route
        path="/reviews/:proposalId"
        element={
          <ProtectedLayout>
            <Reviews />
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
        path="/admin/features"
        element={
          <ProtectedLayout>
            <AdminFeatures />
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
        path="/admin/demo"
        element={
          <ProtectedLayout>
            <DemoData />
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
      <Route
        path="/agent-setup"
        element={
          <ProtectedLayout>
            <AgentSetup />
          </ProtectedLayout>
        }
      />
    </Routes>
  );
}
