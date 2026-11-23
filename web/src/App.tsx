import { useEffect, useMemo, useState } from "react";
import { fetchMeta, fetchSite, fetchSites, type Filters, type Meta, type QueryResult, type SiteDetail, type SiteProps, type SitesGeoJSON } from "./api";
import AskPanel from "./AskPanel";
import { gradientCss, rampFor, scoreColor, UNSCORED, type Ramp } from "./colors";
import { LoadInput, Segmented, WeightsPanel } from "./Controls";
import FilterBar from "./FilterBar";
import Footer from "./Footer";
import MapView, { type Display } from "./MapView";
import RankList from "./RankList";
import { colourPosition, describe, rankByScore, rankByStuck, rankForLoad, type Mode, type Ranking } from "./ranking";
import type { Weights } from "./scoring";
import SidePanel, { type Headline } from "./SidePanel";

const INITIAL_FILTERS: Filters = { licenceAreas: [], voltages: [], minScore: 0 };
type Panel = "none" | "ranking" | "weights" | "ask";

const mw = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 });

function Legend({ label, ramp, left, mid, right, grey }: { label: string; ramp: Ramp; left: string; mid?: string; right: string; grey?: string }) {
  return (
    <div className="pointer-events-auto rounded-md bg-white/95 px-3 py-2 text-[11px] text-stone-600 shadow">
      <p className="mb-1 font-medium text-stone-800">{label}</p>
      <div className="h-2 w-44 rounded-full" style={{ background: gradientCss(ramp) }} />
      <div className="mt-0.5 flex w-44 justify-between tabular-nums">
        <span>{left}</span>
        {mid && <span>{mid}</span>}
        <span>{right}</span>
      </div>
      {grey && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: UNSCORED }} />
          {grey}
        </div>
      )}
    </div>
  );
}

function ToolbarButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-expanded={active}
      onClick={onClick}
      className={`whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium ${
        active ? "border-stone-900 bg-stone-900 text-white" : "border-stone-300 bg-white text-stone-700 hover:border-stone-500"
      }`}
    >
      {children}
    </button>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [allSites, setAllSites] = useState<SitesGeoJSON | null>(null);
  const [filters, setFilters] = useState<Filters>(INITIAL_FILTERS);
  const [viewKey, setViewKey] = useState<"investor" | "developer">("investor");
  const [investorSort, setInvestorSort] = useState<"score" | "stuck">("score");
  const [weights, setWeights] = useState<Weights | null>(null);
  const [loadMw, setLoadMw] = useState(50);
  const [panel, setPanel] = useState<Panel>(() => (window.innerWidth >= 900 ? "ranking" : "none"));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SiteDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false); // phones only; always shown from sm up
  const [askResult, setAskResult] = useState<QueryResult | null>(null);
  const askIds = useMemo(() => askResult?.sites.map((s) => s.site_id) ?? [], [askResult]);

  // Load metadata and every site once; ranking and filtering happen here so
  // every control re-ranks instantly.
  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setMeta(m);
        const inv = m.views.find((v) => v.type === "weighted");
        const dev = m.views.find((v) => v.type === "filter_rank");
        if (inv?.weights) setWeights({ ...inv.weights });
        if (dev?.load_mw_default != null) setLoadMw(dev.load_mw_default);
      })
      .catch((e) => setError(String(e)));
    fetchSites(INITIAL_FILTERS)
      // Draw order: higher investor scores last, so they sit on top.
      .then((d) => setAllSites({ ...d, features: [...d.features].sort((a, b) => (a.properties.score ?? -1) - (b.properties.score ?? -1)) }))
      .catch((e) => setError(String(e)));
  }, []);

  const investor = meta?.views.find((v) => v.type === "weighted") ?? null;
  const developer = meta?.views.find((v) => v.type === "filter_rank") ?? null;
  const mode: Mode = viewKey === "developer" ? "developer" : investorSort === "stuck" ? "stuck" : "score";
  const ramp = rampFor(viewKey);

  const props = useMemo(() => allSites?.features.map((f) => f.properties) ?? [], [allSites]);
  const byId = useMemo(() => new Map<string, SiteProps>(props.map((p) => [p.site_id, p])), [props]);

  // Investor score is always computed: it's shown as context in every mode.
  const scoreRanking = useMemo(() => (weights ? rankByScore(props, weights) : null), [props, weights]);
  const stuckRanking = useMemo(() => rankByStuck(props), [props]);
  const loadRanking = useMemo(() => rankForLoad(props, loadMw), [props, loadMw]);
  const ranking: Ranking | null = mode === "score" ? scoreRanking : mode === "stuck" ? stuckRanking : loadRanking;

  const display = useMemo<Display | null>(() => {
    if (!ranking) return null;
    const out: Display = new Map();
    for (const p of props) {
      const e = ranking.entries.get(p.site_id);
      out.set(p.site_id, {
        color: e ? scoreColor(colourPosition(ranking, e), ramp) : UNSCORED,
        tip: describe(ranking, e),
        rank: e?.rank ?? null,
      });
    }
    return out;
  }, [props, ranking, ramp]);

  const visible = useMemo<Set<string> | null>(() => {
    if (!ranking) return null;
    const ids = new Set<string>();
    for (const p of props) {
      if (filters.licenceAreas.length && !filters.licenceAreas.includes(p.licence_area)) continue;
      if (filters.voltages.length && !filters.voltages.includes(p.voltage)) continue;
      const e = ranking.entries.get(p.site_id);
      if (mode === "developer" && !e) continue; // the shortlist only
      if (mode === "score" && filters.minScore > 0 && (!e || e.value < filters.minScore)) continue;
      ids.add(p.site_id);
    }
    return ids;
  }, [props, ranking, filters, mode]);

  // Sites that share exact coordinates, so the panel can offer the others.
  const colocated = useMemo(() => {
    const byPoint = new Map<string, string[]>();
    for (const f of allSites?.features ?? []) {
      const k = f.geometry.coordinates.join(",");
      byPoint.set(k, [...(byPoint.get(k) ?? []), f.properties.site_id]);
    }
    const out = new Map<string, string[]>();
    for (const g of byPoint.values()) if (g.length > 1) for (const id of g) out.set(id, g.filter((o) => o !== id));
    return out;
  }, [allSites]);

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

  const headline = useMemo<Headline | null>(() => {
    const p = selectedId ? byId.get(selectedId) : undefined;
    if (!p || !ranking || !investor) return null;
    const e = ranking.entries.get(p.site_id);
    const color = e ? scoreColor(colourPosition(ranking, e), ramp) : UNSCORED;
    const sc = scoreRanking?.entries.get(p.site_id);
    const st = stuckRanking.entries.get(p.site_id);
    const scoreText = sc ? `${investor.score_label} ${sc.value.toFixed(1)} (rank ${sc.rank} of ${scoreRanking!.n})` : undefined;
    const stuckSignal = detail?.site_id === p.site_id ? detail.signals.find((s) => s.key === "stuck_mw") : undefined;
    const stuckSources = stuckSignal ? [stuckSignal.source, ...stuckSignal.extra_sources].filter((x) => x != null) : undefined;

    if (mode === "score") {
      return {
        big: sc ? sc.value.toFixed(1) : "—",
        color,
        label: investor.score_label ?? investor.label,
        sub: sc ? `Rank ${sc.rank} of ${scoreRanking!.n} UKPN primaries` : "No score",
        secondary: st ? `Stuck demand ${mw(st.value)} MW (rank ${st.rank} of ${stuckRanking.n})` : "No stuck demand",
      };
    }
    if (mode === "stuck") {
      return {
        big: mw(p.stuck_mw),
        color,
        label: "MW of stuck demand",
        sub: st ? `Rank ${st.rank} of ${stuckRanking.n} sites with stuck demand` : "No stuck demand: queue is within published headroom",
        detail: `Queue ${mw(p.queue_mw)} MW − published headroom ${mw(p.demand_headroom_mw)} MW, floored at 0`,
        secondary: scoreText,
        sources: stuckSources,
      };
    }
    const devSources = detail?.site_id === p.site_id ? detail.developer.sources : undefined;
    return {
      big: mw(p.headroom_after_queue_mw),
      color,
      label: "MW of published headroom left after the queue",
      sub: e
        ? `Rank ${e.rank} of ${loadRanking.n} sites with ≥ ${loadMw} MW published headroom`
        : `Not on the shortlist: ${mw(p.demand_headroom_mw)} MW published headroom is below ${loadMw} MW`,
      detail: `Published headroom ${mw(p.demand_headroom_mw)} MW − queue ahead ${mw(p.queue_mw)} MW`,
      secondary: scoreText,
      sources: devSources,
    };
  }, [selectedId, byId, ranking, ramp, investor, scoreRanking, stuckRanking, loadRanking, loadMw, mode, detail]);

  const legend =
    mode === "score"
      ? { label: investor?.score_label ?? "Score", left: "0", mid: "50", right: "100", grey: "Not scored" }
      : mode === "stuck"
        ? { label: `Stuck demand rank (${stuckRanking.n} sites)`, left: `#${stuckRanking.n}`, right: "#1", grey: "No stuck demand" }
        : { label: `Rank by MW left after queue (${loadRanking.n} sites)`, left: `#${loadRanking.n}`, right: "#1" };

  const listTitle =
    mode === "score" ? (investor?.score_label ?? "Ranking") : mode === "stuck" ? "Most stuck MW" : `Shortlist for a ${loadMw} MW load`;
  const listSubtitle =
    mode === "score"
      ? "Weighted score, 0–100. Change the weights to re-rank."
      : mode === "stuck"
        ? "Queued demand beyond published headroom, largest first. Sites with none are not ranked."
        : `Sites with at least ${loadMw} MW of published headroom, ranked by headroom left after the queue ahead.`;

  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? "none" : p));

  return (
    <div className="flex h-full flex-col bg-stone-50 text-stone-900">
      <header className="z-20 flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-stone-200 bg-white px-4 py-2.5">
        <div>
          <h1 className="text-sm font-semibold">Grid Intelligence</h1>
          <p className="text-[11px] text-stone-500">UK Power Networks primary substations</p>
        </div>
        {meta && investor && developer && (
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="View"
              value={viewKey}
              onChange={(v) => setViewKey(v as "investor" | "developer")}
              options={[investor, developer].map((v) => ({ key: v.key, label: v.label, title: v.description }))}
            />
            {viewKey === "investor" && (
              <Segmented
                label="Rank by"
                value={investorSort}
                onChange={(v) => {
                  setInvestorSort(v as "score" | "stuck");
                  if (v === "stuck" && panel === "weights") setPanel("ranking");
                }}
                options={[
                  { key: "score", label: "Score" },
                  { key: "stuck", label: "Most stuck MW", title: "Queued demand beyond published headroom" },
                ]}
              />
            )}
            {viewKey === "developer" && <LoadInput value={loadMw} onChange={setLoadMw} />}
            <span className="sm:hidden">
              <ToolbarButton active={showFilters} onClick={() => setShowFilters((v) => !v)}>
                Filters
              </ToolbarButton>
            </span>
            <ToolbarButton active={panel === "ask"} onClick={() => togglePanel("ask")}>
              Ask
            </ToolbarButton>
            <ToolbarButton active={panel === "ranking"} onClick={() => togglePanel("ranking")}>
              Ranking
            </ToolbarButton>
            {mode === "score" && (
              <ToolbarButton active={panel === "weights"} onClick={() => togglePanel("weights")}>
                Weights
              </ToolbarButton>
            )}
          </div>
        )}
        <div className={`${showFilters ? "flex" : "hidden"} w-full sm:flex sm:w-auto`}>
          <FilterBar meta={meta} filters={filters} onChange={setFilters} shown={visible?.size ?? null} showMinScore={mode === "score"} />
        </div>
      </header>

      <main className="relative flex-1 overflow-hidden">
        <MapView
          sites={allSites}
          display={display}
          visible={visible}
          selectedId={selectedId}
          highlightIds={panel === "ask" ? askIds : []}
          onSelect={setSelectedId}
        />

        <div className="pointer-events-none absolute bottom-8 left-3 hidden sm:block">
          <Legend ramp={ramp} {...legend} />
        </div>

        {panel === "ranking" && ranking && visible && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36">
            <RankList
              key={mode}
              title={listTitle}
              subtitle={listSubtitle}
              ranking={ranking}
              sites={byId}
              visible={visible}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onClose={() => setPanel("none")}
            />
          </div>
        )}
        {panel === "ask" && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36">
            <AskPanel
              result={askResult}
              onResult={setAskResult}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onClose={() => setPanel("none")}
            />
          </div>
        )}
        {panel === "weights" && mode === "score" && investor && weights && meta && (
          <div className="pointer-events-none absolute left-3 top-3 z-10">
            <WeightsPanel view={investor} signals={meta.signals} weights={weights} onChange={setWeights} onClose={() => setPanel("none")} />
          </div>
        )}

        {error && !selectedId && (
          <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-800 shadow">
            {error}. Is the API running?
          </div>
        )}
        {selectedId && (
          <div className="absolute inset-y-0 right-0 z-10 w-full sm:w-auto">
            <SidePanel
              site={detail}
              headline={headline}
              weights={mode === "score" ? weights : null}
              colocated={(colocated.get(selectedId) ?? []).map((id) => ({
                site_id: id,
                name: byId.get(id)?.name ?? id,
                tip: display?.get(id)?.tip ?? "",
                color: display?.get(id)?.color ?? UNSCORED,
              }))}
              onSelect={setSelectedId}
              loading={detailLoading}
              error={error}
              onClose={() => setSelectedId(null)}
            />
          </div>
        )}
      </main>
      <Footer meta={meta} />
    </div>
  );
}
