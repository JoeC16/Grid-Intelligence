// Score colour: one hue, light -> dark (sequential). Steps 250-700 of the
// blue ramp so the faintest dots still clear 2:1 against the light basemap.
export const SCORE_STOPS: [number, string][] = [
  [0, "#86b6ef"],
  [25, "#5598e7"],
  [50, "#2a78d6"],
  [75, "#1c5cab"],
  [100, "#0d366b"],
];
export const UNSCORED = "#a8a7a2";
export const INK = "#1a1a19";

export function scoreColor(score: number | null): string {
  if (score == null) return UNSCORED;
  for (let i = 1; i < SCORE_STOPS.length; i++) {
    const [s1, c1] = SCORE_STOPS[i - 1];
    const [s2, c2] = SCORE_STOPS[i];
    if (score <= s2) {
      const t = (score - s1) / (s2 - s1);
      return mix(c1, c2, t);
    }
  }
  return SCORE_STOPS[SCORE_STOPS.length - 1][1];
}

function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

export const scoreGradientCss = `linear-gradient(to right, ${SCORE_STOPS.map(([s, c]) => `${c} ${s}%`).join(", ")})`;
