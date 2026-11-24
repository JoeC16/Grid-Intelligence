// Typed client for the FastAPI backend (backend/main.py).

const BASE = import.meta.env.VITE_API_URL ?? "/api";

export interface Source {
  dataset_id: string;
  publish_date: string;
  url: string;
}

export interface SignalMeta {
  key: string;
  label: string;
  description: string;
  direction: "high" | "low";
}

export interface ViewMeta {
  key: string;
  type: "weighted" | "filter_rank";
  label: string;
  description: string;
  // weighted
  score_label?: string;
  weights?: Record<string, number>;
  // filter_rank
  load_mw_default?: number;
  filter_column?: string;
  rank_by?: string;
}

/** A network operator (DNO) covered by the data: names and attribution come from here, never hard-coded. */
export interface DnoInfo {
  code: string;
  name: string;
  region: string;
  licence_areas: string[];
  portal_name: string;
  portal_url: string;
  licence: string;
  licence_url: string;
  map_center: [number, number];
  map_zoom: number;
  site_count: number;
  country: string;
  publisher: string;
  has_topology: boolean;
  data_period: string | null;
  snapshot_date: string | null;
}

/** A country covered. Sites are scored and ranked within their country. */
export interface CountryInfo {
  code: string; // "GB" | "ES"
  name: string;
  dnos: string[];
  licence_areas: string[];
  voltages: number[];
  site_count: number;
  scored_count: number;
  map_center: [number, number];
  map_zoom: number;
  has_topology: boolean;
  has_gsp: boolean;
  upper_level: string; // "BSP" or "transmission node"
  data_period: string | null; // e.g. "2026-10" (Spain: the CNMC month)
}

/** "2026-10" -> "October 2026". */
export function monthLabel(period: string | null | undefined): string {
  if (!period) return "";
  const d = new Date(`${period}-01T00:00:00Z`);
  return isNaN(d.getTime()) ? period : d.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** "UK Power Networks", or "UK Power Networks and SP Energy Networks". */
export function networkNames(dnos: DnoInfo[] | undefined, fallback = "the network operators"): string {
  const names = (dnos ?? []).map((d) => d.name);
  if (!names.length) return fallback;
  return names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** "UK Power Networks (CC BY 4.0), CNMC (CC BY-SA 4.0)": who to credit, per DNO. */
export function dataCredit(dnos: DnoInfo[] | undefined): string {
  return (dnos ?? []).map((d) => `${d.publisher || d.name} (${d.licence})`).join(", ");
}

export interface Meta {
  disclaimer: string;
  licence_areas: string[];
  voltages: number[];
  site_count: number;
  scored_count: number;
  signals: SignalMeta[];
  views: ViewMeta[];
  headroom_2030_scenario: string;
  dnos: DnoInfo[];
  countries: CountryInfo[];
  sources: (Source & { dno: string; field: string; licence: string })[];
}

export interface SiteProps {
  site_id: string;
  dno: string;
  country: string;
  operator: string | null;
  name: string;
  licence_area: string;
  voltage: number;
  gsp: string | null;
  score: number | null;
  rank: number | null;
  developer_rank: number | null;
  developer_rank_local: number | null;
  effective_headroom_mw: number | null;
  limiting_level: string | null;
  bsp_id: string | null;
  queue_mw: number | null;
  demand_headroom_mw: number | null;
  headroom_after_queue_mw: number | null;
  stuck_mw: number | null;
  oversubscription: number | null;
  pct_stuck_mw: number | null;
  pct_oversubscription: number | null;
  pct_headroom_tightness: number | null;
  pct_utilisation: number | null;
  pct_recent_activity: number | null;
  pct_future_squeeze: number | null;
}

export interface SitesGeoJSON {
  type: "FeatureCollection";
  count: number;
  features: {
    type: "Feature";
    id: number;
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: SiteProps;
  }[];
}

export interface Signal {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  percentile: number | null;
  weight: number;
  source: Source | null;
  extra_sources: Source[];
  note: string | null;
}

export interface SiteDetail {
  site_id: string;
  dno: string;
  country: string | null;
  operator: string | null;
  operator_name: string | null;
  province: string | null;
  municipality: string | null;
  reserved: boolean;
  name: string;
  lat: number;
  lon: number;
  voltage: number;
  licence_area: string;
  gsp: string | null;
  score: number | null;
  rank: number | null;
  rank_of: number;
  queue: { queue_mw: number | null; source: Source | null; note: string | null };
  developer: { headroom_after_queue_mw: number | null; rank_at_default_load: number | null; sources: Source[] };
  scorable: boolean;
  exclude_reason: string | null;
  score_missing: string | null;
  signals: Signal[];
  capacity: { firm_capacity_mw: number | null; observed_peak_mw: number | null; capacity_taken_mw: number | null; source: Source | null };
  headroom_2030: { values: { scenario: string; value: number | null; default: boolean }[]; source: Source | null };
  location_source: Source | null;
  upstream: {
    headroom_after_queue_mw: number | null;
    effective_headroom_mw: number | null;
    limiting_level: string | null;
    upstream_constrained: boolean | null;
    gsp_over_capacity: boolean | null;
    bsp: {
      bsp_id: string; name: string; lat: number | null; lon: number | null; site_id: string | null;
      matched: boolean; note: string | null; site_count: number; headroom_mw: number | null; queue_mw: number;
      headroom_after_queue_mw: number | null; stuck_mw: number | null; is_this_site: boolean; sources: Source[];
      level?: "bsp" | "transmission"; cep_mw?: number | null; free_bays?: number | null;
    } | null;
    gsp: {
      name: string; lat: number | null; lon: number | null; import_capacity_utilisation_pct: number | null;
      technical_limits_agreed: boolean | null; source: Source | null;
    } | null;
  };
  siblings: { site_id: string; name: string; lat: number; lon: number; effective_headroom_mw: number | null; queue_mw: number | null }[];
  gsp_context: {
    name: string;
    site_count: number;
    queue_mw: number;
    primary_queue_mw: number;
    grid_level_queue_mw: number;
    large_demand_count: number;
    large_demand_mva: number;
    sources: { queue_mw: Source | null; large_demand: Source | null };
  } | null;
  disclaimer: string;
}

export interface Filters {
  licenceAreas: string[]; // empty = all
  voltages: number[]; // empty = all
  minScore: number;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return res.json() as Promise<T>;
}

// Start-up data published as static files on each deploy (backend/export_static.py), served
// from the CDN so the first screen doesn't wait for the API to start. Same JSON as the API.
// If a file is missing (local dev, an older deploy), fall back to the API.
const STATIC = import.meta.env.VITE_STATIC_URL ?? "/data";

async function staticOrApi<T>(name: string, path: string): Promise<T> {
  try {
    const res = await fetch(`${STATIC}/${name}.json`);
    if (res.ok && (res.headers.get("content-type") ?? "").includes("json")) return (await res.json()) as T;
  } catch {
    // fall through to the API
  }
  return get<T>(path);
}

export const fetchMeta = () => staticOrApi<Meta>("meta", "/meta");

export function fetchSites(f: Filters): Promise<SitesGeoJSON> {
  const q = new URLSearchParams();
  f.licenceAreas.forEach((a) => q.append("licence_area", a));
  f.voltages.forEach((v) => q.append("voltage", String(v)));
  if (f.minScore > 0) q.set("min_score", String(f.minScore));
  const qs = q.toString();
  return qs ? get<SitesGeoJSON>(`/sites?${qs}`) : staticOrApi<SitesGeoJSON>("sites", "/sites");
}

export const fetchSite = (id: string) => get<SiteDetail>(`/sites/${encodeURIComponent(id)}`);

export interface QueryResult {
  answer: string;
  sites: { site_id: string; name: string; lat: number; lon: number }[];
  unverified_numbers: string[];
  tool_calls: { name: string; input: Record<string, unknown> }[];
  stop_reason: string | null;
  model: string | null;
  disclaimer: string;
}

export class AskError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function askQuestion(question: string, accessCode: string): Promise<QueryResult> {
  const res = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Access-Code": accessCode },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const detail = await res.json().then((d) => d.detail).catch(() => null);
    throw new AskError(typeof detail === "string" ? detail : `${res.status} ${res.statusText}`, res.status);
  }
  return res.json() as Promise<QueryResult>;
}

export interface BspRow {
  bsp_id: string;
  dno: string;
  name: string;
  licence_area: string;
  lat: number | null;
  lon: number | null;
  site_id: string | null;
  gsp: string | null;
  matched: boolean;
  note: string | null;
  headroom_mw: number | null;
  site_count: number;
  queue_mw: number;
  headroom_after_queue_mw: number | null;
  stuck_mw: number | null;
  stuck_rank: number | null;
  site_ids: string[];
  headroom_source?: string | null;
  cep_mw?: number | null; // Spain: transmission capacity for power-electronics demand (CEP, CAD1)
  free_bays?: number | null;
}

export const fetchBsps = () => staticOrApi<{ count: number; bsps: BspRow[]; sources: Record<string, Source | null> }>("bsps", "/bsps");

/** Upper level of the network tree in each country: "BSP" (GB) or "transmission node" (Spain). */
export const upperLevel = (c: CountryInfo | null | undefined) => c?.upper_level ?? "BSP";

export interface StoryChapter {
  id: string;
  number: number;
  title: string;
  body: string;
  facts: { label: string; value: number | string; unit: string }[];
  sources: Source[];
  focus: {
    view: "investor" | "developer";
    sort?: "score" | "stuck" | "bsp";
    network: boolean;
    center: [number, number];
    zoom: number;
    select?: string;
    highlight?: string[];
    areas?: string[];
    node?: string; // open this upper-level node's what-if card
  };
}

export const fetchStory = (country: string) =>
  staticOrApi<{ chapters: StoryChapter[]; snapshots: string[]; scenario: string | null }>(`story-${country}`, `/story?country=${country}`);

/** A distribution network operator (Spain: one of ~59 distributors). gold.operator_mart. */
export interface OperatorRow {
  country: string;
  dno: string;
  operator: string;
  operator_name: string;
  licence_area: string;
  sites: number;
  scored_sites: number;
  substations: number;
  provinces: string;
  province_count: number;
  sites_zero_headroom: number;
  share_zero_headroom: number;
  headroom_mw: number;
  queue_mw: number;
  stuck_mw: number;
  capacity_taken_mw: number | null;
  median_score: number | null;
  top_site_id: string | null;
  top_site_name: string | null;
  top_site_stuck_mw: number | null;
  stuck_rank: number | null;
}

export const fetchOperators = (country: string) =>
  staticOrApi<{ country: string; count: number; operators: OperatorRow[]; sources: Record<string, Source | null>; note: string }>(
    `operators-${country}`, `/operators?country=${country}`);
export const fetchNetwork = (country: string) =>
  staticOrApi<GeoJSON.FeatureCollection>(`network-${country}`, `/network?country=${country}`);

export interface GspRow {
  gsp: string;
  licence_area: string | null;
  lat: number | null;
  lon: number | null;
  site_count: number;
  bsp_count: number;
  queue_mw: number;
  primary_queue_mw: number;
  grid_level_queue_mw: number;
  stuck_mw: number;
  stuck_rank: number | null;
  large_demand_count: number;
  large_demand_mva: number;
  sites_limited_by_bsp: number;
  sites_running_out_by: number;
  running_out_by_year: number;
  earliest_runs_out_year: number | null;
  import_capacity_utilisation_pct: number | null;
  in_gsp_list: boolean;
}

export const fetchGsps = () => staticOrApi<{ count: number; gsps: GspRow[] }>("gsps", "/gsps");

/** One upper-level node in the unlock planner (gold.unlock_mart). new_/served_/open_<MW> are gains from adding that many MW. */
export interface UnlockNode {
  bsp_id: string;
  dno: string;
  name: string;
  lat: number | null;
  lon: number | null;
  sites: number;
  headroom_mw: number;
  queue_mw: number;
  node_stuck_mw: number;
  spare_mw: number;
  needs_local_mw: number;
  mw_to_first_open: number | null;
  load_mw: number;
  rank_new_50: number | null;
  rank_queue_50: number | null;
  [key: string]: string | number | null;
}

export const fetchUnlock = (country: string) =>
  staticOrApi<{ country: string; count: number; steps: number[]; load_mw: number; nodes: UnlockNode[]; sources: Source[]; caveat: string }>(
    `unlock-${country}`, `/unlock?country=${country}`);
