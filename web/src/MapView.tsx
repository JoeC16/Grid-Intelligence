import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap } from "maplibre-gl";
import type { SitesGeoJSON } from "./api";
import { INK, UNSCORED } from "./colors";

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const LONDON: [number, number] = [-0.12, 51.5];
const DATA_ATTRIBUTION =
  'Substation data: <a href="https://ukpowernetworks.opendatasoft.com/" target="_blank" rel="noreferrer">UK Power Networks Open Data</a>, CC BY 4.0';

/** What to draw for each site: its colour and the tooltip line. */
export type Display = Map<string, { color: string; tip: string; rank: number | null }>;

interface Props {
  /** Every site, loaded once. Never re-set on the map (that forces a re-tile). */
  sites: SitesGeoJSON | null;
  display: Display | null;
  /** site_ids that pass the filters. */
  visible: Set<string> | null;
  selectedId: string | null;
  /** Sites to ring on the map, e.g. the ones an AI answer names. */
  highlightIds?: string[];
  /** Upstream path of the selected site: lines (kind "path" | "sibling") and BSP/GSP points (kind "bsp" | "gsp"). */
  topology?: GeoJSON.FeatureCollection | null;
  /** The whole network tree (from /network), drawn when not null. */
  network?: GeoJSON.FeatureCollection | null;
  /** Fly the camera here; change `key` to fly again to the same place. */
  flyTo?: { center: [number, number]; zoom: number; key: number } | null;
  onSelectGsp?: (gsp: string) => void;
  onSelect: (siteId: string | null) => void;
}

// Colour and visibility live in feature-state, so view switches, weight
// sliders and filters only repaint; the GeoJSON is uploaded once and the
// paint expressions never change (changing them forces a buffer rebuild).
const COLOR = ["coalesce", ["feature-state", "color"], UNSCORED] as unknown as maplibregl.ExpressionSpecification;

const unlessHidden = (on: number): maplibregl.ExpressionSpecification =>
  ["case", ["boolean", ["feature-state", "hidden"], false], 0, on] as unknown as maplibregl.ExpressionSpecification;

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export default function MapView({
  sites, display, visible, selectedId, highlightIds = [], topology = null, network = null, flyTo = null, onSelectGsp, onSelect,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  // Latest props for the map's event handlers, which are bound once.
  const latest = useRef({ display, visible, onSelect, onSelectGsp });
  latest.current = { display, visible, onSelect, onSelectGsp };

  // Create the map once.
  useEffect(() => {
    if (!container.current) return;
    const m = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      center: LONDON,
      zoom: 9,
      minZoom: 6,
      attributionControl: false,
    });
    map.current = m;
    if (import.meta.env.DEV) (window as unknown as { __map: MLMap }).__map = m; // for browser tests
    m.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: DATA_ATTRIBUTION }));
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    m.on("load", () => {
      m.addSource("sites", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        promoteId: "site_id",
      });

      // circle radius by zoom: [zoom, px] pairs. The selection ring is 4px wider.
      const RADII = [6, 3, 9, 5, 12, 9, 15, 13];
      const byZoom = (extra: number) =>
        ["interpolate", ["linear"], ["zoom"], ...RADII.map((v, i) => (i % 2 ? v + extra : v))] as unknown as maplibregl.ExpressionSpecification;

      // Network tree (Phase 10): edges under the dots, BSP/GSP nodes above them.
      m.addSource("network", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "net-site-edges", type: "line", source: "network",
        filter: ["==", ["get", "kind"], "edge_site"],
        paint: { "line-color": INK, "line-width": 0.6, "line-opacity": 0.25 },
      });
      m.addLayer({
        id: "net-bsp-edges", type: "line", source: "network",
        filter: ["==", ["get", "kind"], "edge_bsp"],
        paint: { "line-color": INK, "line-width": 1.4, "line-opacity": 0.55 },
      });

      // Upstream lines sit under the dots; BSP/GSP markers go on top (added below).
      m.addSource("topology", { type: "geojson", data: EMPTY });
      // Dash patterns can't be data-driven, so siblings and the path are separate layers.
      m.addLayer({
        id: "topo-siblings",
        type: "line",
        source: "topology",
        filter: ["==", ["get", "kind"], "sibling"],
        paint: { "line-color": INK, "line-width": 1, "line-opacity": 0.35, "line-dasharray": [2, 2] },
      });
      m.addLayer({
        id: "topo-path",
        type: "line",
        source: "topology",
        filter: ["==", ["get", "kind"], "path"],
        paint: { "line-color": INK, "line-width": 2, "line-opacity": 0.8 },
      });
      m.addLayer({
        id: "sites",
        type: "circle",
        source: "sites",
        paint: {
          "circle-radius": byZoom(0),
          "circle-color": COLOR,
          "circle-opacity": unlessHidden(1),
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": unlessHidden(1),
        },
      });
      m.addLayer({
        id: "highlight",
        type: "circle",
        source: "sites",
        filter: ["in", ["get", "site_id"], ["literal", []]],
        paint: {
          "circle-radius": byZoom(3),
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": INK,
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": 0.7,
        },
      });
      // Node size = stuck MW; filled when there is stuck demand.
      const nodeRadius = (base: number) =>
        ["interpolate", ["linear"], ["get", "stuck_mw"], 0, base, 50, base + 5, 300, base + 14] as unknown as maplibregl.ExpressionSpecification;
      m.addLayer({
        id: "net-bsp-nodes", type: "circle", source: "network",
        filter: ["==", ["get", "kind"], "node_bsp"],
        paint: {
          "circle-radius": nodeRadius(3.5),
          "circle-color": ["case", [">", ["get", "stuck_mw"], 0], INK, "#ffffff"],
          "circle-opacity": 0.85,
          "circle-stroke-color": INK,
          "circle-stroke-width": 1.5,
        },
      });
      m.addLayer({
        id: "net-gsp-nodes", type: "circle", source: "network",
        filter: ["==", ["get", "kind"], "node_gsp"],
        paint: {
          "circle-radius": nodeRadius(6),
          "circle-color": "#ffffff",
          "circle-stroke-color": INK,
          "circle-stroke-width": ["case", [">", ["get", "stuck_mw"], 0], 4, 2],
        },
      });
      const nodeTip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
      for (const layer of ["net-bsp-nodes", "net-gsp-nodes"]) {
        m.on("mousemove", layer, (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const p = f.properties as { kind: string; name: string; stuck_mw: number; queue_mw: number; site_count: number };
          const what = p.kind === "node_gsp" ? "Grid supply point" : "Bulk supply point";
          nodeTip
            .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
            .setHTML(`<strong>${escapeHtml(p.name)}</strong><br/><span style="color:#5f5e5a">${what} · ${Number(p.stuck_mw).toFixed(1)} MW stuck · ${Number(p.queue_mw).toFixed(1)} MW queued · ${p.site_count} sites</span>`)
            .addTo(m);
        });
        m.on("mouseleave", layer, () => nodeTip.remove());
      }

      m.addLayer({
        id: "topo-nodes",
        type: "circle",
        source: "topology",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["case", ["==", ["get", "kind"], "gsp"], 9, 7],
          "circle-color": "#ffffff",
          "circle-stroke-color": INK,
          "circle-stroke-width": ["case", ["==", ["get", "kind"], "gsp"], 3.5, 2.5],
        },
      });
      m.addLayer({
        id: "selected",
        type: "circle",
        source: "sites",
        filter: ["==", ["get", "site_id"], ""],
        paint: {
          "circle-radius": byZoom(4),
          "circle-color": "rgba(0,0,0,0)",
          "circle-stroke-color": INK,
          "circle-stroke-width": 2.5,
        },
      });

      // Filtered-out dots are transparent but still rendered, so skip them
      // when hit-testing.
      const visibleHits = (where: maplibregl.PointLike | [maplibregl.PointLike, maplibregl.PointLike]) =>
        m.queryRenderedFeatures(where, { layers: ["sites"] }).filter((f) => {
          const id = (f.properties as { site_id: string }).site_id;
          return latest.current.visible?.has(id) ?? true;
        });

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
      popupRef.current = popup;
      // Several substations can share one point (e.g. a grid site's 33 kV and
      // 11 kV boards), so list them all, best-ranked first.
      const rankOf = (id: string) => latest.current.display?.get(id)?.rank ?? Infinity;
      const byRank = (fs: maplibregl.MapGeoJSONFeature[]) => {
        const seen = new Set<string>();
        return fs
          .map((f) => f.properties as { site_id: string; name: string })
          .filter((p) => !seen.has(p.site_id) && seen.add(p.site_id))
          .sort((a, b) => rankOf(a.site_id) - rankOf(b.site_id));
      };
      m.on("mousemove", (e) => {
        const hits = visibleHits(e.point);
        if (!hits.length) {
          m.getCanvas().style.cursor = "";
          popup.remove();
          return;
        }
        m.getCanvas().style.cursor = "pointer";
        const lines = byRank(hits).map((p) => {
          const tip = latest.current.display?.get(p.site_id)?.tip ?? "";
          return `<strong>${escapeHtml(p.name)}</strong><br/><span style="color:#5f5e5a">${escapeHtml(tip)}</span>`;
        });
        popup
          .setLngLat((hits[0].geometry as GeoJSON.Point).coordinates as [number, number])
          .setHTML(lines.join('<div style="height:6px"></div>'))
          .addTo(m);
      });
      m.on("click", (e) => {
        // Network nodes win over the dots under them: a GSP opens its card,
        // a BSP selects its own board (when it is a site).
        const nodes = m.queryRenderedFeatures(e.point, { layers: ["net-gsp-nodes", "net-bsp-nodes"] });
        const gsp = nodes.find((f) => f.properties?.kind === "node_gsp");
        if (gsp) {
          latest.current.onSelectGsp?.(String(gsp.properties!.name));
          return;
        }
        const bsp = nodes.find((f) => f.properties?.kind === "node_bsp" && f.properties?.site_id);
        if (bsp) {
          latest.current.onSelect(String(bsp.properties!.site_id));
          return;
        }
        // Generous hit target: anything within 8px of the click.
        const hits = visibleHits([
          [e.point.x - 8, e.point.y - 8],
          [e.point.x + 8, e.point.y + 8],
        ]);
        latest.current.onSelect(hits.length ? byRank(hits)[0].site_id : null);
      });

      setReady(true);
    });

    return () => {
      m.remove();
      map.current = null;
      setReady(false);
    };
  }, []);

  // Upload the sites once (and again only if the dataset itself changes).
  useEffect(() => {
    if (ready && sites && map.current) (map.current.getSource("sites") as GeoJSONSource).setData(sites);
  }, [ready, sites]);

  // Push colour + visibility as feature-state: a repaint, not a re-tile.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !sites || !display) return;
    popupRef.current?.remove(); // its numbers would now be stale
    for (const f of sites.features) {
      const id = f.properties.site_id;
      m.setFeatureState(
        { source: "sites", id },
        { color: display.get(id)?.color ?? UNSCORED, hidden: visible ? !visible.has(id) : false },
      );
    }
  }, [ready, sites, display, visible]);

  // Draw / clear the whole network.
  useEffect(() => {
    if (ready && map.current) (map.current.getSource("network") as GeoJSONSource).setData(network ?? EMPTY);
  }, [ready, network]);

  // Story: fly to a chapter's view.
  useEffect(() => {
    if (ready && map.current && flyTo) map.current.flyTo({ center: flyTo.center, zoom: flyTo.zoom, duration: 1200 });
  }, [ready, flyTo]);

  // Draw the selected site's upstream path.
  useEffect(() => {
    if (ready && map.current) (map.current.getSource("topology") as GeoJSONSource).setData(topology ?? EMPTY);
  }, [ready, topology]);

  // Ring the highlighted sites.
  useEffect(() => {
    if (ready && map.current) map.current.setFilter("highlight", ["in", ["get", "site_id"], ["literal", highlightIds]]);
  }, [ready, highlightIds]);

  // Highlight the selected site, and bring it into view if it's off-screen
  // (e.g. picked from the ranked list).
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    m.setFilter("selected", ["==", ["get", "site_id"], selectedId ?? ""]);
    const f = selectedId && sites?.features.find((x) => x.properties.site_id === selectedId);
    if (f) {
      const c = f.geometry.coordinates;
      const pad = 0.15; // keep clear of the edges and side panels
      const b = m.getBounds();
      const w = b.getEast() - b.getWest(), h = b.getNorth() - b.getSouth();
      const inside = c[0] > b.getWest() + w * pad && c[0] < b.getEast() - w * (pad + 0.25) &&
                     c[1] > b.getSouth() + h * pad && c[1] < b.getNorth() - h * pad;
      // Phones: the panel is a bottom sheet over ~58% of the map, so centre the site in the strip above it.
      const phone = window.innerWidth < 640;
      if (phone) m.easeTo({ center: c, zoom: Math.max(m.getZoom(), 10), duration: 600, padding: { top: 0, left: 0, right: 0, bottom: m.getContainer().clientHeight * 0.58 } });
      else if (!inside) m.easeTo({ center: c, zoom: Math.max(m.getZoom(), 10), duration: 600 });
    }
  }, [ready, selectedId, sites]);

  // MapLibre's CSS sets position:relative on the map element, so size it
  // inside a positioned wrapper rather than positioning it directly.
  return (
    <div className="absolute inset-0">
      <div ref={container} className="h-full w-full" />
    </div>
  );
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
