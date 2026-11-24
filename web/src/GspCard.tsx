import type { GspRow } from "./api";

const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 });

function Row({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="flex items-baseline justify-between py-1 text-sm">
      <span className="text-stone-600">{label}</span>
      <span className="tabular-nums text-stone-900">
        {value} {unit && <span className="text-stone-500">{unit}</span>}
      </span>
    </div>
  );
}

export default function GspCard({ gsp, onClose }: { gsp: GspRow; onClose: () => void }) {
  return (
    <aside className="flex h-full w-full flex-col overflow-hidden rounded-t-xl bg-white shadow-xl sm:w-[380px] sm:rounded-none">
      <div className="flex items-start justify-between border-b border-stone-200 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-stone-900">{gsp.gsp}</h2>
          <p className="mt-0.5 text-xs text-stone-500">Grid supply point · {gsp.licence_area ?? "—"} · {gsp.bsp_count} BSPs · {gsp.site_count} primaries</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close panel" className="ml-3 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-3">
        <Row label="Stuck demand under it" value={fmt(gsp.stuck_mw)} unit="MW" />
        {gsp.stuck_rank != null && <p className="-mt-1 text-right text-[11px] text-stone-500">rank {gsp.stuck_rank} of GSPs</p>}
        <Row label="Demand queued (primaries)" value={fmt(gsp.primary_queue_mw)} unit="MW" />
        <Row label="Demand queued at grid level" value={fmt(gsp.grid_level_queue_mw)} unit="MW" />
        <Row label="Primaries limited by their BSP" value={String(gsp.sites_limited_by_bsp)} />
        <Row label={`Primaries running out by ${gsp.running_out_by_year}`} value={String(gsp.sites_running_out_by)} />
        <Row label="Earliest a primary runs out" value={gsp.earliest_runs_out_year ? String(gsp.earliest_runs_out_year) : "not by 2050"} />
        <Row label={`Large demand projects (${gsp.large_demand_count})`} value={fmt(gsp.large_demand_mva)} unit="MVA" />
        <Row label="Import utilisation (peak / capacity)" value={fmt(gsp.import_capacity_utilisation_pct)} unit="%" />
        <p className="mt-3 text-[11px] leading-relaxed text-stone-500">
          GSPs publish no MW headroom. Stuck demand here is the sum over its bulk supply points and directly fed primaries.
          "Running out" = the first year UKPN's DFES forecast (default scenario) puts a primary's published headroom below zero.
          Open Sources &amp; licences for datasets and dates.
        </p>
      </div>
    </aside>
  );
}
