import { useEffect, useRef } from "react";
import maplibregl, { type GeoJSONSource, type Map as MLMap } from "maplibre-gl";
import type { SitesGeoJSON } from "./api";
import { INK, SCORE_STOPS, UNSCORED } from "./colors";

const STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const LONDON: [number, number] = [-0.12, 51.5];
const DATA_ATTRIBUTION =
  'Substation data: <a href="https://ukpowernetworks.opendatasoft.com/" target="_blank" rel="noreferrer">UK Power Networks Open Data</a>, CC BY 4.0';

interface Props {
  sites: SitesGeoJSON | null;
  selectedId: string | null;
  onSelect: (siteId: string | null) => void;
}

export default function MapView({ sites, selectedId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const ready = useRef(false);
  const pending = useRef<SitesGeoJSON | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

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
      m.addSource("sites", { type: "geojson", data: pending.current ?? { type: "FeatureCollection", features: [] } });

      // circle radius by zoom: [zoom, px] pairs. The selection ring is 4px wider.
      const RADII = [6, 3, 9, 5, 12, 9, 15, 13];
      const byZoom = (extra: number) =>
        ["interpolate", ["linear"], ["zoom"], ...RADII.map((v, i) => (i % 2 ? v + extra : v))] as unknown as maplibregl.ExpressionSpecification;
      const radius = byZoom(0);
      const color: maplibregl.ExpressionSpecification = [
        "case",
        ["!", ["has", "score"]],
        UNSCORED,
        ["==", ["typeof", ["get", "score"]], "null"],
        UNSCORED,
        ["interpolate", ["linear"], ["get", "score"], ...SCORE_STOPS.flat()],
      ] as unknown as maplibregl.ExpressionSpecification;

      m.addLayer({
        id: "sites",
        type: "circle",
        source: "sites",
        // Draw the highest scores last so they sit on top.
        layout: { "circle-sort-key": ["coalesce", ["get", "score"], -1] },
        paint: {
          "circle-radius": radius,
          "circle-color": color,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
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

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
      m.on("mousemove", "sites", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        m.getCanvas().style.cursor = "pointer";
        const p = f.properties as { name: string; score: number | null; rank: number | null };
        const score = p.score == null ? "not scored" : `score ${Math.round(p.score)} · rank ${p.rank}`;
        popup
          .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
          .setHTML(`<strong>${escapeHtml(p.name)}</strong><br/><span style="color:#5f5e5a">${score}</span>`)
          .addTo(m);
      });
      m.on("mouseleave", "sites", () => {
        m.getCanvas().style.cursor = "";
        popup.remove();
      });
      m.on("click", (e) => {
        // Generous hit target: anything within 8px of the click.
        const box: [maplibregl.PointLike, maplibregl.PointLike] = [
          [e.point.x - 8, e.point.y - 8],
          [e.point.x + 8, e.point.y + 8],
        ];
        const hits = m.queryRenderedFeatures(box, { layers: ["sites"] });
        onSelectRef.current(hits.length ? (hits[0].properties as { site_id: string }).site_id : null);
      });

      ready.current = true;
      if (pending.current) (m.getSource("sites") as GeoJSONSource).setData(pending.current);
    });

    return () => {
      m.remove();
      map.current = null;
      ready.current = false;
    };
  }, []);

  // Push new data when filters change.
  useEffect(() => {
    if (!sites) return;
    pending.current = sites;
    if (ready.current && map.current) (map.current.getSource("sites") as GeoJSONSource).setData(sites);
  }, [sites]);

  // Highlight the selected site.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    m.setFilter("selected", ["==", ["get", "site_id"], selectedId ?? ""]);
  }, [selectedId]);

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
