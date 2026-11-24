// Unlock planner in the browser: mirrors curve() in pipeline/unlock.py so the
// what-if slider recomputes instantly. Keep the two in step.
//
// Adding A MW at a node with published headroom H and queue Q under it:
//   U = H + A − Q                         node headroom left after the queue
//   queue served (node alone) = min(A, max(Q − N − H, 0))   N = queue beyond sites' own headroom
//   queue served with local work = min(A, max(Q − H, 0))
//   new capacity = min(spare, max(U, 0))  spare = Σ max(site headroom − site queue, 0)
//   sites open = sites with min(site after its queue, U) ≥ load
import type { SiteProps } from "./api";

export interface UnlockResult {
  added: number;
  servedNodeOnly: number;
  servedWithLocal: number;
  newCapacity: number;
  sitesOpen: number;
  openIds: string[];
  nodeLeft: number; // U
}

export interface NodeInputs {
  headroom: number; // H
  queue: number; // Q
  spare: number;
  needsLocal: number; // N
  sites: { id: string; after: number }[];
}

export function nodeInputs(node: { headroom_mw: number | null; queue_mw: number }, sites: SiteProps[]): NodeInputs | null {
  if (node.headroom_mw == null) return null;
  const rows = sites
    .filter((s) => s.demand_headroom_mw != null && s.queue_mw != null)
    .map((s) => ({ id: s.site_id, h: s.demand_headroom_mw!, q: s.queue_mw! }));
  return {
    headroom: node.headroom_mw,
    queue: node.queue_mw,
    spare: rows.reduce((t, r) => t + Math.max(r.h - r.q, 0), 0),
    needsLocal: rows.reduce((t, r) => t + Math.max(r.q - Math.max(r.h, 0), 0), 0),
    sites: rows.map((r) => ({ id: r.id, after: r.h - r.q })),
  };
}

export function unlockAt(n: NodeInputs, added: number, loadMw: number): UnlockResult {
  const u = n.headroom + added - n.queue;
  const open = n.sites.filter((s) => Math.min(s.after, u) >= loadMw).map((s) => s.id);
  return {
    added,
    servedNodeOnly: Math.min(added, Math.max(n.queue - n.needsLocal - n.headroom, 0)),
    servedWithLocal: Math.min(added, Math.max(n.queue - n.headroom, 0)),
    newCapacity: Math.min(n.spare, Math.max(u, 0)),
    sitesOpen: open.length,
    openIds: open,
    nodeLeft: u,
  };
}

/** MW to add before any site can take loadMw; null = no site has the local headroom (needs local work too). */
export function mwToFirstOpen(n: NodeInputs, loadMw: number): number | null {
  if (!n.sites.some((s) => s.after >= loadMw)) return null;
  return Math.max(0, n.queue + loadMw - n.headroom);
}
