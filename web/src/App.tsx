import { useEffect, useMemo, useState } from "react";
import { monthLabel, networkNames, upperLevel, fetchBsps, fetchGsps, fetchMeta, fetchNetwork, fetchOperators, fetchSite, fetchSites, fetchStory, type OperatorRow, type BspRow, type GspRow, type StoryChapter, type Filters, type Meta, type QueryResult, type SiteDetail, type SiteProps, type SitesGeoJSON, type Source } from "./api";
import AskPanel from "./AskPanel";
import { gradientCss, rampFor, scoreColor, UNSCORED, type Ramp } from "./colors";
import { LoadInput, Segmented, WeightsPanel } from "./Controls";
import FilterBar from "./FilterBar";
import Footer from "./Footer";
import MapView, { type Display } from "./MapView";
import RankList from "./RankList";
import BspList from "./BspList";
import GspCard from "./GspCard";
import StoryPanel from "./StoryPanel";
import NodeCard from "./NodeCard";
import OperatorList from "./OperatorList";
import { colourPosition, describe, rankByScore, rankBySiteBsp, rankByStuck, rankForLoad, type Mode, type Ranking } from "./ranking";
import type { Weights } from "./scoring";
import SidePanel, { type Headline } from "./SidePanel";

const INITIAL_FILTERS: Filters = { licenceAreas: [], voltages: [], minScore: 0 };
type Panel = "none" | "ranking" | "weights" | "ask" | "story" | "operators";

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
  const [investorSort, setInvestorSort] = useState<"score" | "stuck" | "bsp">("score");
  const [upstreamOn, setUpstreamOn] = useState(true); // developer view: count BSP limits
  const [bsps, setBsps] = useState<BspRow[]>([]);
  const [weights, setWeights] = useState<Weights | null>(null);
  const [loadMw, setLoadMw] = useState(50);
  const [panel, setPanel] = useState<Panel>(() => (window.innerWidth >= 900 ? "ranking" : "none"));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SiteDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false); // phones only; always shown from sm up
  // Phase 10: network view and story
  const [showNetwork, setShowNetwork] = useState(false);
  const [networks, setNetworks] = useState<Record<string, GeoJSON.FeatureCollection>>({});
  const [bspSources, setBspSources] = useState<Record<string, Source | null>>({});
  const [selectedNode, setSelectedNode] = useState<string | null>(null); // upper-level node with no site (Spain)
  const [gspRows, setGspRows] = useState<GspRow[]>([]);
  const [selectedGsp, setSelectedGsp] = useState<string | null>(null);
  // Phase 13: one country at a time (GB, ES); everything is ranked within the country shown.
  const [country, setCountry] = useState("GB");
  const [stories, setStories] = useState<Record<string, StoryChapter[]>>({});
  const story = stories[country] ?? null;
  const [operators, setOperators] = useState<Record<string, { rows: OperatorRow[]; source: Source | null; note: string }>>({});
  const [operatorsError, setOperatorsError] = useState<string | null>(null);
  const [selectedOperator, setSelectedOperator] = useState<string | null>(null);
  const [storyIndex, setStoryIndex] = useState(0);
  const [storyError, setStoryError] = useState<string | null>(null);
  const [storyHighlight, setStoryHighlight] = useState<string[]>([]);
  const [flyTo, setFlyTo] = useState<{ center: [number, number]; zoom: number; key: number } | null>(null);
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
    fetchBsps()
      .then((d) => {
        setBsps(d.bsps);
        setBspSources(d.sources ?? {});
      })
      .catch((e) => setError(String(e)));
    fetchSites(INITIAL_FILTERS)
      // Draw order: higher investor scores last, so they sit on top.
      .then((d) => setAllSites({ ...d, features: [...d.features].sort((a, b) => (a.properties.score ?? -1) - (b.properties.score ?? -1)) }))
      .catch((e) => setError(String(e)));
  }, []);

  const investor = meta?.views.find((v) => v.type === "weighted") ?? null;
  const developer = meta?.views.find((v) => v.type === "filter_rank") ?? null;
  const mode: Mode = viewKey === "developer" ? "developer" : investorSort;
  const ramp = rampFor(viewKey);

  const countryInfo = meta?.countries?.find((c) => c.code === country) ?? null;
  const hasTopology = countryInfo?.has_topology ?? true;
  const countryDnos = useMemo(() => (meta?.dnos ?? []).filter((d) => (d.country ?? "GB") === country), [meta, country]);
  const siteWord = countryInfo?.has_gsp === false ? "busbars" : "primaries";
  const level = upperLevel(countryInfo); // "BSP" or "transmission node"
  const Level = level === "BSP" ? "BSP" : "Transmission node";
  const levels = level === "BSP" ? "BSPs" : "transmission nodes";
  const networkData = networks[country] ?? null;
  // Only the country shown takes part in rankings, colours and lists.
  const props = useMemo(
    () => allSites?.features.map((f) => f.properties).filter((p) => (p.country ?? "GB") === country) ?? [],
    [allSites, country],
  );
  const hasOperators = useMemo(() => new Set(props.map((p) => p.operator)).size > 1, [props]);
  const operatorIds = useMemo(
    () => (selectedOperator ? props.filter((p) => p.operator === selectedOperator).map((p) => p.site_id) : []),
    [props, selectedOperator],
  );

  const switchCountry = (code: string) => {
    if (code === country) return;
    const c = meta?.countries?.find((x) => x.code === code);
    setCountry(code);
    setFilters(INITIAL_FILTERS);
    setSelectedId(null);
    setSelectedGsp(null);
    setSelectedNode(null);
    setSelectedOperator(null);
    setStoryIndex(0);
    setStoryHighlight([]);
    if (c && !c.has_topology) {
      setShowNetwork(false);
      if (investorSort === "bsp") setInvestorSort("score");
    }
    if (panel === "operators" && code === "GB") setPanel("ranking");
    if (c) setFlyTo({ center: c.map_center, zoom: c.map_zoom, key: Date.now() });
  };
  const byId = useMemo(() => new Map<string, SiteProps>(props.map((p) => [p.site_id, p])), [props]);

  // Investor score is always computed: it's shown as context in every mode.
  const scoreRanking = useMemo(() => (weights ? rankByScore(props, weights) : null), [props, weights]);
  const stuckRanking = useMemo(() => rankByStuck(props), [props]);
  const loadRanking = useMemo(() => rankForLoad(props, loadMw, upstreamOn, level), [props, loadMw, upstreamOn, level]);
  const bspRanking = useMemo(() => rankBySiteBsp(props, bsps, level), [props, bsps, level]);
  const ranking: Ranking | null =
    mode === "score" ? scoreRanking : mode === "stuck" ? stuckRanking : mode === "bsp" ? bspRanking : loadRanking;
  const selectedBspId = selectedId ? (byId.get(selectedId)?.bsp_id ?? null) : null;

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

  // Load the network (and GSP marts) the first time it's needed.
  useEffect(() => {
    if (!(showNetwork || selectedGsp) || networkData) return;
    fetchNetwork(country).then((d) => setNetworks((n) => ({ ...n, [country]: d }))).catch((e) => setError(String(e)));
    fetchGsps().then((d) => setGspRows(d.gsps)).catch((e) => setError(String(e)));
  }, [showNetwork, selectedGsp, networkData, country]);

  // Load a country's story when its panel first opens.
  useEffect(() => {
    if (panel !== "story" || story) return;
    setStoryError(null);
    fetchStory(country)
      .then((d) => setStories((s) => ({ ...s, [country]: d.chapters })))
      .catch((e) => setStoryError(String(e)));
  }, [panel, story, country]);

  // Load a country's distributors when that panel first opens.
  useEffect(() => {
    if (panel !== "operators" || operators[country]) return;
    setOperatorsError(null);
    fetchOperators(country)
      .then((d) => setOperators((o) => ({ ...o, [country]: { rows: d.operators, source: Object.values(d.sources)[0] ?? null, note: d.note } })))
      .catch((e) => setOperatorsError(String(e)));
  }, [panel, operators, country]);

  // Apply a chapter's focus: view, ranking, network, selection, rings, camera.
  useEffect(() => {
    const c = panel === "story" ? story?.[storyIndex] : undefined;
    if (!c) return;
    const f = c.focus;
    setViewKey(f.view);
    if (f.sort) setInvestorSort(f.sort);
    setShowNetwork(f.network);
    setSelectedGsp(null);
    setSelectedId(f.select ?? null);
    setStoryHighlight(f.highlight ?? []);
    setFilters({ ...INITIAL_FILTERS, licenceAreas: f.areas ?? [] });
    setFlyTo({ center: f.center, zoom: f.zoom, key: Date.now() });
  }, [panel, story, storyIndex]);

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
        sub: sc ? `Rank ${sc.rank} of ${scoreRanking!.n} ${siteWord} in ${countryInfo?.name ?? "this country"}` : "No score",
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
    const up = detail?.site_id === p.site_id ? detail.upstream : undefined;
    if (mode === "bsp") {
      const b = up?.bsp;
      return {
        big: e ? mw(e.value) : b ? "0.0" : "—",
        color,
        label: b ? `MW stuck at its ${level}, ${b.name}` : `MW stuck at its ${level}`,
        sub: e
          ? `${Level} rank ${e.rank} of ${bspRanking.n} ${levels} with stuck demand`
          : p.bsp_id ? `Its ${level} has no stuck demand, or its headroom isn't published`
          : level === "BSP" ? "Fed directly from its GSP (no BSP)" : "No transmission node published for this busbar",
        detail: b && b.headroom_mw != null
          ? `Queue under the ${level} ${mw(b.queue_mw)} MW (${b.site_count} sites) − its published headroom ${mw(b.headroom_mw)} MW, floored at 0`
          : undefined,
        secondary: scoreText,
        sources: b?.sources,
      };
    }
    const devSources = detail?.site_id === p.site_id ? detail.developer.sources : undefined;
    const value = upstreamOn ? p.effective_headroom_mw : p.headroom_after_queue_mw;
    const bspPart = upstreamOn && up?.bsp?.headroom_after_queue_mw != null
      ? `; ${Level} ${up.bsp.name}: ${mw(up.bsp.headroom_after_queue_mw)} MW left after its queue. The lower counts${p.limiting_level === "bsp" ? ` (the ${level})` : " (this site)"}`
      : "";
    return {
      big: mw(value),
      color,
      label: upstreamOn ? `MW of published headroom left after the queue, counting its ${level}` : "MW of published headroom left after the queue",
      sub: e
        ? `Rank ${e.rank} of ${loadRanking.n} sites with ≥ ${loadMw} MW published headroom`
        : `Not on the shortlist: ${mw(p.demand_headroom_mw)} MW published headroom is below ${loadMw} MW`,
      detail: `This site: published headroom ${mw(p.demand_headroom_mw)} MW − queue ahead ${mw(p.queue_mw)} MW${bspPart}`,
      secondary: scoreText,
      sources: devSources,
    };
  }, [selectedId, byId, ranking, ramp, investor, scoreRanking, stuckRanking, loadRanking, bspRanking, loadMw, upstreamOn, mode, detail, siteWord, countryInfo, level, Level, levels]);

  // The selected site's upstream path, drawn on the map.
  const topology = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!detail || detail.site_id !== selectedId) return null;
    const here: [number, number] = [detail.lon, detail.lat];
    const b = detail.upstream.bsp;
    const g = detail.upstream.gsp;
    const bspPt = b && b.lat != null && b.lon != null ? ([b.lon, b.lat] as [number, number]) : null;
    const gspPt = g && g.lat != null && g.lon != null ? ([g.lon, g.lat] as [number, number]) : null;
    const line = (a: [number, number], z: [number, number], kind: string): GeoJSON.Feature => ({
      type: "Feature", properties: { kind }, geometry: { type: "LineString", coordinates: [a, z] } });
    const point = (c: [number, number], kind: string): GeoJSON.Feature => ({
      type: "Feature", properties: { kind }, geometry: { type: "Point", coordinates: c } });
    const f: GeoJSON.Feature[] = [];
    if (bspPt) {
      if (!b?.is_this_site) f.push(line(here, bspPt, "path"));
      for (const x of detail.siblings) f.push(line([x.lon, x.lat], bspPt, "sibling"));
      if (gspPt) f.push(line(bspPt, gspPt, "path"));
      f.push(point(bspPt, "bsp"));
    } else if (gspPt) {
      f.push(line(here, gspPt, "path"));
    }
    if (gspPt) f.push(point(gspPt, "gsp"));
    return { type: "FeatureCollection", features: f };
  }, [detail, selectedId]);

  const legend =
    mode === "score"
      ? { label: investor?.score_label ?? "Score", left: "0", mid: "50", right: "100", grey: "Not scored" }
      : mode === "stuck"
        ? { label: `Stuck demand rank (${stuckRanking.n} sites)`, left: `#${stuckRanking.n}`, right: "#1", grey: "No stuck demand" }
        : mode === "bsp"
          ? { label: `${Level} stuck demand rank (${bspRanking.n} ${levels})`, left: `#${bspRanking.n}`, right: "#1", grey: `${Level} not stuck or not published` }
          : { label: `Rank by MW left after queue (${loadRanking.n} sites)`, left: `#${loadRanking.n}`, right: "#1" };

  const listTitle =
    mode === "score" ? (investor?.score_label ?? "Ranking") : mode === "stuck" ? "Most stuck MW" : `Shortlist for a ${loadMw} MW load`;
  const listSubtitle =
    mode === "score"
      ? "Weighted score, 0–100. Change the weights to re-rank."
      : mode === "stuck"
        ? "Queued demand beyond published headroom, largest first. Sites with none are not ranked."
        : `Sites with at least ${loadMw} MW of published headroom, ranked by headroom left after the queue ahead${
            upstreamOn ? (level === "BSP" ? ", counting the bulk supply point (BSP) above each site" : ", counting the transmission node above each busbar")
              : ` (${level} limits ignored)`}.`;

  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? "none" : p));

  return (
    <div className="flex h-full flex-col bg-stone-50 text-stone-900 print:block print:h-auto print:bg-white">
      <header className="z-20 flex print:hidden flex-wrap items-center gap-x-6 gap-y-2 border-b border-stone-200 bg-white px-4 py-2.5">
        <div>
          <h1 className="text-sm font-semibold">Grid Intelligence</h1>
          <p className="text-[11px] text-stone-500">
            {countryInfo?.has_gsp !== false
              ? `${networkNames(countryDnos, "Distribution network")} primary substations`
              : `${countryInfo?.name ?? ""}: distribution busbars, every distributor (CNMC${countryInfo?.data_period ? `, ${monthLabel(countryInfo.data_period)}` : ""})`}
          </p>
        </div>
        {meta && (meta.countries?.length ?? 0) > 1 && (
          <Segmented
            label="Country"
            value={country}
            onChange={switchCountry}
            options={meta.countries.map((c) => ({ key: c.code, label: c.name, title: `${c.site_count.toLocaleString("en-GB")} sites, ranked within ${c.name}` }))}
          />
        )}
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
                  setInvestorSort(v as "score" | "stuck" | "bsp");
                  if (v !== "score" && panel === "weights") setPanel("ranking");
                }}
                options={[
                  { key: "score", label: "Score" },
                  { key: "stuck", label: "Most stuck MW", title: "Queued demand beyond published headroom" },
                  ...(hasTopology ? [{ key: "bsp", label: level === "BSP" ? "BSPs" : "Transmission", title: `${Level}s by stuck MW` }] : []),
                ]}
              />
            )}
            {viewKey === "developer" && (
              <>
                <LoadInput value={loadMw} onChange={setLoadMw} />
                {hasTopology && <label className="flex items-center gap-1.5 text-xs text-stone-600" title={`Use the lower of the site's and its ${level}'s headroom after queue`}>
                  <input type="checkbox" checked={upstreamOn} onChange={(e) => setUpstreamOn(e.target.checked)} className="accent-stone-900" />
                  Count {level} limits
                </label>}
              </>
            )}
            <span className="sm:hidden">
              <ToolbarButton active={showFilters} onClick={() => setShowFilters((v) => !v)}>
                Filters
              </ToolbarButton>
            </span>
            <ToolbarButton active={panel === "story"} onClick={() => togglePanel("story")}>
              Story
            </ToolbarButton>
            {hasTopology && (
              <ToolbarButton active={showNetwork} onClick={() => setShowNetwork((v) => !v)}>
                Network
              </ToolbarButton>
            )}
            {hasOperators && (
              <ToolbarButton active={panel === "operators"} onClick={() => togglePanel("operators")}>
                Distributors
              </ToolbarButton>
            )}
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
          <FilterBar meta={meta} country={countryInfo} dnos={countryDnos} filters={filters} onChange={setFilters} shown={visible?.size ?? null} showMinScore={mode === "score"} />
        </div>
      </header>

      <main className="relative flex-1 overflow-hidden print:overflow-visible">
        <div className="contents print:hidden">
        <MapView
          sites={allSites}
          display={display}
          visible={visible}
          selectedId={selectedId}
          highlightIds={panel === "ask" ? askIds : panel === "story" ? storyHighlight : panel === "operators" ? operatorIds : []}
          topology={topology}
          network={showNetwork ? networkData : null}
          flyTo={flyTo}
          onSelectGsp={(g) => {
            setSelectedId(null);
            setSelectedNode(null);
            setSelectedGsp(g);
          }}
          onSelectNode={(id) => {
            setSelectedId(null);
            setSelectedGsp(null);
            setSelectedNode(id);
          }}
          onSelect={setSelectedId}
          dnos={countryDnos}
        />
        </div>

        <div className="pointer-events-none absolute bottom-8 left-3 hidden sm:block print:hidden">
          <Legend ramp={ramp} {...legend} />
        </div>

        {panel === "ranking" && mode === "bsp" && visible && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36 print:hidden">
            <BspList
              bsps={bsps}
              level={level}
              visibleSites={visible}
              selectedBspId={selectedBspId}
              // Select the BSP's own board if it is a site; otherwise open the node's card.
              onSelect={(b) => {
                if (b.site_id) setSelectedId(b.site_id);
                else {
                  setSelectedId(null);
                  setSelectedNode(b.bsp_id);
                  if (b.lat != null && b.lon != null) setFlyTo({ center: [b.lon, b.lat], zoom: 9, key: Date.now() });
                }
              }}
              onClose={() => setPanel("none")}
            />
          </div>
        )}
        {panel === "ranking" && mode !== "bsp" && ranking && visible && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36 print:hidden">
            <RankList
              exportContext={[
                `Grid Intelligence export, ${new Date().toISOString().slice(0, 10)}`,
                `${listTitle}: ${listSubtitle}`,
                ...(mode === "score" && weights
                  ? [`Weights: ${Object.entries(weights).map(([k, w]) => `${k} ${w}`).join(", ")}`]
                  : []),
                ...(mode === "developer" ? [`Load size ${loadMw} MW; ${level} limits ${upstreamOn ? "counted" : "ignored"}`] : []),
                `Filters: areas ${filters.licenceAreas.join("/") || "all"}; voltages ${filters.voltages.join("/") || "all"}`,
                `Sources: ${[...new Map((meta?.sources ?? []).map((s) => [s.dataset_id, `${s.dataset_id} (${s.publish_date}, ${s.licence})`])).values()].join("; ")}`,
                meta?.disclaimer ?? "Published headroom is indicative and not guaranteed.",
                `Not a connection offer. Ranks are within ${countryInfo?.name ?? "the country shown"}; filters only hide rows.`,
              ]}
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
        {panel === "story" && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36 print:hidden">
            <StoryPanel chapters={story} index={storyIndex} onIndex={setStoryIndex} error={storyError} onClose={() => setPanel("none")} />
          </div>
        )}
        {panel === "operators" && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36 print:hidden">
            <OperatorList
              operators={operators[country]?.rows ?? null}
              source={operators[country]?.source ?? null}
              note={operators[country]?.note ?? ""}
              period={monthLabel(countryInfo?.data_period) || "latest"}
              selectedOperator={selectedOperator}
              error={operatorsError}
              onSelect={(o) => {
                setSelectedOperator(o.operator);
                setSelectedId(o.top_site_id);
                const f = allSites?.features.filter((x) => x.properties.operator === o.operator) ?? [];
                if (f.length) {
                  const lons = f.map((x) => x.geometry.coordinates[0]);
                  const lats = f.map((x) => x.geometry.coordinates[1]);
                  const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats));
                  const zoom = span > 6 ? 5.3 : span > 2 ? 6.5 : span > 0.5 ? 8 : 9.5;
                  setFlyTo({ center: [(Math.max(...lons) + Math.min(...lons)) / 2, (Math.max(...lats) + Math.min(...lats)) / 2], zoom, key: Date.now() });
                }
              }}
              onClose={() => setPanel("none")}
            />
          </div>
        )}
        {panel === "ask" && (
          <div className="pointer-events-none absolute bottom-3 left-3 top-3 z-10 flex sm:bottom-36 print:hidden">
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
          <div className="pointer-events-none absolute left-3 top-3 z-10 print:hidden">
            <WeightsPanel view={investor} signals={meta.signals} weights={weights} onChange={setWeights} onClose={() => setPanel("none")} />
          </div>
        )}

        {error && !selectedId && (
          <div className="absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-800 shadow">
            {error}. Is the API running?
          </div>
        )}
        {!selectedId && selectedGsp && gspRows.find((g) => g.gsp === selectedGsp) && (
          <div className="absolute inset-x-0 bottom-0 z-10 h-[58%] sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:h-auto sm:w-auto print:static print:h-auto">
            <GspCard gsp={gspRows.find((g) => g.gsp === selectedGsp)!} onClose={() => setSelectedGsp(null)} />
          </div>
        )}
        {!selectedId && !selectedGsp && selectedNode && bsps.find((b) => b.bsp_id === selectedNode) && (() => {
          const node = bsps.find((b) => b.bsp_id === selectedNode)!;
          const src = [node.headroom_source ? { ...(bspSources[node.dno] ?? { url: "", publish_date: "" }), dataset_id: node.headroom_source } : null,
            ...(meta?.sources ?? []).filter((s) => s.dno === node.dno && (s.field === "queue_mw" || s.field === "topology"))]
            .filter((x): x is Source => x != null && !!x.url);
          return (
            <div className="absolute inset-x-0 bottom-0 z-10 h-[58%] sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:h-auto sm:w-auto print:static print:h-auto">
              <NodeCard
                node={node}
                level={level}
                sites={props.filter((p) => p.bsp_id === node.bsp_id)}
                sources={[...new Map(src.map((s) => [s.dataset_id, s])).values()]}
                onSelect={(id) => {
                  setSelectedNode(null);
                  setSelectedId(id);
                }}
                onClose={() => setSelectedNode(null)}
              />
            </div>
          );
        })()}
        {selectedId && (
          <div className="absolute inset-x-0 bottom-0 z-10 h-[58%] sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:h-auto sm:w-auto print:static print:h-auto">
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
              dnos={countryDnos}
            />
          </div>
        )}
      </main>
      <Footer meta={meta} />
    </div>
  );
}
