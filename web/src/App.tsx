import { useEffect, useState } from "react";
import { fetchMeta, fetchSite, fetchSites, type Filters, type Meta, type SiteDetail, type SitesGeoJSON } from "./api";
import { scoreGradientCss, UNSCORED } from "./colors";
import FilterBar from "./FilterBar";
import MapView from "./MapView";
import SidePanel from "./SidePanel";

const INITIAL_FILTERS: Filters = { licenceAreas: [], voltages: [], minScore: 0 };

function Legend() {
  return (
    <div className="pointer-events-auto rounded-md bg-white/95 px-3 py-2 text-[11px] text-stone-600 shadow">
      <p className="mb-1 font-medium text-stone-800">Stuck-demand score</p>
      <div className="h-2 w-40 rounded-full" style={{ background: scoreGradientCss }} />
      <div className="mt-0.5 flex w-40 justify-between tabular-nums">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: UNSCORED }} />
        Not scored
      </div>
    </div>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [sites, setSites] = useState<SitesGeoJSON | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SiteDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMeta().then(setMeta).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    let live = true;
    fetchSites(filters)
      .then((d) => live && setSites(d))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [filters]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let live = true;
    setDetailLoading(true);
    fetchSite(selectedId)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(String(e)))
      .finally(() => live && setDetailLoading(false));
    return () => {
      live = false;
    };
  }, [selectedId]);

  return (
    <div className="flex h-full flex-col bg-stone-50 text-stone-900">
      <header className="z-10 flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-stone-200 bg-white px-4 py-2.5">
        <div>
          <h1 className="text-sm font-semibold">Grid Intelligence</h1>
          <p className="text-[11px] text-stone-500">Stuck demand at UK Power Networks primary substations</p>
        </div>
        <FilterBar meta={meta} filters={filters} onChange={setFilters} shown={sites?.count ?? null} />
      </header>

      <main className="relative flex-1">
        <MapView sites={sites} selectedId={selectedId} onSelect={setSelectedId} />
        <div className="pointer-events-none absolute left-3 top-3 sm:bottom-8 sm:top-auto">
          <Legend />
        </div>
        {error && !selectedId && (
          <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-800 shadow">
            {error}. Is the API running?
          </div>
        )}
        {selectedId && (
          <div className="absolute inset-y-0 right-0 z-10 w-full sm:w-auto">
            <SidePanel site={detail} loading={detailLoading} error={error} onClose={() => setSelectedId(null)} />
          </div>
        )}
      </main>
    </div>
  );
}
