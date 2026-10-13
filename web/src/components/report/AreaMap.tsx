"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useRef, useState } from "react";
import type { GeoJSONSource, Map as MlMap, MapGeoJSONFeature, MapMouseEvent, Popup } from "maplibre-gl";
import { AMENITY_STYLE, MAP_INK, OFSTED_COLORS, iconUrl, installIconFactory, phaseLetter } from "./mapIcons";

/* ------------------------------------------------------------------ config */

export type LayerKey = "neighbours" | "transport" | "schools" | "amenities" | "green" | "crime" | "flood" | "planning";
type Basemap = "simple" | "detailed";
type FC = { type: "FeatureCollection"; features: unknown[]; months?: string[] };

const BASEMAPS: Record<Basemap, string> = {
  simple: "https://tiles.openfreemap.org/styles/positron",
  detailed: "https://tiles.openfreemap.org/styles/liberty",
};

const LAYERS: { key: LayerKey; label: string; group: string; minZoom: number }[] = [
  { key: "neighbours", label: "Neighbouring areas", group: "Area", minZoom: 10 },
  { key: "transport", label: "Stations and bus stops", group: "Everyday essentials", minZoom: 11 },
  { key: "schools", label: "Schools by Ofsted grade", group: "Everyday essentials", minZoom: 11 },
  { key: "amenities", label: "GPs, pharmacies, dentists, supermarkets", group: "Everyday essentials", minZoom: 12 },
  { key: "green", label: "Parks and green space", group: "Everyday essentials", minZoom: 12 },
  { key: "crime", label: "Crime, last 3 months", group: "Risks", minZoom: 12 },
  { key: "flood", label: "Flood zones", group: "Risks", minZoom: 11 },
  { key: "planning", label: "Conservation and green belt", group: "Risks", minZoom: 10 },
];

const OFSTED_LABELS: [number, string][] = [[1, "Outstanding"], [2, "Good"], [3, "Requires improvement"], [4, "Inadequate"], [0, "Report card or not rated"]];

const CRIME_GROUPS: { label: string; color: string; types: string[] }[] = [
  { label: "Violence and robbery", color: "#b83a2e", types: ["Violence and sexual offences", "Robbery", "Possession of weapons"] },
  { label: "Burglary and theft", color: "#c98a0b", types: ["Burglary", "Other theft", "Theft from the person", "Bicycle theft", "Shoplifting", "Vehicle crime"] },
  { label: "Anti-social behaviour", color: "#7a6aa8", types: ["Anti-social behaviour"] },
  { label: "Damage, drugs, other", color: "#4a5a70", types: ["Criminal damage and arson", "Drugs", "Public order", "Other crime"] },
];

const PLANNING = [
  { t: "planning.conservation_area", label: "Conservation area", color: "#8a5a2b" },
  { t: "planning.article4", label: "Article 4 direction", color: "#b8573a" },
  { t: "planning.green_belt", label: "Green belt", color: "#4f8a3a" },
  { t: "nature.sssi", label: "SSSI", color: "#2b8a7a" },
  { t: "nature.national_park", label: "National Park", color: "#3a6a2b" },
  { t: "nature.national_landscape", label: "National Landscape", color: "#6a8a2b" },
  { t: "nature.local_nature_reserve", label: "Local nature reserve", color: "#2b7a5a" },
];

const ENDPOINT: Record<LayerKey, string> = {
  neighbours: "areas", transport: "transport", schools: "schools", amenities: "amenities",
  green: "green", crime: "crime", flood: "flood", planning: "planning",
};

/* ------------------------------------------------------------------ types + helpers */

export interface MapPoi {
  name: string;
  type: string;
  lon: number;
  lat: number;
  href?: string | null;
  /** Ofsted rank 1–4, 0 = report card / unrated (schools only) */
  ofsted?: number;
  ofstedLabel?: string;
}

export interface Essential {
  label: string;
  name: string;
  dist: number;
  lon: number;
  lat: number;
  icon: string;
  href?: string | null;
}

type Bounds = [number, number, number, number];

const empty = (): FC => ({ type: "FeatureCollection", features: [] });
const contains = (outer: Bounds, inner: Bounds) => outer[0] <= inner[0] && outer[1] <= inner[1] && outer[2] >= inner[2] && outer[3] >= inner[3];
function pad(b: Bounds, k = 0.35): Bounds {
  const dx = (b[2] - b[0]) * k, dy = (b[3] - b[1]) * k;
  return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy];
}
const tooBig = (b: Bounds) => b[2] - b[0] > 0.5 || b[3] - b[1] > 0.3;
function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}
function fc(list: MapPoi[]): FC {
  return {
    type: "FeatureCollection",
    features: list.map((p) => ({
      type: "Feature",
      properties: { n: p.name, t: p.type, href: p.href ?? "", o: p.ofsted ?? 0, ol: p.ofstedLabel ?? "", tn: AMENITY_STYLE[p.type]?.label ?? "" },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  };
}
/** Degrees per metre at a latitude (good to well under 1% across Great Britain). */
const degPerM = (lat: number) => ({ x: 1 / (111320 * Math.cos((lat * Math.PI) / 180)), y: 1 / 110540 });
function circle(c: [number, number], m: number): number[][] {
  const d = degPerM(c[1]);
  return Array.from({ length: 97 }, (_, i) => {
    const a = (i / 96) * Math.PI * 2;
    return [c[0] + Math.cos(a) * m * d.x, c[1] + Math.sin(a) * m * d.y];
  });
}
function circleBounds(c: [number, number], m: number): Bounds {
  const d = degPerM(c[1]);
  return [c[0] - m * d.x, c[1] - m * d.y, c[0] + m * d.x, c[1] + m * d.y];
}
const fmtDist = (m: number) => (m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`);
const walk = (m: number) => Math.max(1, Math.round((m * 1.25) / 80));

/* ------------------------------------------------------------------ component */

export function AreaMap({ center, bbox, geojson, boundaryNote, label, levelForNeighbours, pois = [], essentials = [], radiusM, initialLayers }: {
  center: [number, number];
  bbox: Bounds | null;
  geojson: string | null;
  /** shown in the key when the boundary is approximate */
  boundaryNote?: string | null;
  label: string;
  /** level whose neighbouring boundaries can be shown (sector, district, lad) */
  levelForNeighbours: string | null;
  /** points known from the report, shown before the layer fetch completes */
  pois?: MapPoi[];
  /** nearest station, schools, GP… listed under the map */
  essentials?: Essential[];
  /** draw a ring this many metres around the centre and open the map framed on it */
  radiusM?: number;
  /** layers switched on at load, over the defaults (topic pages open on their own layer) */
  initialLayers?: Partial<Record<LayerKey, boolean>>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const popupRef = useRef<Popup | null>(null);
  const data = useRef<Partial<Record<LayerKey, { bounds: Bounds; fc: FC }>>>({});
  const inflight = useRef<Set<LayerKey>>(new Set());
  const [on, setOn] = useState<Record<LayerKey, boolean>>({
    neighbours: false, transport: true, schools: true, amenities: true, green: false, crime: false, flood: false, planning: false,
    ...initialLayers,
  });
  const onRef = useRef(on);
  const refreshAllRef = useRef<() => void>(() => {});
  const [basemap, setBasemap] = useState<Basemap>("simple");
  const [zoom, setZoom] = useState(14);
  const [status, setStatus] = useState<Partial<Record<LayerKey, "loading" | "error" | "zoom" | "ok">>>({});
  const [crimeFilter, setCrimeFilter] = useState<string>("all");
  const [crimeMonths, setCrimeMonths] = useState<string[]>([]);
  const [panel, setPanel] = useState(false);
  const [keyOpen, setKeyOpen] = useState(true);
  const [icons, setIcons] = useState<Record<string, string>>({});

  // The key starts open on wide screens, folded on phones.
  useEffect(() => { if (window.innerWidth < 760) setKeyOpen(false); }, []); // eslint-disable-line react-hooks/set-state-in-effect

  const initial: Bounds = radiusM ? circleBounds(center, radiusM * 1.08)
    : bbox ?? [center[0] - 0.012, center[1] - 0.007, center[0] + 0.012, center[1] + 0.007];

  // Legend and essentials use the same canvas icons as the map. Keyed on the icon ids, not the
  // array: the `essentials = []` default is a new array every render and would loop setIcons.
  const essentialIcons = essentials.map((e) => e.icon).join("\n");
  useEffect(() => {
    const ids = ["zc|rail", "zc|metro", "zc|bus", ...Object.keys(AMENITY_STYLE).map((k) => `zc|${k}`), ...OFSTED_LABELS.map(([r]) => `zc|school|${r}|S`), ...(essentialIcons ? essentialIcons.split("\n") : [])];
    setIcons(Object.fromEntries([...new Set(ids)].map((id) => [id, iconUrl(id)]))); // eslint-disable-line react-hooks/set-state-in-effect
  }, [essentialIcons]);

  /* ---- our sources and layers, re-added whenever the basemap style loads */
  const addOverlays = useCallback((m: MlMap) => {
    const font = ["Noto Sans Regular"];
    const bold = ["Noto Sans Bold"];
    const halo = { "text-color": MAP_INK, "text-halo-color": "#ffffff", "text-halo-width": 1.8 };
    const stored = (k: LayerKey, fallback: FC = empty()) => data.current[k]?.fc ?? fallback;
    const src = (id: string, d: FC) => { if (!m.getSource(id)) m.addSource(id, { type: "geojson", data: d as never }); };

    src("green", stored("green"));
    m.addLayer({ id: "green", type: "fill", source: "green", paint: { "fill-color": "#5fa65a", "fill-opacity": 0.3, "fill-outline-color": "#3d7a39" } });
    src("flood", stored("flood"));
    m.addLayer({ id: "flood", type: "fill", source: "flood", paint: { "fill-color": "#2b6cb0", "fill-opacity": ["match", ["get", "t"], "flood.zone3", 0.5, 0.22] } });
    src("planning", stored("planning"));
    const pcol = ["match", ["get", "t"], ...PLANNING.flatMap((p) => [p.t, p.color]), "#8a5a2b"] as never;
    m.addLayer({ id: "planning", type: "fill", source: "planning", paint: { "fill-color": pcol, "fill-opacity": 0.2 } });
    m.addLayer({ id: "planning-line", type: "line", source: "planning", paint: { "line-color": pcol, "line-width": 1.5 } });

    src("neighbours", stored("neighbours"));
    m.addLayer({ id: "neighbours", type: "line", source: "neighbours", paint: { "line-color": MAP_INK, "line-width": 1.2, "line-opacity": 0.5 } });
    m.addLayer({ id: "neighbours-label", type: "symbol", source: "neighbours", layout: { "text-field": ["get", "n"], "text-size": 13, "text-font": bold }, paint: halo });

    if (geojson) {
      src("area", { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: JSON.parse(geojson) }] });
      m.addLayer({ id: "area-fill", type: "fill", source: "area", paint: { "fill-color": "#1f6b4a", "fill-opacity": 0.07 } });
      m.addLayer({ id: "area-line", type: "line", source: "area", paint: { "line-color": "#1f6b4a", "line-width": 3, "line-dasharray": [1.5, 1.5] } });
    } else {
      src("pin", fc([{ name: label, type: "pin", lon: center[0], lat: center[1] }]));
      m.addLayer({ id: "pin-halo", type: "circle", source: "pin", paint: { "circle-radius": 60, "circle-color": "#1f6b4a", "circle-opacity": 0.08, "circle-stroke-width": 1, "circle-stroke-color": "#1f6b4a", "circle-stroke-opacity": 0.4 } });
      m.addLayer({ id: "pin", type: "circle", source: "pin", paint: { "circle-radius": 9, "circle-color": "#1f6b4a", "circle-stroke-width": 3, "circle-stroke-color": "#fff" } });
    }

    // Range ring: the world outside it is dimmed a touch so the circle reads as a lit area,
    // edged with a fine dotted line; the label follows the top arc.
    if (radiusM) {
      const ring = circle(center, radiusM);
      const arc = ring.slice(16, 33).reverse(); // 120° → 60°: the top arc, drawn left to right
      src("radius", { type: "FeatureCollection", features: [
        { type: "Feature", properties: { k: "mask" }, geometry: { type: "Polygon", coordinates: [[[-20, 40], [20, 40], [20, 70], [-20, 70], [-20, 40]], ring.slice().reverse()] } },
        { type: "Feature", properties: { k: "ring" }, geometry: { type: "LineString", coordinates: ring } },
        { type: "Feature", properties: { k: "arc", l: `${fmtDist(radiusM)}, ${walk(radiusM)} min walk` }, geometry: { type: "LineString", coordinates: arc } },
      ] });
      m.addLayer({ id: "radius-mask", type: "fill", source: "radius", filter: ["==", ["get", "k"], "mask"],
        paint: { "fill-color": MAP_INK, "fill-opacity": 0.07 } });
      m.addLayer({ id: "radius", type: "line", source: "radius", filter: ["==", ["get", "k"], "ring"],
        layout: { "line-cap": "round" },
        paint: { "line-color": MAP_INK, "line-width": 1.6, "line-opacity": 0.45, "line-dasharray": [0, 2.2] } });
      m.addLayer({ id: "radius-label", type: "symbol", source: "radius", filter: ["==", ["get", "k"], "arc"], layout: {
        "symbol-placement": "line-center", "text-field": ["get", "l"], "text-font": ["Noto Sans Regular"], "text-size": 11,
        "text-letter-spacing": 0.04, "text-offset": [0, -0.8], "text-keep-upright": true, "text-allow-overlap": true,
      }, paint: { "text-color": "#4a5a70", "text-halo-color": "rgba(255,255,255,0.9)", "text-halo-width": 1.6 } });
    }

    src("crime", stored("crime"));
    const crimeColor = ["match", ["get", "t"], ...CRIME_GROUPS.flatMap((g) => g.types.flatMap((t) => [t, g.color])), "#4a5a70"] as never;
    m.addLayer({ id: "crime-heat", type: "heatmap", source: "crime", maxzoom: 15.5, paint: {
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 11, 8, 15, 22],
      "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 13.5, 0.55, 15.5, 0],
      "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(0,0,0,0)", 0.25, "rgba(201,138,11,.45)", 0.6, "rgba(184,58,46,.7)", 1, "#7d1f16"],
    } });
    m.addLayer({ id: "crime-pt", type: "circle", source: "crime", minzoom: 14, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 3, 18, 7], "circle-color": crimeColor,
      "circle-opacity": ["interpolate", ["linear"], ["zoom"], 14, 0, 15, 0.8], "circle-stroke-width": 1, "circle-stroke-color": "#fff",
    } });

    const initialPois = (pred: (p: MapPoi) => boolean) => fc(pois.filter(pred));

    // Amenities: round badges with a glyph; names from zoom 15.
    src("amenities", stored("amenities", initialPois((p) => p.type in AMENITY_STYLE)));
    m.addLayer({ id: "amenities", type: "symbol", source: "amenities", layout: {
      "icon-image": ["concat", "zc|", ["get", "t"]], "icon-size": ["interpolate", ["linear"], ["zoom"], 12, 0.6, 15, 0.85, 17, 1],
      "icon-allow-overlap": true, "text-field": ["step", ["zoom"], "", 15.5, ["get", "n"]], "text-font": font, "text-size": 11,
      "text-offset": [0, 1.3], "text-anchor": "top", "text-optional": true, "symbol-sort-key": 2,
    }, paint: halo });

    // Schools: square badge, P/S/A letter, colour = Ofsted grade.
    src("schools", stored("schools", initialPois((p) => p.type.startsWith("school."))));
    m.addLayer({ id: "schools", type: "symbol", source: "schools", layout: {
      "icon-image": ["concat", "zc|school|", ["to-string", ["get", "o"]], "|",
        ["match", ["get", "t"], "school.primary", "P", "school.secondary", "S", "school.all_through", "A", "school.nursery", "N", "school.post16", "16", "•"]],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.6, 15, 0.9, 17, 1.05], "icon-allow-overlap": true,
      "text-field": ["step", ["zoom"], "", 14.5, ["get", "n"]], "text-font": bold, "text-size": 11, "text-offset": [0, 1.35],
      "text-anchor": "top", "text-optional": true, "text-max-width": 9, "symbol-sort-key": 1,
    }, paint: halo });

    // Transport: rail double-arrow, Underground roundel, bus stops from zoom 15.
    src("transport", stored("transport", initialPois((p) => p.type.startsWith("station.") || p.type === "stop.bus")));
    m.addLayer({ id: "bus", type: "symbol", source: "transport", minzoom: 15, filter: ["==", ["get", "t"], "stop.bus"], layout: { "icon-image": "zc|bus", "icon-size": 0.7, "icon-allow-overlap": true } });
    m.addLayer({ id: "stations", type: "symbol", source: "transport", filter: ["!=", ["get", "t"], "stop.bus"], layout: {
      "icon-image": ["match", ["get", "t"], "station.metro", "zc|metro", "zc|rail"], "icon-size": ["interpolate", ["linear"], ["zoom"], 11, 0.75, 15, 1.05],
      "icon-allow-overlap": true, "text-field": ["get", "n"], "text-font": bold, "text-size": 12.5, "text-offset": [0, 1.45], "text-anchor": "top",
      "text-optional": true, "symbol-sort-key": 0,
    }, paint: { ...halo, "text-halo-width": 2.2 } });

    applyVisibility(m, onRef.current);
  }, [geojson, label, center, pois, radiusM]);

  /* ---- create the map once */
  useEffect(() => {
    let cancelled = false;
    let m: MlMap | null = null;
    (async () => {
      const ml = (await import("maplibre-gl")).default;
      if (cancelled || !el.current) return;
      m = new ml.Map({
        container: el.current,
        style: BASEMAPS.simple,
        bounds: initial,
        fitBoundsOptions: { padding: 30, maxZoom: 15.5 },
        maxBounds: [[-11, 48.5], [4, 61.5]],
        attributionControl: { compact: true },
        cooperativeGestures: true,
      });
      map.current = m;
      installIconFactory(m);
      m.addControl(new ml.NavigationControl({ showCompass: false }), "top-left");
      m.addControl(new ml.FullscreenControl({ container: wrap.current! }), "top-left");
      m.addControl(new ml.GeolocateControl({ positionOptions: { enableHighAccuracy: false }, trackUserLocation: false }), "top-left");
      m.addControl(new ml.ScaleControl({ unit: "metric", maxWidth: 110 }), "bottom-right");
      m.on("style.load", () => addOverlays(m!));
      m.on("zoomend", () => setZoom(m!.getZoom()));
      m.on("moveend", () => refreshAllRef.current());
      m.once("load", () => refreshAllRef.current());

      const popup = new ml.Popup({ offset: 14, maxWidth: "280px" });
      popupRef.current = popup;
      const show = (e: MapMouseEvent, html: string) => popup.setLngLat(e.lngLat).setHTML(html).addTo(m!);
      const clickable = ["schools", "stations", "amenities", "bus", "crime-pt", "neighbours-label", "flood", "planning", "green"];
      for (const id of clickable) {
        m.on("mouseenter", id, () => { m!.getCanvas().style.cursor = "pointer"; });
        m.on("mouseleave", id, () => { m!.getCanvas().style.cursor = ""; });
      }
      m.on("click", async (e) => {
        const layers = clickable.filter((id) => m!.getLayer(id) && m!.getLayoutProperty(id, "visibility") !== "none");
        const f: MapGeoJSONFeature | undefined = m!.queryRenderedFeatures(e.point, { layers })[0];
        if (f) return show(e, featureHtml(f));
        try {
          const r = await fetch(`/api/uk/map/locate?lon=${e.lngLat.lng.toFixed(5)}&lat=${e.lngLat.lat.toFixed(5)}`);
          const hit = (await r.json()) as { postcode: string; href: string | null } | null;
          if (hit) show(e, `<strong>${esc(hit.postcode)}</strong><br>${hit.href ? `<a href="${hit.href}">View postcode report</a>` : ""}`);
        } catch { /* ignore */ }
      });
    })();
    return () => { cancelled = true; m?.remove(); map.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- fetch layers for the current view */
  const refresh = useCallback(async (k: LayerKey) => {
    const m = map.current;
    if (!m || !onRef.current[k] || inflight.current.has(k)) return;
    if (k === "neighbours" && !levelForNeighbours) return;
    const b = m.getBounds();
    const view: Bounds = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    const spec = LAYERS.find((l) => l.key === k)!;
    if (m.getZoom() < spec.minZoom || tooBig(view)) { setStatus((s) => ({ ...s, [k]: "zoom" })); return; }
    const have = data.current[k];
    if (have && contains(have.bounds, view)) { setStatus((s) => ({ ...s, [k]: "ok" })); return; }
    let want = pad(view);
    if (tooBig(want)) want = view;
    inflight.current.add(k);
    setStatus((s) => ({ ...s, [k]: "loading" }));
    try {
      const q = `bbox=${want.map((v) => v.toFixed(5)).join(",")}${k === "neighbours" ? `&level=${levelForNeighbours}` : ""}`;
      const r = await fetch(`/api/uk/map/${ENDPOINT[k]}?${q}`);
      if (!r.ok) throw new Error(String(r.status));
      const got = (await r.json()) as FC;
      data.current[k] = { bounds: want, fc: got };
      (m.getSource(k) as GeoJSONSource | undefined)?.setData(got as never);
      if (k === "crime") setCrimeMonths(got.months ?? []);
      setStatus((s) => ({ ...s, [k]: "ok" }));
    } catch {
      setStatus((s) => ({ ...s, [k]: "error" }));
    } finally {
      inflight.current.delete(k);
    }
  }, [levelForNeighbours]);

  const refreshAll = useCallback(() => {
    (Object.keys(onRef.current) as LayerKey[]).forEach((k) => { if (onRef.current[k]) void refresh(k); });
  }, [refresh]);
  useEffect(() => { refreshAllRef.current = refreshAll; }, [refreshAll]);

  useEffect(() => {
    onRef.current = on;
    const m = map.current;
    if (!m) return;
    const go = () => { applyVisibility(m, on); refreshAll(); };
    if (m.isStyleLoaded()) go(); else m.once("idle", go);
  }, [on, refreshAll]);

  useEffect(() => {
    const m = map.current;
    if (!m || !m.getLayer("crime-pt")) return;
    const g = CRIME_GROUPS.find((x) => x.label === crimeFilter);
    const filter = g ? (["in", ["get", "t"], ["literal", g.types]] as never) : null;
    m.setFilter("crime-pt", filter);
    m.setFilter("crime-heat", filter);
  }, [crimeFilter, on.crime]);

  useEffect(() => {
    const m = map.current;
    // diff: false → a full reload that fires "style.load", where our overlays are re-added. The
    // default diff drops our sources and layers without that event, so they vanished on a switch.
    if (m) m.setStyle(BASEMAPS[basemap], { diff: false });
  }, [basemap]);

  const focus = (e: Essential) => {
    const m = map.current;
    if (!m) return;
    m.flyTo({ center: [e.lon, e.lat], zoom: Math.max(m.getZoom(), 15.5), speed: 1.4 });
    popupRef.current?.setLngLat([e.lon, e.lat])
      .setHTML(`<strong>${e.href ? `<a href="${esc(e.href)}">${esc(e.name)}</a>` : esc(e.name)}</strong><br>${esc(e.label)}, ${fmtDist(e.dist)} (${walk(e.dist)} min walk)`)
      .addTo(m);
    wrap.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const groups = [...new Set(LAYERS.map((l) => l.group))];
  const legend = legendRows(on, icons, crimeMonths);
  const activeCount = Object.values(on).filter(Boolean).length;

  return (
    <div className="map-block">
      <div className="map map-detailed" ref={wrap} role="region" aria-label={`Map of ${label}`}>
        <div ref={el} className="canvas" />

        <button type="button" className="map-panel-toggle" aria-expanded={panel} onClick={() => setPanel(!panel)}>
          Layers ({activeCount})
        </button>

        {panel && (
          <div className="map-panel" role="group" aria-label="Map layers">
            {groups.map((g) => (
              <fieldset key={g}>
                <legend>{g}</legend>
                {LAYERS.filter((l) => l.group === g && (l.key !== "neighbours" || levelForNeighbours)).map((l) => (
                  <label key={l.key} className="layer-row">
                    <input type="checkbox" checked={on[l.key]} onChange={(e) => setOn({ ...on, [l.key]: e.target.checked })} />
                    <span>{l.label}</span>
                    <LayerState s={on[l.key] ? status[l.key] : undefined} />
                  </label>
                ))}
              </fieldset>
            ))}
            {on.crime && (
              <label className="layer-select">
                Crime type
                <select value={crimeFilter} onChange={(e) => setCrimeFilter(e.target.value)}>
                  <option value="all">All crime and ASB</option>
                  {CRIME_GROUPS.map((g) => <option key={g.label} value={g.label}>{g.label}</option>)}
                </select>
              </label>
            )}
            <fieldset>
              <legend>Base map</legend>
              <div className="seg">
                {(["simple", "detailed"] as Basemap[]).map((b) => (
                  <button key={b} type="button" aria-pressed={basemap === b} onClick={() => setBasemap(b)}>{b === "simple" ? "Simple" : "Detailed"}</button>
                ))}
              </div>
            </fieldset>
            <p className="map-hint">Click anywhere on the map to find the postcode there.</p>
          </div>
        )}

        {legend.length > 0 && (
          <div className="map-legend-wrap">
            {keyOpen && (
              <div className="map-legend" aria-label="Map key">
                {legend.map((row) => (
                  <span key={row.label}>
                    {/* eslint-disable-next-line @next/next/no-img-element -- tiny canvas data-URL icons */}
                    {row.img ? <img src={row.img} alt="" width={16} height={16} /> : <i style={{ background: row.color, border: row.border }} />}
                    {row.label}
                  </span>
                ))}
                {geojson && boundaryNote && <span className="m-src">{boundaryNote}</span>}
              </div>
            )}
            <button type="button" className="map-key-toggle" aria-expanded={keyOpen} onClick={() => setKeyOpen(!keyOpen)}>{keyOpen ? "Hide key" : "Key"}</button>
          </div>
        )}
        {on.crime && zoom < 14 && <div className="map-toast">Zoom in to see individual crimes</div>}
      </div>

      {essentials.length > 0 && (
        <div className="essentials" aria-label="Nearest essentials">
          <span className="ess-title">Nearest</span>
          <ul>
            {essentials.map((e) => (
              <li key={e.label + e.name}>
                <button type="button" onClick={() => focus(e)} title={`Show ${e.name} on the map`}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- tiny canvas data-URL icons */}
                  {icons[e.icon] ? <img src={icons[e.icon]} alt="" width={22} height={22} /> : <span className="ess-dot" />}
                  <span className="ess-text">
                    <span className="ess-k">{e.label}</span>
                    <span className="ess-n">{e.name}</span>
                  </span>
                  <span className="ess-d num">{fmtDist(e.dist)}<small>{walk(e.dist)} min</small></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ pieces */

function LayerState({ s }: { s?: "loading" | "error" | "zoom" | "ok" }) {
  if (!s || s === "ok") return null;
  const text = s === "loading" ? "loading…" : s === "zoom" ? "zoom in" : "unavailable";
  return <em className={`layer-state ${s}`}>{text}</em>;
}

function applyVisibility(m: MlMap, on: Record<LayerKey, boolean>) {
  const ids: Record<LayerKey, string[]> = {
    neighbours: ["neighbours", "neighbours-label"],
    transport: ["stations", "bus"],
    schools: ["schools"],
    amenities: ["amenities"],
    green: ["green"],
    crime: ["crime-heat", "crime-pt"],
    flood: ["flood"],
    planning: ["planning", "planning-line"],
  };
  for (const [k, list] of Object.entries(ids) as [LayerKey, string[]][]) {
    for (const id of list) if (m.getLayer(id)) m.setLayoutProperty(id, "visibility", on[k] ? "visible" : "none");
  }
}

function legendRows(on: Record<LayerKey, boolean>, icons: Record<string, string>, months: string[]) {
  const rows: { label: string; img?: string; color?: string; border?: string }[] = [];
  if (on.transport) rows.push({ label: "Rail station", img: icons["zc|rail"] }, { label: "Underground, metro or tram", img: icons["zc|metro"] });
  if (on.schools) OFSTED_LABELS.forEach(([r, l]) => rows.push({ label: `School: ${l}`, img: icons[`zc|school|${r}|S`] }));
  if (on.schools) rows.push({ label: "Letters: P primary, S secondary, A all-through", color: "transparent" });
  if (on.amenities) Object.entries(AMENITY_STYLE).forEach(([k, s]) => rows.push({ label: s.label, img: icons[`zc|${k}`] }));
  if (on.green) rows.push({ label: "Park or green space", color: "rgba(95,166,90,.5)" });
  if (on.crime) {
    CRIME_GROUPS.forEach((g) => rows.push({ label: g.label, color: g.color }));
    if (months.length) rows.push({ label: `Crimes ${months[0].slice(0, 7)} to ${months[months.length - 1].slice(0, 7)}`, color: "transparent" });
  }
  if (on.flood) rows.push({ label: "Flood Zone 3, high", color: "rgba(43,108,176,.55)" }, { label: "Flood Zone 2, medium", color: "rgba(43,108,176,.25)" });
  if (on.planning) PLANNING.slice(0, 4).forEach((p) => rows.push({ label: p.label, color: p.color }));
  if (on.neighbours) rows.push({ label: "Neighbouring boundary", color: "transparent", border: "1.5px solid #4a5a70" });
  return rows;
}

function featureHtml(f: MapGeoJSONFeature): string {
  const p = f.properties as Record<string, string | number>;
  const link = (text: string) => (p.href ? `<a href="${esc(String(p.href))}">${esc(text)}</a>` : esc(text));
  switch (f.layer.id) {
    case "schools": {
      const rank = Number(p.o);
      const color = OFSTED_COLORS[rank] ?? OFSTED_COLORS[0];
      const phase = String(p.t ?? "").replace("school.", "").replace("_", "-");
      return `<strong>${link(String(p.n))}</strong><br>${esc(phase.charAt(0).toUpperCase() + phase.slice(1))} school<br>Ofsted: <b style="color:${color}">${esc(String(p.ol || "Not rated"))}</b>`;
    }
    case "stations":
    case "bus":
      return `<strong>${link(String(p.n))}</strong><br>${esc(String(p.tn || (p.t === "station.metro" ? "Underground, metro or tram" : p.t === "stop.bus" ? "Bus stop" : "Rail station")))}`;
    case "amenities":
      return `<strong>${esc(String(p.n))}</strong><br>${esc(String(p.tn))}`;

    case "crime-pt":
      return `<strong>${esc(String(p.t))}</strong><br>${esc(String(p.m))}${p.l ? `<br>${esc(String(p.l))}` : ""}${p.o ? `<br>Outcome: ${esc(String(p.o))}` : ""}<br><span style="color:#4a5a70">Location is approximate</span>`;
    case "neighbours-label":
      return `<strong>${link(String(p.n))}</strong>`;
    default:
      return `<strong>${esc(String(p.tn ?? p.t))}</strong>${p.n ? `<br>${esc(String(p.n))}` : ""}`;
  }
}

export { phaseLetter };
