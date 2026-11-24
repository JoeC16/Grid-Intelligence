import { useMemo, useState } from "react";
import type { Source, UnlockNode } from "./api";

// Best next moves: upper-level nodes ranked by what added capacity there unlocks
// (gold.unlock_mart). Click one to open its what-if card.

type Goal = "new" | "queue";

interface Props {
  nodes: UnlockNode[] | null;
  steps: number[];
  loadMw: number;
  level: string; // "BSP" | "transmission node"
  caveat: string;
  sources: Source[];
  selectedNode: string | null;
  onSelect: (n: UnlockNode) => void;
  onClose: () => void;
  error: string | null;
}

const mw = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 }));
const r3 = (v: number | null | undefined) => Math.round((v ?? 0) * 1000) / 1000;

export default function UnlockPanel({ nodes, steps, loadMw, level, caveat, sources, selectedNode, onSelect, onClose, error }: Props) {
  const [goal, setGoal] = useState<Goal>("new");
  const shown = steps.filter((s) => s >= 10 && s <= 200);
  const [step, setStep] = useState(50);
  const val = (n: UnlockNode, a: number) => (goal === "new" ? n[`new_${a}`] : n[`served_${a}`]) as number | null;
  const rows = useMemo(() => {
    // Same order as the pipeline's rank at +50 MW (gain, then sites opened, then the next step), for any step.
    const next = steps.find((s) => s > step) ?? step;
    return (nodes ?? [])
      .filter((n) => r3(val(n, step)) > 0)
      .sort((a, b) => r3(val(b, step)) - r3(val(a, step))
        || ((b[`open_${step}`] as number) ?? 0) - ((a[`open_${step}`] as number) ?? 0)
        || r3(val(b, next)) - r3(val(a, next))
        || a.name.localeCompare(b.name));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, goal, step, steps]);
  const levels = level === "BSP" ? "BSPs" : "transmission nodes";

  return (
    <div className="pointer-events-auto flex max-h-full w-[22rem] max-w-[calc(100vw-1.5rem)] flex-col rounded-md bg-white shadow-lg">
      <div className="flex items-start justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-stone-900">Best next moves</p>
          <p className="mt-0.5 text-[11px] leading-snug text-stone-500">
            Where added capacity at a {level} unlocks the most demand under it. Click one for its what-if slider.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close best next moves" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      <div className="space-y-1.5 border-b border-stone-100 px-4 py-2 text-[11px]">
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Goal">
          <span className="mr-1 text-stone-500">Goal</span>
          {(
            [
              ["new", "Open new capacity", "Room for new demand beyond today's queue"],
              ["queue", "Serve the queue", "Queued demand waiting only on this node"],
            ] as [Goal, string, string][]
          ).map(([k, label, title]) => (
            <button key={k} type="button" title={title} aria-pressed={goal === k} onClick={() => setGoal(k)}
              className={`rounded-full border px-2 py-0.5 font-medium ${goal === k ? "border-stone-900 bg-stone-900 text-white" : "border-stone-300 text-stone-700 hover:border-stone-500"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="MW added">
          <span className="mr-1 text-stone-500">Add</span>
          {shown.map((s) => (
            <button key={s} type="button" aria-pressed={step === s} onClick={() => setStep(s)}
              className={`rounded-full border px-2 py-0.5 font-medium tabular-nums ${step === s ? "border-stone-900 bg-stone-900 text-white" : "border-stone-300 text-stone-700 hover:border-stone-500"}`}>
              +{s} MW
            </button>
          ))}
        </div>
      </div>
      {error && <p className="px-4 py-2 text-xs text-red-700">{error}</p>}
      {!nodes && !error && <p className="px-4 py-2 text-xs text-stone-500">Loading…</p>}
      <ol className="flex-1 overflow-y-auto py-1">
        {rows.map((n, i) => {
          const opened = (n[`open_${step}`] as number) ?? 0;
          return (
            <li key={n.bsp_id}>
              <button type="button" onClick={() => onSelect(n)}
                className={`flex w-full items-baseline gap-3 px-4 py-1.5 text-left hover:bg-stone-50 ${n.bsp_id === selectedNode ? "bg-stone-100" : ""}`}>
                <span className="w-6 shrink-0 text-right text-xs tabular-nums text-stone-400">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-stone-900">{n.name}</span>
                  <span className="block text-[11px] leading-snug text-stone-500">
                    +{step} MW →{" "}
                    <span className="font-medium text-stone-700">
                      {mw(val(n, step))} MW {goal === "new" ? "new capacity" : "of queue served"}
                    </span>
                    {goal === "new" && `, ${opened} ${level === "BSP" ? "site" : "busbar"}${opened === 1 ? "" : "s"} open for ${loadMw} MW`}
                  </span>
                  <span className="block text-[11px] text-stone-400">
                    {n.sites} {level === "BSP" ? "sites" : "busbars"} · queue beyond its headroom {mw(n.node_stuck_mw)} MW
                    {n.mw_to_first_open != null ? ` · first ${loadMw} MW connection after +${mw(n.mw_to_first_open)} MW` : ""}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {nodes && rows.length === 0 && <li className="px-4 py-2 text-xs text-stone-500">No {levels} gain from +{step} MW.</li>}
      </ol>
      <div className="space-y-1 border-t border-stone-200 px-4 py-2 text-[11px] text-stone-500">
        <p>{caveat}</p>
        <p>
          {sources.map((x, i) => (
            <span key={x.dataset_id}>
              {i > 0 && " + "}
              <a href={x.url} target="_blank" rel="noreferrer" className="underline decoration-stone-300 underline-offset-2 hover:text-stone-800">
                {x.dataset_id} · {x.publish_date}
              </a>
            </span>
          ))}
        </p>
      </div>
    </div>
  );
}
