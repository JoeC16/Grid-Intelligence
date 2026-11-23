// The three rankings the UI can show. Each mirrors pipeline/score.py:
//   score    -> investor weighted score (rescore() in scoring.ts)
//   stuck    -> stuck_rank(): sites with stuck_mw > 0, by stuck_mw, highest first
//   bsp      -> sites coloured by their BSP's stuck MW rank (bsps.stuck_rank)
//   developer-> filter_rank(): sites with published headroom >= load, by
//               effective_headroom_mw (counts the BSP), or headroom_after_queue_mw
//               when upstream limits are ignored; highest first
// Ties share the best rank. Values are compared at 3 dp, as the pipeline does.
import type { SiteProps } from "./api";
import { rescore, type Weights } from "./scoring";

export type Mode = "score" | "stuck" | "bsp" | "developer";

export interface Ranked {
  value: number; // the metric ranked on
  rank: number;
}

export interface Ranking {
  mode: Mode;
  /** developer only: BSP limits counted */
  upstream?: boolean;
  /** Only sites that take part in this ranking. */
  entries: Map<string, Ranked>;
  /** How many sites are ranked. */
  n: number;
}

const r3 = (v: number) => Math.round(v * 1000) / 1000;

/** 1 = highest value; ties share the best rank. */
export function rankDesc(items: [string, number][]): Map<string, Ranked> {
  const sorted = items.map(([, v]) => r3(v)).sort((a, b) => b - a);
  const out = new Map<string, Ranked>();
  for (const [id, v] of items) {
    const key = r3(v);
    // rank = 1 + number of strictly higher values (binary search)
    let lo = 0, hi = sorted.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (sorted[mid] > key) lo = mid + 1;
      else hi = mid;
    }
    out.set(id, { value: v, rank: lo + 1 });
  }
  return out;
}

// A site is scorable if the pipeline scored it (excluded sites have no score).
const scorable = (s: SiteProps) => s.score != null;

export function rankByScore(sites: SiteProps[], weights: Weights): Ranking {
  const live = rescore(sites, weights);
  const entries = new Map<string, Ranked>();
  for (const [id, { score, rank }] of live) if (score != null && rank != null) entries.set(id, { value: score, rank });
  return { mode: "score", entries, n: entries.size };
}

export function rankByStuck(sites: SiteProps[]): Ranking {
  const items: [string, number][] = sites
    .filter((s) => scorable(s) && s.stuck_mw != null && s.stuck_mw > 0)
    .map((s) => [s.site_id, s.stuck_mw!]);
  const entries = rankDesc(items);
  return { mode: "stuck", entries, n: entries.size };
}

/**
 * Developer shortlist. upstream=true (the default view) ranks by effective
 * headroom, which counts the BSP above the site; false ignores upstream limits.
 * Mirrors filter_rank(local=...) in pipeline/score.py.
 */
export function rankForLoad(sites: SiteProps[], loadMw: number, upstream = true): Ranking {
  const value = (s: SiteProps) => (upstream ? s.effective_headroom_mw : s.headroom_after_queue_mw);
  const items: [string, number][] = sites
    .filter((s) => scorable(s) && s.demand_headroom_mw != null && s.demand_headroom_mw >= loadMw && value(s) != null)
    .map((s) => [s.site_id, value(s)!]);
  const entries = rankDesc(items);
  return { mode: "developer", entries, n: entries.size, upstream };
}

/**
 * Investor "BSPs by stuck MW": every site under a BSP with stuck demand takes
 * that BSP's stuck MW and rank, so the map colours whole branches.
 */
export function rankBySiteBsp(sites: SiteProps[], bsps: { bsp_id: string; stuck_mw: number | null; stuck_rank: number | null }[]): Ranking {
  const byBsp = new Map(bsps.filter((b) => b.stuck_rank != null).map((b) => [b.bsp_id, b]));
  const entries = new Map<string, Ranked>();
  for (const s of sites) {
    const b = s.bsp_id ? byBsp.get(s.bsp_id) : undefined;
    if (b && scorable(s)) entries.set(s.site_id, { value: b.stuck_mw!, rank: b.stuck_rank! });
  }
  return { mode: "bsp", entries, n: byBsp.size };
}

/** 0-100 for the colour ramp: the score itself, or rank-based (best = 100). */
export function colourPosition(r: Ranking, e: Ranked): number {
  if (r.mode === "score") return e.value;
  return r.n <= 1 ? 100 : 100 * (1 - (e.rank - 1) / (r.n - 1));
}

const mw = (v: number) => `${v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} MW`;

/** Short text for tooltips and the ranked list. */
export function describe(r: Ranking, e: Ranked | undefined): string {
  if (!e) {
    if (r.mode === "stuck") return "no stuck demand";
    if (r.mode === "bsp") return "BSP has no stuck demand";
    if (r.mode === "developer") return "not enough published headroom";
    return "not scored";
  }
  if (r.mode === "score") return `score ${e.value.toFixed(1)} · rank ${e.rank}`;
  if (r.mode === "stuck") return `${mw(e.value)} stuck · rank ${e.rank}`;
  if (r.mode === "bsp") return `BSP ${mw(e.value)} stuck · BSP rank ${e.rank}`;
  return `${mw(e.value)} left after queue${r.upstream ? " (BSP counted)" : ""} · rank ${e.rank}`;
}
