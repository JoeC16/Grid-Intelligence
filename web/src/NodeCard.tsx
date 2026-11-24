import type { BspRow, SiteProps, Source } from "./api";

// Card for an upper-level node with no map site of its own: a Spanish transmission
// node (Red Eléctrica), or a GB BSP without its own board. Opened from the network view.

const fmt = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 });

function Row({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-stone-600">{label}</span>
      <span className="shrink-0 tabular-nums text-stone-900">
        {value} {unit && <span className="text-stone-500">{unit}</span>}
      </span>
    </div>
  );
}

interface Props {
  node: BspRow;
  level: string; // "BSP" | "transmission node"
  sites: SiteProps[]; // the sites hanging off this node
  sources: Source[];
  onSelect: (siteId: string) => void;
  onClose: () => void;
}

export default function NodeCard({ node, level, sites, sources, onSelect, onClose }: Props) {
  const es = level === "transmission node";
  const kids = [...sites].sort((a, b) => (b.queue_mw ?? 0) - (a.queue_mw ?? 0));
  return (
    <aside className="flex h-full w-full flex-col overflow-hidden rounded-t-xl bg-white shadow-xl sm:w-[380px] sm:rounded-none">
      <div className="flex items-start justify-between border-b border-stone-200 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-stone-900">{node.name}</h2>
          <p className="mt-0.5 text-xs text-stone-500">
            {es ? "Transmission node (Red Eléctrica)" : "Bulk supply point"} · {node.site_count} {es ? "busbars" : "sites"} under it
            {node.stuck_rank != null && ` · rank ${node.stuck_rank} by stuck MW`}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close panel" className="ml-3 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-3">
        {node.matched ? (
          <>
            <Row label="Stuck demand under it" value={fmt(node.stuck_mw)} unit="MW" />
            <Row label={es ? "Published headroom (ordinary demand)" : "Published headroom"} value={fmt(node.headroom_mw)} unit="MW" />
            {es && node.cep_mw != null && <Row label="For power-electronics demand (CEP)" value={fmt(node.cep_mw)} unit="MW" />}
            <Row label="Queued under it" value={fmt(node.queue_mw)} unit="MW" />
            <Row label="Left after queue" value={fmt(node.headroom_after_queue_mw)} unit="MW" />
            {es && node.free_bays != null && <Row label="Free bays" value={String(node.free_bays)} />}
          </>
        ) : (
          <p className="text-sm text-stone-600">No published headroom for this {level}.</p>
        )}
        {node.note && <p className="mt-2 text-[11px] leading-snug text-stone-500">{node.note}</p>}
        {es && (
          <p className="mt-2 text-[11px] leading-snug text-stone-500">
            Headroom here = Red Eléctrica's published demand capacity for ordinary loads minus requests admitted at the node.
            Busbars are linked to it as published by their distributor ("nudo de afección" in the CNMC generation map). Indicative,
            not additive.
          </p>
        )}
        <p className="mt-1 text-[11px]">
          {sources.map((x, i) => (
            <span key={x.dataset_id}>
              {i > 0 && " + "}
              <a href={x.url} target="_blank" rel="noreferrer" className="text-stone-500 underline decoration-stone-300 underline-offset-2 hover:text-stone-800">
                {x.dataset_id} · {x.publish_date}
              </a>
            </span>
          ))}
        </p>

        <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">
          {es ? "Busbars" : "Sites"} under it, most queued first
        </h3>
        <ul className="mt-1 divide-y divide-stone-100">
          {kids.map((s) => (
            <li key={s.site_id}>
              <button type="button" onClick={() => onSelect(s.site_id)} className="flex w-full items-baseline justify-between gap-2 py-1.5 text-left text-xs hover:underline">
                <span className="min-w-0 truncate text-stone-800">{s.name}</span>
                <span className="shrink-0 tabular-nums text-stone-500">
                  {fmt(s.queue_mw)} MW queued · {fmt(s.demand_headroom_mw)} MW headroom
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
