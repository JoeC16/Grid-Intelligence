// Live re-scoring in the browser. Mirrors combine() in pipeline/score.py:
// per view, use the stuck percentile p (or 1 - p if the view inverts), take
// the weighted sum over the signals a site has, divide by those weights, x100.
import type { SiteProps } from "./api";

export type Weights = Record<string, number>;

export function pctKey(signal: string): keyof SiteProps {
  return `pct_${signal}` as keyof SiteProps;
}

export function computeScore(site: SiteProps, weights: Weights, invert: boolean): number | null {
  let weighted = 0;
  let available = 0;
  for (const [key, w] of Object.entries(weights)) {
    const p = site[pctKey(key)] as number | null;
    if (p == null || w <= 0) continue;
    weighted += w * (invert ? 1 - p : p);
    available += w;
  }
  if (available === 0) return null;
  // Round half-up to 1 dp, in the same order as combine() in pipeline/score.py.
  return Math.floor(((100 * weighted) / available) * 10 + 0.5) / 10;
}

/** Score every site, then rank across all scored sites (ties share the best rank). */
export function rescore(sites: SiteProps[], weights: Weights, invert: boolean): Map<string, { score: number | null; rank: number | null }> {
  const scores = sites.map((s) => ({ id: s.site_id, score: s.score == null ? null : computeScore(s, weights, invert) }));
  const sorted = scores.map((s) => s.score).filter((v): v is number => v != null).sort((a, b) => b - a);
  const out = new Map<string, { score: number | null; rank: number | null }>();
  for (const { id, score } of scores) {
    // rank = 1 + number of sites with a strictly higher score
    let lo = 0, hi = sorted.length;
    while (score != null && lo < hi) {
      const mid = (lo + hi) >> 1;
      if (sorted[mid] > score) lo = mid + 1;
      else hi = mid;
    }
    out.set(id, { score, rank: score == null ? null : lo + 1 });
  }
  return out;
}
