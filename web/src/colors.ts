// One sequential ramp per view, single hue light -> dark. Both validated with
// the dataviz skill's ordinal checks against the basemap (#f2f2f0): monotone
// lightness, adjacent steps >= 0.06 apart, lightest step >= 2:1 contrast.
export type Ramp = [number, string][];

export const RAMPS: Record<string, Ramp> = {
  investor: [ // blue, steps 300-700
    [0, "#6da7ec"],
    [25, "#3987e5"],
    [50, "#256abf"],
    [75, "#184f95"],
    [100, "#0d366b"],
  ],
  developer: [ // orange
    [0, "#ea7c4a"],
    [25, "#d95926"],
    [50, "#b0461a"],
    [75, "#863313"],
    [100, "#5a2009"],
  ],
};
export const UNSCORED = "#a8a7a2";
export const INK = "#1a1a19";

export const rampFor = (view: string): Ramp => RAMPS[view] ?? RAMPS.investor;

export function scoreColor(score: number | null, ramp: Ramp): string {
  if (score == null) return UNSCORED;
  for (let i = 1; i < ramp.length; i++) {
    const [s1, c1] = ramp[i - 1];
    const [s2, c2] = ramp[i];
    if (score <= s2) return mix(c1, c2, (score - s1) / (s2 - s1));
  }
  return ramp[ramp.length - 1][1];
}

function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

export const gradientCss = (ramp: Ramp) =>
  `linear-gradient(to right, ${ramp.map(([s, c]) => `${c} ${s}%`).join(", ")})`;
