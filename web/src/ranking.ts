// The three rankings the UI can show. Each mirrors pipeline/score.py:
//   score    -> investor weighted score (rescore() in scoring.ts)
//   stuck    -> stuck_rank(): sites with stuck_mw > 0, by stuck_mw, highest first
//   developer-> filter_rank(): sites with published headroom >= load, by
//               headroom_after_queue_mw, highest first
// Ties share the best rank. Values are compared at 3 dp, as the pipeline does.
import type { SiteProps } from "./api";
import { rescore, type Weights } from "./scoring";

export type Mode = "score" | "stuck" | "developer";

export interface Ranked {
  value: number; // the metric ranked on
  rank: number;
}

export interface Ranking {
  mode: Mode;
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

export function rankForLoad(sites: SiteProps[], loadMw: number): Ranking {
  const items: [string, number][] = sites
    .filter((s) => scorable(s) && s.demand_headroom_mw != null && s.demand_headroom_mw >= loadMw && s.headroom_after_queue_mw != null)
    .map((s) => [s.site_id, s.headroom_after_queue_mw!]);
  const entries = rankDesc(items);
  return { mode: "developer", entries, n: entries.size };
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
    if (r.mode === "developer") return "not enough published headroom";
    return "not scored";
  }
  if (r.mode === "score") return `score ${e.value.toFixed(1)} · rank ${e.rank}`;
  if (r.mode === "stuck") return `${mw(e.value)} stuck · rank ${e.rank}`;
  return `${mw(e.value)} left after queue · rank ${e.rank}`;
}
