import { useMemo, useState } from "react";
import type { OperatorRow, Source } from "./api";

// Distributors (Spain): one row per distribution network operator, from gold.operator_mart.
// The "which networks to buy or expand" view: how full each network is and how much demand is waiting.

interface Props {
  operators: OperatorRow[] | null;
  source: Source | null;
  period: string;
  note: string;
  selectedOperator: string | null;
  onSelect: (o: OperatorRow) => void;
  onClose: () => void;
  error: string | null;
}

type Sort = "stuck" | "full" | "queue" | "size";

const mw = (v: number | null) => (v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 }));
const pct = (v: number) => `${(Math.floor(v * 1000 + 0.5) / 10).toFixed(1)}%`;

const SORTS: { key: Sort; label: string; title: string }[] = [
  { key: "stuck", label: "Stuck MW", title: "Requests waiting beyond published headroom, summed over the operator's busbars" },
  { key: "full", label: "% full", title: "Share of busbars with zero published headroom" },
  { key: "queue", label: "Waiting", title: "MW of requests admitted and not yet evaluated" },
  { key: "size", label: "Size", title: "Busbars published" },
];

function csv(rows: OperatorRow[], context: string[]): string {
  const cols: (keyof OperatorRow)[] = ["operator", "operator_name", "provinces", "sites", "substations", "sites_zero_headroom",
    "share_zero_headroom", "headroom_mw", "queue_mw", "stuck_mw", "capacity_taken_mw", "top_site_name", "top_site_stuck_mw"];
  const esc = (v: unknown) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  return [...context.map((c) => `# ${c}`), cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export default function OperatorList({ operators, source, period, note, selectedOperator, onSelect, onClose, error }: Props) {
  const [sort, setSort] = useState<Sort>("stuck");
  const rows = useMemo(() => {
    const r = [...(operators ?? [])];
    const by: Record<Sort, (o: OperatorRow) => number> = {
      stuck: (o) => o.stuck_mw, full: (o) => o.share_zero_headroom, queue: (o) => o.queue_mw, size: (o) => o.sites,
    };
    return r.sort((a, b) => by[sort](b) - by[sort](a) || b.sites - a.sites || a.operator_name.localeCompare(b.operator_name));
  }, [operators, sort]);

  const download = () => {
    const text = csv(rows, [
      `Grid Intelligence: distribution network operators, ${new Date().toISOString().slice(0, 10)}`,
      `Source: ${source ? `${source.dataset_id} (published ${source.publish_date}) ${source.url}` : "CNMC"}; data period ${period}`,
      "Fuente: CNMC. Licensed under CC BY-SA 4.0. Published headroom is indicative and not guaranteed.",
      note,
    ]);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    a.download = "distributors.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="pointer-events-auto flex max-h-full w-[22rem] max-w-[calc(100vw-1.5rem)] flex-col rounded-md bg-white shadow-lg">
      <div className="flex items-start justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-stone-900">Distributors</p>
          <p className="mt-0.5 text-[11px] leading-snug text-stone-500">
            Every distribution network operator in the CNMC data ({period}): how full its network is and how much demand is
            waiting. Click one to see its most stuck busbar.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close distributors" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-1 border-b border-stone-100 px-4 py-2" role="group" aria-label="Sort distributors">
        <span className="mr-1 text-[11px] text-stone-500">Sort</span>
        {SORTS.map((s) => (
          <button
            key={s.key}
            type="button"
            title={s.title}
            aria-pressed={sort === s.key}
            onClick={() => setSort(s.key)}
            className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
              sort === s.key ? "border-stone-900 bg-stone-900 text-white" : "border-stone-300 text-stone-700 hover:border-stone-500"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      {error && <p className="px-4 py-2 text-xs text-red-700">{error}</p>}
      {!operators && !error && <p className="px-4 py-2 text-xs text-stone-500">Loading…</p>}
      <ol className="flex-1 overflow-y-auto py-1">
        {rows.map((o, i) => (
          <li key={o.operator}>
            <button
              type="button"
              onClick={() => onSelect(o)}
              title={o.top_site_name ? `Most stuck: ${o.top_site_name} (${mw(o.top_site_stuck_mw)} MW)` : "No busbar with stuck demand"}
              className={`flex w-full items-baseline gap-3 px-4 py-1.5 text-left hover:bg-stone-50 ${o.operator === selectedOperator ? "bg-stone-100" : ""}`}
            >
              <span className="w-6 shrink-0 text-right text-xs tabular-nums text-stone-400">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-stone-900">{o.operator_name}</span>
                <span className="block text-[11px] leading-snug text-stone-500">
                  {o.sites} busbar{o.sites === 1 ? "" : "s"} · {pct(o.share_zero_headroom)} at zero headroom · {mw(o.queue_mw)} MW waiting ·{" "}
                  <span className="font-medium text-stone-700">{mw(o.stuck_mw)} MW stuck</span>
                </span>
                <span className="block truncate text-[11px] text-stone-400">{o.provinces}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
      <div className="space-y-1 border-t border-stone-200 px-4 py-2 text-[11px] text-stone-500">
        <p>{note}</p>
        <p className="flex items-center justify-between gap-2">
          {source ? (
            <a href={source.url} target="_blank" rel="noreferrer" className="underline decoration-stone-300 underline-offset-2 hover:text-stone-800">
              {source.dataset_id} · {source.publish_date}
            </a>
          ) : (
            <span>CNMC</span>
          )}
          <button type="button" onClick={download} className="font-medium text-stone-700 underline decoration-stone-300 underline-offset-2">
            Download CSV
          </button>
        </p>
      </div>
    </div>
  );
}
