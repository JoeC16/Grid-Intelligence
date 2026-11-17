import type { Signal, SiteDetail, Source } from "./api";
import { scoreColor } from "./colors";

interface Props {
  site: SiteDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

const fmt = (v: number | null, digits = 1) =>
  v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

function SourceLink({ source }: { source: Source | null }) {
  if (!source) return <span className="text-stone-400">no source</span>;
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noreferrer"
      className="text-stone-500 underline decoration-stone-300 underline-offset-2 hover:text-stone-800"
      title={`Open ${source.dataset_id} on the UKPN Open Data Portal`}
    >
      {source.dataset_id} · {source.publish_date}
    </a>
  );
}

function PercentileBar({ value }: { value: number | null }) {
  if (value == null) return <div className="h-1.5 w-full rounded-full bg-stone-100" />;
  return (
    <div className="h-1.5 w-full rounded-full bg-stone-100" aria-label={`${Math.round(value * 100)}th percentile`}>
      <div className="h-1.5 rounded-full bg-stone-700" style={{ width: `${Math.max(value * 100, 2)}%` }} />
    </div>
  );
}

function SignalRow({ s }: { s: Signal }) {
  return (
    <li className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-stone-700">{s.label}</span>
        <span className="text-sm font-semibold tabular-nums text-stone-900">
          {fmt(s.value, s.unit === "offers" ? 0 : 1)} <span className="font-normal text-stone-500">{s.unit}</span>
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-3">
        <PercentileBar value={s.percentile} />
        <span className="w-24 shrink-0 text-right text-[11px] tabular-nums text-stone-500">
          {s.percentile == null ? "not ranked" : `${Math.round(s.percentile * 100)}th pct`} · w{s.weight}
        </span>
      </div>
      {s.note && <p className="mt-1 text-[11px] text-stone-500">{s.note}</p>}
      <p className="mt-1 text-[11px]">
        <SourceLink source={s.source} />
      </p>
    </li>
  );
}

function Row({ label, value, unit }: { label: string; value: number | null; unit: string }) {
  return (
    <div className="flex items-baseline justify-between py-1 text-sm">
      <span className="text-stone-600">{label}</span>
      <span className="tabular-nums text-stone-900">
        {fmt(value)} <span className="text-stone-500">{unit}</span>
      </span>
    </div>
  );
}

export default function SidePanel({ site, loading, error, onClose }: Props) {
  return (
    <aside className="flex h-full w-full flex-col overflow-hidden bg-white shadow-xl sm:w-[380px]">
      <div className="flex items-start justify-between border-b border-stone-200 px-5 py-4">
        <div className="min-w-0">
          {site ? (
            <>
              <h2 className="truncate text-base font-semibold text-stone-900" title={site.name}>
                {site.name}
              </h2>
              <p className="mt-0.5 text-xs text-stone-500">
                {site.licence_area} · {site.voltage} kV · GSP {site.gsp ?? "unmapped"} ·{" "}
                <span className="font-mono">{site.site_id}</span>
              </p>
            </>
          ) : (
            <h2 className="text-base font-semibold text-stone-900">{loading ? "Loading…" : "Substation"}</h2>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close panel"
          className="ml-3 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pb-6">
        {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
        {site && (
          <>
            <section className="flex items-center gap-4 py-4">
              <div
                className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-xl font-semibold text-white"
                style={{ background: scoreColor(site.score) }}
              >
                {site.score == null ? "—" : Math.round(site.score)}
              </div>
              <div className="text-sm">
                <p className="font-medium text-stone-900">Stuck-demand score</p>
                {site.score != null ? (
                  <p className="text-stone-500">
                    Rank {site.rank} of {site.rank_of} UKPN primaries
                  </p>
                ) : (
                  <p className="text-stone-500">Not scored: {site.exclude_reason}</p>
                )}
                {site.score_missing && (
                  <p className="mt-0.5 text-xs text-stone-500">Scored without: {site.score_missing.split(",").join(", ")}</p>
                )}
              </div>
            </section>

            <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500">Signals</h3>
            <ul className="divide-y divide-stone-100">
              {site.signals.map((s) => (
                <SignalRow key={s.key} s={s} />
              ))}
            </ul>

            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">Capacity</h3>
            <div className="py-2">
              <Row label="Firm capacity" value={site.capacity.firm_capacity_mw} unit="MW" />
              <Row label="Observed peak (24/25)" value={site.capacity.observed_peak_mw} unit="MW" />
              <p className="mt-1 text-[11px]">
                <SourceLink source={site.capacity.source} />
              </p>
            </div>

            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">
              Published headroom 2030 by scenario
            </h3>
            <div className="py-2">
              {site.headroom_2030.values.map((v) => (
                <Row key={v.scenario} label={v.scenario + (v.default ? " (used in score)" : "")} value={v.value} unit="MW" />
              ))}
              <p className="mt-1 text-[11px]">
                <SourceLink source={site.headroom_2030.source} />
              </p>
            </div>

            {site.gsp_context && (
              <>
                <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">
                  GSP: {site.gsp_context.name}
                </h3>
                <div className="py-2">
                  <Row label={`Queue, ${site.gsp_context.site_count} primaries`} value={site.gsp_context.primary_queue_mw} unit="MW" />
                  <Row label="Queue at grid level (e.g. 132 kV)" value={site.gsp_context.grid_level_queue_mw} unit="MW" />
                  <p className="text-[11px]">
                    <SourceLink source={site.gsp_context.sources.queue_mw} />
                  </p>
                  <Row label={`Large demand projects (${site.gsp_context.large_demand_count})`} value={site.gsp_context.large_demand_mva} unit="MVA" />
                  <p className="text-[11px]">
                    <SourceLink source={site.gsp_context.sources.large_demand} />
                  </p>
                </div>
              </>
            )}

            <p className="mt-4 rounded-md bg-stone-50 p-3 text-[11px] leading-relaxed text-stone-600">{site.disclaimer}</p>
          </>
        )}
      </div>
    </aside>
  );
}
