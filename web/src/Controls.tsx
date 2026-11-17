import type { SignalMeta, ViewMeta } from "./api";
import type { Weights } from "./scoring";

export function ViewToggle({ views, value, onChange }: { views: ViewMeta[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded-full border border-stone-300 bg-stone-100 p-0.5" role="radiogroup" aria-label="View">
      {views.map((v) => (
        <button
          key={v.key}
          type="button"
          role="radio"
          aria-checked={value === v.key}
          title={v.description}
          onClick={() => onChange(v.key)}
          className={`whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            value === v.key ? "bg-white text-stone-900 shadow-sm" : "text-stone-600 hover:text-stone-900"
          }`}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}

interface WeightsPanelProps {
  view: ViewMeta;
  signals: SignalMeta[];
  weights: Weights;
  onChange: (w: Weights) => void;
  onClose: () => void;
}

export function WeightsPanel({ view, signals, weights, onChange, onClose }: WeightsPanelProps) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const isDefault = signals.every((s) => (weights[s.key] ?? 0) === (view.weights[s.key] ?? 0));
  return (
    <div className="pointer-events-auto w-72 rounded-md bg-white p-4 shadow-lg">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-stone-900">{view.label} weights</p>
          <p className="mt-0.5 text-[11px] leading-snug text-stone-500">
            {view.invert
              ? "Each signal counts in reverse: more headroom, a shorter queue, etc. score higher."
              : "Higher weight = the signal counts for more in the score."}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close weights" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      <ul className="mt-3 space-y-3">
        {signals.map((s) => {
          const w = weights[s.key] ?? 0;
          const share = total > 0 ? Math.round((100 * w) / total) : 0;
          return (
            <li key={s.key}>
              <label className="block">
                <div className="flex items-baseline justify-between text-xs">
                  <span className="text-stone-700" title={s.description}>
                    {s.label}
                  </span>
                  <span className="tabular-nums text-stone-500">
                    <span className="font-medium text-stone-900">{w}</span> · {share}%
                  </span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={50}
                  step={5}
                  value={w}
                  aria-label={`${s.label} weight`}
                  onChange={(e) => onChange({ ...weights, [s.key]: Number(e.target.value) })}
                  className="mt-1 w-full accent-stone-900"
                />
              </label>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex items-center justify-between text-[11px] text-stone-500">
        <span>{total === 0 ? "All weights are zero — no score." : "Shares re-normalise to 100%."}</span>
        <button
          type="button"
          disabled={isDefault}
          onClick={() => onChange({ ...view.weights })}
          className="rounded border border-stone-300 px-2 py-0.5 text-stone-700 enabled:hover:border-stone-500 disabled:opacity-40"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
