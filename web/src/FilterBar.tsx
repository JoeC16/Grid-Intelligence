import type { Filters, Meta } from "./api";

interface Props {
  meta: Meta | null;
  filters: Filters;
  onChange: (f: Filters) => void;
  shown: number | null;
  /** Min score only applies when ranking by score. */
  showMinScore: boolean;
}

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function Chip({ active, onClick, title, children }: { active: boolean; onClick: () => void; title?: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
        active
          ? "border-stone-900 bg-stone-900 text-white"
          : "border-stone-300 bg-white text-stone-700 hover:border-stone-500"
      }`}
    >
      {children}
    </button>
  );
}

export default function FilterBar({ meta, filters, onChange, shown, showMinScore }: Props) {
  if (!meta) return null;
  // Areas grouped by network operator; a network chip (shown once there are several) selects all its areas.
  const dnos = meta.dnos ?? [];
  const owner = new Map(dnos.flatMap((d) => d.licence_areas.map((a) => [a, d.name] as const)));
  const areas = [...dnos.flatMap((d) => d.licence_areas.filter((a) => meta.licence_areas.includes(a))),
    ...meta.licence_areas.filter((a) => !owner.has(a))];
  const hasAll = (d: (typeof dnos)[number]) => d.licence_areas.every((a) => filters.licenceAreas.includes(a));
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      {dnos.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Network operator">
          <span className="mr-1 text-xs text-stone-500">Network</span>
          {dnos.map((d) => (
            <Chip
              key={d.code}
              active={hasAll(d)}
              title={`${d.name}: ${d.region}`}
              onClick={() => {
                const rest = filters.licenceAreas.filter((a) => !d.licence_areas.includes(a));
                onChange({ ...filters, licenceAreas: hasAll(d) ? rest : [...rest, ...d.licence_areas] });
              }}
            >
              {d.code}
            </Chip>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Licence area">
        <span className="mr-1 text-xs text-stone-500">Area</span>
        {areas.map((a) => (
          <Chip
            key={a}
            active={filters.licenceAreas.includes(a)}
            title={owner.get(a)}
            onClick={() => onChange({ ...filters, licenceAreas: toggle(filters.licenceAreas, a) })}
          >
            {a}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Voltage">
        <span className="mr-1 text-xs text-stone-500">Voltage</span>
        {meta.voltages.map((v) => (
          <Chip
            key={v}
            active={filters.voltages.includes(v)}
            onClick={() => onChange({ ...filters, voltages: toggle(filters.voltages, v) })}
          >
            {v} kV
          </Chip>
        ))}
      </div>

{showMinScore && (
      <label className="flex items-center gap-2 text-xs text-stone-500">
        Min score
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={filters.minScore}
          onChange={(e) => onChange({ ...filters, minScore: Number(e.target.value) })}
          className="w-28 accent-stone-900"
        />
        <span className="w-6 tabular-nums font-medium text-stone-800">{filters.minScore}</span>
      </label>
      )}

      <span className="text-xs text-stone-500 tabular-nums">
        {shown ?? "…"} of {meta.site_count} substations
      </span>
    </div>
  );
}
