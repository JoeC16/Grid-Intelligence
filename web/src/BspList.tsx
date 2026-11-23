import type { BspRow } from "./api";

interface Props {
  bsps: BspRow[];
  visibleSites: Set<string>;
  selectedBspId: string | null;
  onSelect: (b: BspRow) => void;
  onClose: () => void;
}

const mw = (v: number | null) => (v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 }));

export default function BspList({ bsps, visibleSites, selectedBspId, onSelect, onClose }: Props) {
  // Ranked BSPs only; area/voltage filters hide BSPs with no visible site.
  const rows = bsps
    .filter((b) => b.stuck_rank != null && b.site_ids.some((id) => visibleSites.has(id)))
    .sort((a, b) => a.stuck_rank! - b.stuck_rank! || a.name.localeCompare(b.name));
  return (
    <div className="pointer-events-auto flex max-h-full w-80 flex-col rounded-md bg-white shadow-lg">
      <div className="flex items-start justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-stone-900">BSPs by stuck MW</p>
          <p className="mt-0.5 text-[11px] leading-snug text-stone-500">
            Demand queued under each bulk supply point beyond its published headroom, largest first.
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close ranking" className="ml-2 rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
          ✕
        </button>
      </div>
      <ol className="flex-1 overflow-y-auto py-1">
        {rows.map((b) => (
          <li key={b.bsp_id}>
            <button
              type="button"
              onClick={() => onSelect(b)}
              className={`flex w-full items-baseline gap-3 px-4 py-1.5 text-left hover:bg-stone-50 ${b.bsp_id === selectedBspId ? "bg-stone-100" : ""}`}
            >
              <span className="w-7 shrink-0 text-right text-xs tabular-nums text-stone-400">{b.stuck_rank}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-stone-900">{b.name}</span>
                <span className="block text-[11px] text-stone-500">
                  {b.licence_area} · {b.site_count} sites · {mw(b.stuck_mw)} MW stuck ({mw(b.queue_mw)} queued, {mw(b.headroom_mw)} headroom)
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
      <div className="border-t border-stone-200 px-4 py-2 text-[11px] text-stone-500">{rows.length} BSPs with stuck demand</div>
    </div>
  );
}
