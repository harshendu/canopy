/**
 * Work trackers (USER_FLOWS §J0/§J9/§C12): the tracker catalog, tracker links, a project's
 * tracking (native or mirrored, its binding, switching) and finalising a draft plan — all
 * tracker-neutral, so nothing here assumes Jira.
 */
import { api } from "./client";
import type {
  DraftFinalizeResult,
  ProjectTracking,
  ProjectTrackingUpdate,
  TrackerCatalog,
  TrackerLink,
  TrackerLinkCreate,
  TrackerLinkSyncResult,
  TrackerLinkTarget,
  TrackingPublishResult,
  TrackingSwitchRequest,
  TrackingSwitchResult,
  TrackingSyncResult,
} from "./types";

/** The tracker catalog's cache key (shared by every surface that labels a provider). */
export const TRACKERS_KEY = ["trackers"] as const;

/** A project's tracking cache key. */
export function trackingKey(projectId: number): readonly ["tracking", number] {
  return ["tracking", projectId];
}

/** The trackers this deployment knows, what each can do, and the default tracking mode. */
export function getTrackers(): Promise<TrackerCatalog> {
  return api.get<TrackerCatalog>("/meta/trackers");
}

/** Tracker links, optionally only those of one target (e.g. a project or initiative). */
export function listTrackerLinks(target?: {
  target_type: TrackerLinkTarget;
  target_id: number;
}): Promise<TrackerLink[]> {
  const query = target
    ? `?target_type=${encodeURIComponent(target.target_type)}&target_id=${target.target_id}`
    : "";
  return api.get<TrackerLink[]>(`/tracker-links${query}`);
}

/** Link a tracker item (e.g. an epic) to a canopy target and sync it in. */
export function createTrackerLink(body: TrackerLinkCreate): Promise<TrackerLinkSyncResult> {
  return api.post<TrackerLinkSyncResult>("/tracker-links", body);
}

export function resyncTrackerLink(id: number): Promise<TrackerLinkSyncResult> {
  return api.post<TrackerLinkSyncResult>(`/tracker-links/${id}/resync`);
}

export function deleteTrackerLink(id: number): Promise<void> {
  return api.del(`/tracker-links/${id}`);
}

/** How a project is tracked: mode, binding, past trackers, capabilities, status ownership. */
export function getProjectTracking(projectId: number): Promise<ProjectTracking> {
  return api.get<ProjectTracking>(`/projects/${projectId}/tracking`);
}

/** Adjust the active binding in place (scope, mapping, sprint mirroring). */
export function updateProjectTracking(
  projectId: number,
  body: ProjectTrackingUpdate,
): Promise<ProjectTracking> {
  return api.put<ProjectTracking>(`/projects/${projectId}/tracking`, body);
}

/** Pull the project's binding now — incremental, or `full` (re-reads everything and refreshes
 *  the tracker's statuses). */
export function syncProjectTracking(projectId: number, full = false): Promise<TrackingSyncResult> {
  return api.post<TrackingSyncResult>(`/projects/${projectId}/tracking/sync?full=${full}`);
}

/** Preview (`dry_run`) or apply a switch between native and mirrored tracking. */
export function switchProjectTracking(
  projectId: number,
  body: TrackingSwitchRequest,
): Promise<TrackingSwitchResult> {
  return api.post<TrackingSwitchResult>(`/projects/${projectId}/tracking/switch`, body);
}

/** Create a mirrored project's open canopy-owned tasks as items in its tracker. */
export function publishProjectTracking(projectId: number): Promise<TrackingPublishResult> {
  return api.post<TrackingPublishResult>(`/projects/${projectId}/tracking/publish`);
}

/** Turn a reviewed draft plan into real work: canopy tasks in a native project, the bound
 *  tracker's items in a mirrored one (or the given tracker connection). */
export function finalizeDraftPlan(
  planId: number,
  connectionId: number | null = null,
): Promise<DraftFinalizeResult> {
  return api.post<DraftFinalizeResult>(`/draft-plans/${planId}/finalize`, {
    connection_id: connectionId,
  });
}
