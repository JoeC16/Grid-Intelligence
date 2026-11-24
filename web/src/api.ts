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

export interface Meta {
  disclaimer: string;
  licence_areas: string[];
  voltages: number[];
  site_count: number;
  scored_count: number;
  signals: SignalMeta[];
  views: ViewMeta[];
  headroom_2030_scenario: string;
  sources: (Source & { dno: string; field: string; licence: string })[];
}

export interface SiteProps {
  site_id: string;
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
  capacity: { firm_capacity_mw: number | null; observed_peak_mw: number | null; source: Source | null };
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

export const fetchMeta = () => get<Meta>("/meta");

export function fetchSites(f: Filters): Promise<SitesGeoJSON> {
  const q = new URLSearchParams();
  f.licenceAreas.forEach((a) => q.append("licence_area", a));
  f.voltages.forEach((v) => q.append("voltage", String(v)));
  if (f.minScore > 0) q.set("min_score", String(f.minScore));
  return get<SitesGeoJSON>(`/sites?${q}`);
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
}

export const fetchBsps = () => get<{ count: number; bsps: BspRow[]; source: Source | null }>("/bsps");

export interface StoryChapter {
  id: string;
  number: number;
  title: string;
  body: string;
  facts: { label: string; value: number; unit: string }[];
  sources: Source[];
  focus: {
    view: "investor" | "developer";
    sort?: "score" | "stuck" | "bsp";
    network: boolean;
    center: [number, number];
    zoom: number;
    select?: string;
    highlight?: string[];
  };
}

export const fetchStory = () => get<{ chapters: StoryChapter[]; snapshots: string[]; scenario: string }>("/story");
export const fetchNetwork = () => get<GeoJSON.FeatureCollection>("/network");

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

export const fetchGsps = () => get<{ count: number; gsps: GspRow[] }>("/gsps");
