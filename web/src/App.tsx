import { useEffect, useMemo, useState } from "react";
import { fetchMeta, fetchSite, fetchSites, type Filters, type Meta, type SiteDetail, type SitesGeoJSON } from "./api";
import { gradientCss, rampFor, UNSCORED, type Ramp } from "./colors";
import { ViewToggle, WeightsPanel } from "./Controls";
import FilterBar from "./FilterBar";
import MapView from "./MapView";
import { rescore, type Weights } from "./scoring";
import SidePanel from "./SidePanel";

const INITIAL_FILTERS: Filters = { licenceAreas: [], voltages: [], minScore: 0 };

function Legend({ label, ramp }: { label: string; ramp: Ramp }) {
  return (
    <div className="pointer-events-auto rounded-md bg-white/95 px-3 py-2 text-[11px] text-stone-600 shadow">
      <p className="mb-1 font-medium text-stone-800">{label}</p>
      <div className="h-2 w-40 rounded-full" style={{ background: gradientCss(ramp) }} />
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
  const [allSites, setAllSites] = useState<SitesGeoJSON | null>(null);
  const [viewKey, setViewKey] = useState("investor");
  const [weightsByView, setWeightsByView] = useState<Record<string, Weights>>({});
  const [showWeights, setShowWeights] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SiteDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load metadata and every site once; filtering and scoring happen here so
  // view switches and weight changes re-rank instantly.
  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setMeta(m);
        setWeightsByView(Object.fromEntries(m.views.map((v) => [v.key, { ...v.weights }])));
      })
      .catch((e) => setError(String(e)));
    fetchSites(INITIAL_FILTERS)
      // Draw order: higher investor scores last, so they sit on top.
      .then((d) => setAllSites({ ...d, features: [...d.features].sort((a, b) => (a.properties.score ?? -1) - (b.properties.score ?? -1)) }))
      .catch((e) => setError(String(e)));
  }, []);

  const view = meta?.views.find((v) => v.key === viewKey) ?? null;
  const weights = weightsByView[viewKey];
  const ramp = rampFor(viewKey);

  // Live score + rank for every site under the current view and weights.
  const live = useMemo(() => {
    if (!allSites || !view || !weights) return null;
    return rescore(allSites.features.map((f) => f.properties), weights, view.invert);
  }, [allSites, view, weights]);

  // Sites that share exact coordinates, so the panel can offer the others.
  const colocated = useMemo(() => {
    const byPoint = new Map<string, { site_id: string; name: string }[]>();
    for (const f of allSites?.features ?? []) {
      const k = f.geometry.coordinates.join(",");
      byPoint.set(k, [...(byPoint.get(k) ?? []), { site_id: f.properties.site_id, name: f.properties.name }]);
    }
    const out = new Map<string, { site_id: string; name: string }[]>();
    for (const group of byPoint.values())
      if (group.length > 1) for (const s of group) out.set(s.site_id, group.filter((o) => o.site_id !== s.site_id));
    return out;
  }, [allSites]);

  const rankOf = useMemo(() => (live ? [...live.values()].filter((v) => v.score != null).length : 0), [live]);

  // Which sites pass the filters (min score uses the live score).
  const visible = useMemo<Set<string> | null>(() => {
    if (!allSites || !live) return null;
    const ids = new Set<string>();
    for (const { properties: p } of allSites.features) {
      if (filters.licenceAreas.length && !filters.licenceAreas.includes(p.licence_area)) continue;
      if (filters.voltages.length && !filters.voltages.includes(p.voltage)) continue;
      if (filters.minScore > 0) {
        const s = live.get(p.site_id)?.score;
        if (s == null || s < filters.minScore) continue;
      }
      ids.add(p.site_id);
    }
    return ids;
  }, [allSites, live, filters]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let alive = true;
    setDetailLoading(true);
    fetchSite(selectedId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(String(e)))
      .finally(() => alive && setDetailLoading(false));
    return () => {
      alive = false;
    };
  }, [selectedId]);

  return (
    <div className="flex h-full flex-col bg-stone-50 text-stone-900">
      <header className="z-20 flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-stone-200 bg-white px-4 py-2.5">
        <div>
          <h1 className="text-sm font-semibold">Grid Intelligence</h1>
          <p className="text-[11px] text-stone-500">UK Power Networks primary substations</p>
        </div>
        {meta && (
          <div className="flex items-center gap-2">
            <ViewToggle views={meta.views} value={viewKey} onChange={setViewKey} />
            <button
              type="button"
              aria-expanded={showWeights}
              onClick={() => setShowWeights((s) => !s)}
              className={`whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium ${
                showWeights ? "border-stone-900 bg-stone-900 text-white" : "border-stone-300 bg-white text-stone-700 hover:border-stone-500"
              }`}
            >
              Weights
            </button>
          </div>
        )}
        <FilterBar meta={meta} filters={filters} onChange={setFilters} shown={visible?.size ?? null} />
      </header>

      <main className="relative flex-1">
        <MapView sites={allSites} live={live} visible={visible} ramp={ramp} selectedId={selectedId} onSelect={setSelectedId} />
        {view && (
          <div className="pointer-events-none absolute left-3 top-3 sm:bottom-8 sm:top-auto">
            <Legend label={view.score_label} ramp={ramp} />
          </div>
        )}
        {showWeights && view && meta && weights && (
          <div className="pointer-events-none absolute left-3 top-3 z-10">
            <WeightsPanel
              view={view}
              signals={meta.signals}
              weights={weights}
              onChange={(w) => setWeightsByView((all) => ({ ...all, [viewKey]: w }))}
              onClose={() => setShowWeights(false)}
            />
          </div>
        )}
        {error && !selectedId && (
          <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-800 shadow">
            {error}. Is the API running?
          </div>
        )}
        {selectedId && view && weights && (
          <div className="absolute inset-y-0 right-0 z-10 w-full sm:w-auto">
            <SidePanel
              site={detail}
              view={view}
              weights={weights}
              live={live?.get(selectedId) ?? null}
              rankOf={rankOf}
              colocated={(colocated.get(selectedId) ?? []).map((o) => ({ ...o, score: live?.get(o.site_id)?.score ?? null }))}
              onSelect={setSelectedId}
              ramp={ramp}
              loading={detailLoading}
              error={error}
              onClose={() => setSelectedId(null)}
            />
          </div>
        )}
      </main>
    </div>
  );
}
