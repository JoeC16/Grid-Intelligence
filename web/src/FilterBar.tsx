import type { CountryInfo, DnoInfo, Filters, Meta } from "./api";

interface Props {
  meta: Meta | null;
  /** The country shown: its areas and voltages. */
  country: CountryInfo | null;
  /** The DNOs in that country. */
  dnos: DnoInfo[];
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

// With many busbar voltages (Spain publishes 22), filter by band instead of by each voltage.
// Bands follow the Spanish regulatory split: medium voltage up to 36 kV, high voltage above.
const MAX_VOLTAGE_CHIPS = 8;
const BANDS = [
  { key: "mv", label: "≤ 36 kV", test: (v: number) => v <= 36 },
  { key: "hv", label: "> 36 kV", test: (v: number) => v > 36 },
];

export default function FilterBar({ meta, country, dnos, filters, onChange, shown, showMinScore }: Props) {
  if (!meta) return null;
  // Areas grouped by network operator; a network chip (shown once there are several) selects all its areas.
  const inCountry = country?.licence_areas ?? meta.licence_areas;
  const owner = new Map(dnos.flatMap((d) => d.licence_areas.map((a) => [a, d.name] as const)));
  const areas = [...dnos.flatMap((d) => d.licence_areas.filter((a) => inCountry.includes(a))),
    ...inCountry.filter((a) => !owner.has(a))];
  const voltages = country?.voltages ?? meta.voltages;
  const banded = voltages.length > MAX_VOLTAGE_CHIPS;
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
        {banded
          ? BANDS.map((b) => {
              const vs = voltages.filter(b.test);
              const on = vs.length > 0 && vs.every((v) => filters.voltages.includes(v));
              return (
                <Chip
                  key={b.key}
                  active={on}
                  title={vs.map((v) => `${v} kV`).join(", ")}
                  onClick={() => {
                    const rest = filters.voltages.filter((v) => !vs.includes(v));
                    onChange({ ...filters, voltages: on ? rest : [...rest, ...vs] });
                  }}
                >
                  {b.label}
                </Chip>
              );
            })
          : voltages.map((v) => (
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
        {shown?.toLocaleString("en-GB") ?? "…"} of {(country?.site_count ?? meta.site_count).toLocaleString("en-GB")} {country && country.has_gsp === false ? "busbars" : "substations"}
      </span>
    </div>
  );
}
