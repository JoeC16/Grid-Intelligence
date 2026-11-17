import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap } from "maplibre-gl";
import type { SitesGeoJSON } from "./api";
import { INK, scoreColor, UNSCORED, type Ramp } from "./colors";

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const LONDON: [number, number] = [-0.12, 51.5];
const DATA_ATTRIBUTION =
  'Substation data: <a href="https://ukpowernetworks.opendatasoft.com/" target="_blank" rel="noreferrer">UK Power Networks Open Data</a>, CC BY 4.0';

export type LiveScores = Map<string, { score: number | null; rank: number | null }>;

interface Props {
  /** Every site, loaded once. Never re-set on the map (that forces a re-tile). */
  sites: SitesGeoJSON | null;
  /** Live score/rank per site for the current view + weights. */
  live: LiveScores | null;
  /** site_ids that pass the filters. */
  visible: Set<string> | null;
  ramp: Ramp;
  selectedId: string | null;
  onSelect: (siteId: string | null) => void;
}

// Colour and visibility live in feature-state, so view switches, weight
// sliders and filters only repaint; the GeoJSON is uploaded once and the
// paint expressions never change (changing them forces a buffer rebuild).
const COLOR = ["coalesce", ["feature-state", "color"], UNSCORED] as unknown as maplibregl.ExpressionSpecification;

const unlessHidden = (on: number): maplibregl.ExpressionSpecification =>
  ["case", ["boolean", ["feature-state", "hidden"], false], 0, on] as unknown as maplibregl.ExpressionSpecification;

export default function MapView({ sites, live, visible, ramp, selectedId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  // Latest props for the map's event handlers, which are bound once.
  const latest = useRef({ live, visible, onSelect });
  latest.current = { live, visible, onSelect };

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
      // 11 kV boards), so list them all, highest live score first.
      const byScore = (fs: maplibregl.MapGeoJSONFeature[]) => {
        const seen = new Set<string>();
        return fs
          .map((f) => f.properties as { site_id: string; name: string })
          .filter((p) => !seen.has(p.site_id) && seen.add(p.site_id))
          .sort((a, b) => (latest.current.live?.get(b.site_id)?.score ?? -1) - (latest.current.live?.get(a.site_id)?.score ?? -1));
      };
      m.on("mousemove", (e) => {
        const hits = visibleHits(e.point);
        if (!hits.length) {
          m.getCanvas().style.cursor = "";
          popup.remove();
          return;
        }
        m.getCanvas().style.cursor = "pointer";
        const lines = byScore(hits).map((p) => {
          const l = latest.current.live?.get(p.site_id);
          const score = l?.score == null ? "not scored" : `score ${l.score.toFixed(1)} · rank ${l.rank}`;
          return `<strong>${escapeHtml(p.name)}</strong><br/><span style="color:#5f5e5a">${score}</span>`;
        });
        popup
          .setLngLat((hits[0].geometry as GeoJSON.Point).coordinates as [number, number])
          .setHTML(lines.join('<div style="height:6px"></div>'))
          .addTo(m);
      });
      m.on("click", (e) => {
        // Generous hit target: anything within 8px of the click.
        const hits = visibleHits([
          [e.point.x - 8, e.point.y - 8],
          [e.point.x + 8, e.point.y + 8],
        ]);
        latest.current.onSelect(hits.length ? byScore(hits)[0].site_id : null);
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
    if (!ready || !m || !sites || !live) return;
    popupRef.current?.remove(); // its score/rank would now be stale
    for (const f of sites.features) {
      const id = f.properties.site_id;
      m.setFeatureState(
        { source: "sites", id },
        { color: scoreColor(live.get(id)?.score ?? null, ramp), hidden: visible ? !visible.has(id) : false },
      );
    }
  }, [ready, sites, live, visible, ramp]);

  // Highlight the selected site.
  useEffect(() => {
    if (ready && map.current) map.current.setFilter("selected", ["==", ["get", "site_id"], selectedId ?? ""]);
  }, [ready, selectedId]);

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
