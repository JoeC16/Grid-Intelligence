import { useState } from "react";
import type { Meta } from "./api";

const CC_BY = "https://creativecommons.org/licenses/by/4.0/";
const OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/";

// What each field means to a reader, for the sources list.
const FIELD_LABELS: Record<string, string> = {
  name: "substation list and locations",
  demand_headroom_mw: "published headroom",
  firm_capacity_mw: "firm capacity and observed peak",
  queue_mw: "demand queue",
  grid_level_queue_mw: "grid-level queue",
  connections_last_year: "connections in the past year",
  headroom_2030_mw: "2030 published headroom",
  gsp: "grid supply points",
  large_demand: "large demand projects",
};

function SourcesDialog({ meta, onClose }: { meta: Meta; onClose: () => void }) {
  // One row per dataset, with what the app uses it for.
  const byDataset = new Map<string, { url: string; date: string; licence: string; uses: Set<string> }>();
  for (const s of meta.sources) {
    const row = byDataset.get(s.dataset_id) ?? { url: s.url, date: s.publish_date, licence: s.licence, uses: new Set<string>() };
    const label = FIELD_LABELS[s.field];
    if (label) row.uses.add(label);
    byDataset.set(s.dataset_id, row);
  }
  const year = new Date().getFullYear();
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 sm:items-center" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Data sources and licences"
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-t-lg bg-white p-5 shadow-xl sm:rounded-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-stone-900">Data sources and licences</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
            ✕
          </button>
        </div>
        <p className="mt-2 text-sm text-stone-700">{meta.disclaimer}</p>

        <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">UK Power Networks Open Data</h3>
        <p className="mt-1 text-xs text-stone-600">
          Contains data from UK Power Networks, licensed under{" "}
          <a className="underline" href={CC_BY} target="_blank" rel="noreferrer">CC BY 4.0</a>. Changes: datasets joined, aggregated per
          substation and scored by Grid Intelligence. UK Power Networks does not endorse this tool.
        </p>
        <table className="mt-2 w-full text-left text-xs">
          <thead className="text-stone-500">
            <tr>
              <th className="py-1 pr-3 font-medium">Dataset</th>
              <th className="py-1 pr-3 font-medium">Used for</th>
              <th className="py-1 pr-3 font-medium">Published</th>
              <th className="py-1 font-medium">Licence</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {[...byDataset].map(([id, r]) => (
              <tr key={id}>
                <td className="py-1.5 pr-3">
                  <a className="font-mono text-stone-800 underline decoration-stone-300 underline-offset-2" href={r.url} target="_blank" rel="noreferrer">
                    {id}
                  </a>
                </td>
                <td className="py-1.5 pr-3 text-stone-600">{[...r.uses].join(", ")}</td>
                <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums text-stone-600">{r.date}</td>
                <td className="whitespace-nowrap py-1.5 text-stone-600">{r.licence || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">Place names (Ask)</h3>
        <p className="mt-1 text-xs text-stone-600">
          Contains OS data © Crown copyright and database right {year}, from OS Open Names via postcodes.io, licensed under the{" "}
          <a className="underline" href={OGL} target="_blank" rel="noreferrer">Open Government Licence v3.0</a>.
        </p>

        <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-stone-500">Map</h3>
        <p className="mt-1 text-xs text-stone-600">
          Basemap by OpenFreeMap; © OpenMapTiles; data © OpenStreetMap contributors (ODbL).
        </p>
      </div>
    </div>
  );
}

export default function Footer({ meta }: { meta: Meta | null }) {
  const [open, setOpen] = useState(false);
  return (
    <footer className="z-20 flex flex-wrap items-center gap-x-4 gap-y-0.5 border-t border-stone-200 bg-white px-4 py-1.5 text-[11px] text-stone-500">
      <span className="font-medium text-stone-700">Published headroom is indicative and not guaranteed.</span>
      <span>
        Contains data from UK Power Networks (
        <a className="underline" href={CC_BY} target="_blank" rel="noreferrer">CC BY 4.0</a>) · OS Open Names (OGL v3) · © OpenStreetMap contributors
      </span>
      {meta && (
        <button type="button" onClick={() => setOpen(true)} className="font-medium text-stone-700 underline decoration-stone-300 underline-offset-2 hover:text-stone-900">
          Sources & licences
        </button>
      )}
      {open && meta && <SourcesDialog meta={meta} onClose={() => setOpen(false)} />}
    </footer>
  );
}
