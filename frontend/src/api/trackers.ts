/**
 * Tracker links and the tracker catalog — the tracker-neutral successors of the Jira links
 * (`/jira-links`). Typed calls only for now; the UI moves over in a later change.
 */
import { api } from "./client";
import type {
  TrackerCatalog,
  TrackerLink,
  TrackerLinkCreate,
  TrackerLinkSyncResult,
} from "./types";

/** The trackers this deployment knows, what each can do, and the default tracking mode. */
export function getTrackers(): Promise<TrackerCatalog> {
  return api.get<TrackerCatalog>("/meta/trackers");
}

/** Tracker links, optionally only those of one target (e.g. a project or initiative). */
export function listTrackerLinks(target?: {
  target_type: string;
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
