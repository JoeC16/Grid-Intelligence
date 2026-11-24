import { useEffect, useMemo, useState } from "react";
import type { BspRow, SiteProps, Source } from "./api";
import { mwToFirstOpen, nodeInputs, unlockAt } from "./unlock";

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
  /** What-if: called with the sites that would open, so the map can ring them. */
  onWhatIf?: (openIds: string[]) => void;
  loadMw?: number;
  caveat?: string;
}

function WhatIf({ node, sites, level, loadMw, caveat, onWhatIf }: {
  node: BspRow; sites: SiteProps[]; level: string; loadMw: number; caveat?: string; onWhatIf?: (ids: string[]) => void;
}) {
  const inputs = useMemo(() => nodeInputs(node, sites), [node, sites]);
  const [added, setAdded] = useState(50);
  const [load, setLoad] = useState(loadMw);
  const base = useMemo(() => (inputs ? unlockAt(inputs, 0, load) : null), [inputs, load]);
  const r = useMemo(() => (inputs ? unlockAt(inputs, added, load) : null), [inputs, added, load]);
  const first = inputs ? mwToFirstOpen(inputs, load) : null;
  useEffect(() => {
    onWhatIf?.(r?.openIds ?? []);
    return () => onWhatIf?.([]);
  }, [r, onWhatIf]);
  if (!inputs || !r || !base) return null;
  const newGain = r.newCapacity - base.newCapacity;
  const openGain = r.sitesOpen - base.sitesOpen;
  return (
    <section className="mt-4 rounded-md border border-stone-200 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-stone-500">What if: add capacity here</h3>
      <label className="mt-2 flex items-center gap-3 text-sm text-stone-700">
        <span className="w-20 shrink-0 tabular-nums font-semibold text-stone-900">+{added} MW</span>
        <input type="range" min={0} max={400} step={5} value={added} onChange={(e) => setAdded(Number(e.target.value))}
          className="flex-1 accent-stone-900" aria-label={`MW added at the ${level}`} />
      </label>
      <label className="mt-1 flex items-center gap-2 text-[11px] text-stone-500">
        Sites open for a load of
        <input type="number" min={1} max={500} value={load} onChange={(e) => setLoad(Math.max(1, Number(e.target.value) || 1))}
          className="w-14 rounded border border-stone-300 px-1 py-0.5 text-right tabular-nums text-stone-800" />
        MW
      </label>
      <div className="mt-2">
        <Row label="Queue served (waiting only on this node)" value={fmt(r.servedNodeOnly)} unit="MW" />
        <Row label="… if its sites were upgraded too" value={fmt(r.servedWithLocal)} unit="MW" />
        <Row label="New capacity opened (beyond the queue)" value={fmt(newGain)} unit="MW" />
        <Row label={`${isEs(level) ? "Busbars" : "Sites"} newly able to take ${load} MW`} value={`${openGain} of ${inputs.sites.length}`} />
      </div>
      <p className="mt-1 text-[11px] leading-snug text-stone-500">
        {first == null
          ? `No ${isEs(level) ? "busbar" : "site"} under it has ${load} MW of its own headroom: it would need a local upgrade too.`
          : first === 0
            ? `A ${load} MW connection already fits at ${base.sitesOpen} ${isEs(level) ? "busbar" : "site"}${base.sitesOpen === 1 ? "" : "s"} without adding anything.`
            : `The first ${load} MW connection opens after +${fmt(first)} MW (the queue under the ${level} comes first).`}{" "}
        Opened {isEs(level) ? "busbars" : "sites"} are ringed on the map.
      </p>
      {caveat && <p className="mt-1 text-[11px] leading-snug text-stone-400">{caveat}</p>}
    </section>
  );
}

const isEs = (level: string) => level !== "BSP";

export default function NodeCard({ node, level, sites, sources, onSelect, onClose, onWhatIf, loadMw = 10, caveat }: Props) {
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

        {node.matched && node.headroom_mw != null && (
          <WhatIf node={node} sites={sites} level={level} loadMw={loadMw} caveat={caveat} onWhatIf={onWhatIf} />
        )}

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
