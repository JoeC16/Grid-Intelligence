import { useState } from "react";
import type { SiteProps } from "./api";
import { describe, type Ranking } from "./ranking";

interface Props {
  /** Lines describing the view, weights and sources, written at the top of the CSV. */
  exportContext: string[];
  title: string;
  subtitle: string;
  ranking: Ranking;
  sites: Map<string, SiteProps>;
  visible: Set<string>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}

const PAGE = 25;

const csvCell = (v: unknown) => {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

function downloadCsv(filename: string, lines: string[]) {
  const blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function RankList({ exportContext, title, subtitle, ranking, sites, visible, selectedId, onSelect, onClose }: Props) {
  const [shown, setShown] = useState(PAGE);
  // Ranks are national (every network covered); area/voltage filters only hide rows.
  const rows = [...ranking.entries]
    .filter(([id]) => visible.has(id))
    .sort((a, b) => a[1].rank - b[1].rank || (sites.get(a[0])?.name ?? "").localeCompare(sites.get(b[0])?.name ?? ""));

  return (
    <div className="pointer-events-auto flex max-h-full w-80 flex-col rounded-md bg-white shadow-lg">
      <div className="flex items-start justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-stone-900">{title}</p>
          <p className="mt-0.5 text-[11px] leading-snug text-stone-500">{subtitle}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close ranking" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-stone-500">No sites match.</p>
      ) : (
        <ol className="flex-1 overflow-y-auto py-1">
          {rows.slice(0, shown).map(([id, e]) => {
            const s = sites.get(id);
            return (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => onSelect(id)}
                  className={`flex w-full items-baseline gap-3 px-4 py-1.5 text-left hover:bg-stone-50 ${id === selectedId ? "bg-stone-100" : ""}`}
                >
                  <span className="w-7 shrink-0 text-right text-xs tabular-nums text-stone-400">{e.rank}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-stone-900">{s?.name}</span>
                    <span className="block text-[11px] text-stone-500">
                      {s?.licence_area} · {s?.voltage} kV · {describe(ranking, e).replace(/ · rank \d+$/, "")}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
      <div className="flex items-center justify-between border-t border-stone-200 px-4 py-2 text-[11px] text-stone-500">
        <span>
          {Math.min(shown, rows.length)} of {rows.length} shown ·{" "}
          <button
            type="button"
            className="font-medium text-stone-700 hover:underline"
            onClick={() => {
              const header = ["rank", "site_id", "name", "licence_area", "voltage_kv", "gsp", "ranked_on", "value",
                "published_headroom_mw", "queue_mw", "effective_headroom_mw", "stuck_mw", "stuck_demand_score_default_weights"];
              const body = rows.map(([id, e]) => {
                const s = sites.get(id);
                return [e.rank, id, s?.name, s?.licence_area, s?.voltage, s?.gsp, ranking.mode, e.value,
                  s?.demand_headroom_mw, s?.queue_mw, s?.effective_headroom_mw, s?.stuck_mw, s?.score].map(csvCell).join(",");
              });
              downloadCsv(`grid-intelligence-${ranking.mode}-${new Date().toISOString().slice(0, 10)}.csv`,
                [...exportContext.map((l) => csvCell(`# ${l}`)), "", header.join(","), ...body]);
            }}
          >
            Download CSV
          </button>
        </span>
        {shown < rows.length && (
          <button type="button" onClick={() => setShown((n) => n + PAGE)} className="font-medium text-stone-700 hover:underline">
            Show more
          </button>
        )}
      </div>
    </div>
  );
}
