import { lazy, Suspense } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api } from "./api/client";
import type { Proposal } from "./api/types";
import { useAuth } from "./lib/auth";
import { useCurrentUser } from "./lib/useCurrentUser";
import { canContribute } from "./lib/permissions";
import { personaHome } from "./lib/persona";
import { useEventStream } from "./lib/useEventStream";
import { featureOn, useFeatures } from "./lib/useFeatures";
import { visibleNavItems } from "./lib/nav";
import { PreviewProvider } from "./lib/preview";
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
import Sidebar from "./components/Sidebar";
import PreviewPanel from "./components/PreviewPanel";
import ImpersonationBanner from "./components/ImpersonationBanner";

const Portfolio = lazy(() => import("./pages/Portfolio")); // Recharts — load on demand

function Loading() {
  return <div className="p-6 text-sm text-slate-400">Loading…</div>;
}

/**
 * The authenticated app shell: a persistent layout route (renders once, survives navigation via
 * <Outlet/>) hosting the collapsible sidebar, the routed page, and the shared right-side preview
 * drawer. Keeping it a single layout route means sidebar/collapse and preview state persist across
 * navigations instead of remounting per page.
 */
function ProtectedLayout() {
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
  const navItems = visibleNavItems({
    role: me?.role,
    isAdmin: me?.role === "admin",
    canContribute: canContribute(me?.role),
    isFeatureOn: (feature) => featureOn(features, feature),
  });
  return (
    <PreviewProvider>
      <div className="flex min-h-screen flex-col">
        <ImpersonationBanner />
        <div className="flex min-h-0 flex-1">
          <Sidebar items={navItems} reviewCount={reviewCount} onSignOut={logout} />
          <main className="flex-1 overflow-auto p-6">
            <Outlet />
          </main>
        </div>
      </div>
      <PreviewPanel />
    </PreviewProvider>
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
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<PersonaHome />} />
        <Route
          path="/portfolio"
          element={
            <Suspense fallback={<Loading />}>
              <Portfolio />
            </Suspense>
          }
        />
        <Route path="/initiatives" element={<Initiatives />} />
        <Route path="/initiatives/:initiativeId" element={<InitiativeView />} />
        <Route path="/initiatives/:initiativeId/scenarios" element={<ScenarioList />} />
        <Route
          path="/initiatives/:initiativeId/scenarios/:scenarioId"
          element={<ScenarioWorkspace />}
        />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:projectId" element={<ProjectView />} />
        <Route path="/reviews" element={<Reviews />} />
        <Route path="/reviews/:proposalId" element={<Reviews />} />
        <Route path="/me" element={<MyWorkspace />} />
        <Route path="/me/today" element={<MyToday />} />
        <Route path="/decisions" element={<Decisions />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/features" element={<AdminFeatures />} />
        <Route path="/admin/integrations" element={<AdminIntegrations />} />
        <Route path="/admin/demo" element={<DemoData />} />
        <Route path="/team" element={<Team />} />
        <Route path="/connectors" element={<Connectors />} />
        <Route path="/agent-setup" element={<AgentSetup />} />
      </Route>
    </Routes>
  );
}
