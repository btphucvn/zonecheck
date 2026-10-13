"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useRef, useState } from "react";
import type { GeoJSONSource, Map as MlMap, MapGeoJSONFeature, Popup } from "maplibre-gl";
import { MAP_INK } from "./mapIcons";

// Crime map for the crime detail page: every neighbourhood (LSOA) shaded by its crime rate
// against all neighbourhoods in England and Wales, with the number of crimes in a bubble,
// walking rings around the address and, on demand, the street-level crimes themselves.

type FC = { type: "FeatureCollection"; features: unknown[] };
type Bounds = [number, number, number, number];
type Group = "total" | "violent" | "burglary" | "vehicle" | "theft" | "damage" | "asb";
type Measure = "n" | "r";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const MIN_ZOOM = 12.3;

export const GROUPS: { k: Group; label: string }[] = [
  { k: "total", label: "All crime" },
  { k: "violent", label: "Violence and robbery" },
  { k: "burglary", label: "Burglary" },
  { k: "vehicle", label: "Vehicle crime" },
  { k: "theft", label: "Theft" },
  { k: "damage", label: "Criminal damage" },
  { k: "asb", label: "Anti-social behaviour" },
];

/** Percentile of the rate (higher = more crime) → fill. Breaks follow quintiles, the top split. */
const RAMP: [number, string, string][] = [
  [0, "#4f9a6a", "Among the lowest 20%"],
  [20, "#a6cf8b", "Lower than most"],
  [40, "#efe3b2", "Around average"],
  [60, "#f3b886", "Higher than most"],
  [80, "#e57f66", "Among the highest 20%"],
  [95, "#b8433a", "Highest 5%"],
];

const POINT_GROUPS: { label: string; color: string; types: string[] }[] = [
  { label: "Violence and robbery", color: "#b83a2e", types: ["Violence and sexual offences", "Robbery", "Possession of weapons"] },
  { label: "Burglary and theft", color: "#c98a0b", types: ["Burglary", "Other theft", "Theft from the person", "Bicycle theft", "Shoplifting", "Vehicle crime"] },
  { label: "Anti-social behaviour", color: "#7a6aa8", types: ["Anti-social behaviour"] },
  { label: "Damage, drugs, other", color: "#4a5a70", types: ["Criminal damage and arson", "Drugs", "Public order", "Other crime"] },
];

const empty = (): FC => ({ type: "FeatureCollection", features: [] });
const contains = (o: Bounds, i: Bounds) => o[0] <= i[0] && o[1] <= i[1] && o[2] >= i[2] && o[3] >= i[3];
const pad = (b: Bounds, f = 0.35): Bounds => {
  const dx = (b[2] - b[0]) * f, dy = (b[3] - b[1]) * f;
  return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy];
};
const tooBig = (b: Bounds) => b[2] - b[0] > 0.2 || b[3] - b[1] > 0.12;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

function circle([lon, lat]: [number, number], m: number, n = 96): [number, number][] {
  const dLat = m / 111320, dLon = m / (111320 * Math.cos((lat * Math.PI) / 180));
  return Array.from({ length: n + 1 }, (_, i) => {
    const a = (i / n) * 2 * Math.PI;
    return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)];
  });
}

function band(p: number | undefined): string {
  if (p == null) return "No data";
  return [...RAMP].reverse().find(([from]) => p >= from)![2];
}

function fmtMonth(iso: string | null) {
  if (!iso) return "";
  return new Date(`${iso.slice(0, 7)}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
}

function popupHtml(f: MapGeoJSONFeature, group: Group) {
  const p = f.properties as Record<string, number | string | undefined>;
  const row = (g: { k: Group; label: string }) => {
    const n = p[`${g.k}_n`], r = p[`${g.k}_r`], pc = p[`${g.k}_p`] as number | undefined;
    if (n == null) return "";
    const col = pc == null ? "#ccc" : [...RAMP].reverse().find(([from]) => pc >= from)![1];
    return `<tr${g.k === group ? ' class="on"' : ""}><td><i style="background:${col}"></i>${esc(g.label)}</td><td class="r">${esc(n)}</td><td class="r">${r ?? "–"}</td></tr>`;
  };
  return `<div class="cm-pop"><strong>Neighbourhood ${esc(p.c)}</strong><span>${esc(p.nm)}, about ${Number(p.pop ?? 0).toLocaleString("en-GB")} residents</span>
    <p><b>${esc(band(p[`${group}_p`] as number | undefined))}</b>${p[`${group}_p`] != null ? ` · higher than ${esc(p[`${group}_p`])}% of neighbourhoods in England and Wales` : ""}</p>
    <table><thead><tr><th></th><th class="r">Crimes</th><th class="r">Per 1,000</th></tr></thead><tbody>${GROUPS.map(row).join("")}</tbody></table>
    <em>Last 12 months. All crime excludes anti-social behaviour.</em></div>`;
}

export function CrimeMap({ center, bbox, geojson, label, rings = [], highlight }: {
  center: [number, number];
  bbox: Bounds | null;
  geojson: string | null;
  label: string;
  /** walking rings around the address, metres */
  rings?: number[];
  /** neighbourhood code holding the address, outlined */
  highlight?: string | null;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const popup = useRef<Popup | null>(null);
  const got = useRef<{ areas?: { bounds: Bounds; areas: FC; labels: FC }; points?: { bounds: Bounds; fc: FC } }>({});
  const busy = useRef(new Set<string>());
  const [group, setGroup] = useState<Group>("total");
  const [measure, setMeasure] = useState<Measure>("n");
  const [points, setPoints] = useState(false);
  const [state, setState] = useState<"loading" | "ok" | "zoom" | "error">("loading");
  const [last, setLast] = useState<string | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [keyOpen, setKeyOpen] = useState(true);
  const opts = useRef({ group, measure, points });

  useEffect(() => { if (window.innerWidth < 760) setKeyOpen(false); }, []); // eslint-disable-line react-hooks/set-state-in-effect

  const outer = rings.length ? Math.max(...rings) : 0;
  const initial: Bounds = outer
    ? (() => { const c = circle(center, outer * 1.1, 8); const xs = c.map((p) => p[0]), ys = c.map((p) => p[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] as Bounds; })()
    : bbox ?? [center[0] - 0.015, center[1] - 0.009, center[0] + 0.015, center[1] + 0.009];

  /* ---- paint expressions for the current group / measure */
  const applyStyle = useCallback((m: MlMap) => {
    const { group: g, measure: me, points: pts } = opts.current;
    if (!m.getLayer("cm-fill")) return;
    const p = ["get", `${g}_p`];
    m.setPaintProperty("cm-fill", "fill-color", ["case", ["!", ["has", `${g}_p`]], "rgba(0,0,0,0)",
      ["step", p, RAMP[0][1], ...RAMP.slice(1).flatMap(([from, col]) => [from, col])]] as never);
    const v = ["get", `${g}_${me}`];
    m.setLayoutProperty("cm-num", "text-field", ["case", ["!", ["has", `${g}_${me}`]], "",
      me === "r" ? ["number-format", v, { "max-fraction-digits": 0 }] : ["to-string", v]] as never);
    m.setFilter("cm-bubble", ["has", `${g}_${me}`]);
    m.setFilter("cm-bubble-shadow", ["has", `${g}_${me}`]);
    for (const id of ["cm-pt"]) m.setLayoutProperty(id, "visibility", pts ? "visible" : "none");
  }, []);

  /* ---- sources and layers (once per style load) */
  const addLayers = useCallback((m: MlMap) => {
    const src = (id: string, d: FC) => { if (!m.getSource(id)) m.addSource(id, { type: "geojson", data: d as never }); };
    src("cm-areas", got.current.areas?.areas ?? empty());
    src("cm-labels", got.current.areas?.labels ?? empty());
    src("cm-points", got.current.points?.fc ?? empty());
    // Under the basemap's road labels so street names stay readable over the shading.
    const firstSymbol = m.getStyle().layers.find((l) => l.type === "symbol")?.id;
    m.addLayer({ id: "cm-fill", type: "fill", source: "cm-areas", paint: { "fill-color": "rgba(0,0,0,0)", "fill-opacity": 0.62 } }, firstSymbol);
    m.addLayer({ id: "cm-line", type: "line", source: "cm-areas", paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.6, 16, 1.6], "line-opacity": 0.9 } }, firstSymbol);
    m.addLayer({ id: "cm-hover", type: "line", source: "cm-areas", filter: ["==", ["get", "c"], ""], paint: { "line-color": MAP_INK, "line-width": 2.2 } });
    if (highlight) m.addLayer({ id: "cm-home", type: "line", source: "cm-areas", filter: ["==", ["get", "c"], highlight], paint: { "line-color": MAP_INK, "line-width": 2, "line-dasharray": [2, 1.5] } });

    if (geojson) {
      src("cm-area", { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: JSON.parse(geojson) }] });
      m.addLayer({ id: "cm-area", type: "line", source: "cm-area", paint: { "line-color": "#5b3fd6", "line-width": 2.5 } });
    }
    if (rings.length) {
      src("cm-rings", { type: "FeatureCollection", features: rings.map((r, i) => ({ type: "Feature", properties: { i, l: `${r >= 1000 ? `${(r / 1000).toFixed(1)} km` : `${r} m`}, ${Math.round(r / 80)} min walk` }, geometry: { type: "LineString", coordinates: circle(center, r) } })) });
      m.addLayer({ id: "cm-rings", type: "line", source: "cm-rings", paint: { "line-color": ["match", ["get", "i"], 0, "#3fb6a8", "#6b8fe0"], "line-width": 2.4, "line-opacity": 0.9 } });
      m.addLayer({ id: "cm-rings-label", type: "symbol", source: "cm-rings", layout: { "symbol-placement": "line", "symbol-spacing": 400, "text-field": ["get", "l"], "text-font": ["Noto Sans Bold"], "text-size": 11, "text-offset": [0, -0.7], "text-keep-upright": true }, paint: { "text-color": "#33476a", "text-halo-color": "#fff", "text-halo-width": 1.6 } });
    }

    // Street-level crimes, last three months (optional).
    const pcol = ["match", ["get", "t"], ...POINT_GROUPS.flatMap((g) => g.types.flatMap((t) => [t, g.color])), "#4a5a70"] as never;
    m.addLayer({ id: "cm-pt", type: "circle", source: "cm-points", layout: { visibility: "none" }, paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 2.5, 17, 6], "circle-color": pcol, "circle-opacity": 0.85, "circle-stroke-width": 1, "circle-stroke-color": "#fff" } });

    // Count bubbles: white disc with a soft shadow and the number on top.
    const rad = ["interpolate", ["linear"], ["zoom"], 12, 11, 14, 17, 16, 22];
    m.addLayer({ id: "cm-bubble-shadow", type: "circle", source: "cm-labels", paint: { "circle-radius": rad as never, "circle-color": "rgba(19,35,58,0.28)", "circle-blur": 0.6, "circle-translate": [0, 2] } });
    m.addLayer({ id: "cm-bubble", type: "circle", source: "cm-labels", paint: { "circle-radius": rad as never, "circle-color": "#ffffff" } });
    m.addLayer({ id: "cm-num", type: "symbol", source: "cm-labels", layout: {
      "text-field": "", "text-font": ["Noto Sans Bold"], "text-size": ["interpolate", ["linear"], ["zoom"], 12, 10, 14, 13, 16, 15] as never,
      "text-allow-overlap": true, "text-ignore-placement": true,
    }, paint: { "text-color": MAP_INK } });

    // Address pin on top of everything.
    src("cm-pin", { type: "FeatureCollection", features: [{ type: "Feature", properties: { n: label }, geometry: { type: "Point", coordinates: center } }] });
    m.addLayer({ id: "cm-pin-halo", type: "circle", source: "cm-pin", paint: { "circle-radius": 14, "circle-color": "#5b3fd6", "circle-opacity": 0.18 } });
    m.addLayer({ id: "cm-pin", type: "circle", source: "cm-pin", paint: { "circle-radius": 8, "circle-color": "#5b3fd6", "circle-stroke-width": 3, "circle-stroke-color": "#fff" } });
    applyStyle(m);
  }, [applyStyle, center, geojson, highlight, label, rings]);

  /* ---- data for the current view */
  const refresh = useCallback(async () => {
    const m = map.current;
    if (!m) return;
    const b = m.getBounds();
    const view: Bounds = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    if (m.getZoom() < MIN_ZOOM || tooBig(view)) { setState("zoom"); return; }
    let want = pad(view);
    if (tooBig(want)) want = view;
    const q = want.map((v) => v.toFixed(5)).join(",");

    if (!(got.current.areas && contains(got.current.areas.bounds, view)) && !busy.current.has("areas")) {
      busy.current.add("areas");
      setState("loading");
      try {
        const r = await fetch(`/api/uk/map/crime-areas?bbox=${q}`);
        if (!r.ok) throw new Error(String(r.status));
        const d = (await r.json()) as { areas: FC; labels: FC; last: string | null };
        got.current.areas = { bounds: want, areas: d.areas, labels: d.labels };
        (m.getSource("cm-areas") as GeoJSONSource | undefined)?.setData(d.areas as never);
        (m.getSource("cm-labels") as GeoJSONSource | undefined)?.setData(d.labels as never);
        setLast(d.last);
        setState("ok");
      } catch { setState("error"); }
      finally { busy.current.delete("areas"); }
    } else if (got.current.areas) setState("ok");

    if (opts.current.points && !(got.current.points && contains(got.current.points.bounds, view)) && !busy.current.has("points")) {
      busy.current.add("points");
      try {
        const r = await fetch(`/api/uk/map/crime?bbox=${q}`);
        if (!r.ok) throw new Error(String(r.status));
        const d = (await r.json()) as FC & { months?: string[] };
        got.current.points = { bounds: want, fc: d };
        (m.getSource("cm-points") as GeoJSONSource | undefined)?.setData(d as never);
        setMonths(d.months ?? []);
      } catch { /* the shading still works without points */ }
      finally { busy.current.delete("points"); }
    }
  }, []);

  /* ---- create the map once */
  useEffect(() => {
    let cancelled = false;
    let m: MlMap | null = null;
    (async () => {
      const ml = (await import("maplibre-gl")).default;
      if (cancelled || !el.current) return;
      m = new ml.Map({
        container: el.current, style: STYLE, bounds: initial, fitBoundsOptions: { padding: 20, maxZoom: 15.5 },
        maxBounds: [[-11, 48.5], [4, 61.5]], minZoom: 9, attributionControl: { compact: true }, cooperativeGestures: true,
      });
      map.current = m;
      m.addControl(new ml.NavigationControl({ showCompass: false }), "bottom-right");
      m.addControl(new ml.FullscreenControl({ container: wrap.current! }), "top-right");
      m.addControl(new ml.GeolocateControl({ positionOptions: { enableHighAccuracy: false }, trackUserLocation: false }), "bottom-right");
      m.addControl(new ml.ScaleControl({ unit: "metric", maxWidth: 100 }), "bottom-left");
      m.on("style.load", () => addLayers(m!));
      m.on("moveend", () => refresh());
      m.once("load", () => refresh());

      popup.current = new ml.Popup({ offset: 8, maxWidth: "300px", closeButton: true });
      const hoverable = ["cm-fill", "cm-bubble"];
      for (const id of hoverable) {
        m.on("mousemove", id, (e) => {
          m!.getCanvas().style.cursor = "pointer";
          const c = e.features?.[0]?.properties?.c ?? "";
          m!.setFilter("cm-hover", ["==", ["get", "c"], c]);
        });
        m.on("mouseleave", id, () => { m!.getCanvas().style.cursor = ""; m!.setFilter("cm-hover", ["==", ["get", "c"], ""]); });
      }
      m.on("click", (e) => {
        const pt = m!.getLayoutProperty("cm-pt", "visibility") === "visible" ? m!.queryRenderedFeatures(e.point, { layers: ["cm-pt"] })[0] : undefined;
        if (pt) {
          const p = pt.properties as Record<string, string>;
          popup.current!.setLngLat(e.lngLat).setHTML(`<div class="cm-pop"><strong>${esc(p.t)}</strong><span>${esc(p.l)}, ${esc(p.m)}</span>${p.o ? `<p>${esc(p.o)}</p>` : ""}</div>`).addTo(m!);
          return;
        }
        const f = m!.queryRenderedFeatures(e.point, { layers: ["cm-bubble", "cm-fill"] })[0];
        if (!f) return;
        const code = f.properties?.c;
        const area = (got.current.areas?.areas.features as { properties: Record<string, unknown> }[] | undefined)?.find((x) => x.properties.c === code);
        popup.current!.setLngLat(e.lngLat).setHTML(popupHtml((area ?? f) as MapGeoJSONFeature, opts.current.group)).addTo(m!);
      });
    })();
    return () => { cancelled = true; m?.remove(); map.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    opts.current = { group, measure, points };
    const m = map.current;
    if (m?.isStyleLoaded()) applyStyle(m);
    if (points) refresh();
  }, [group, measure, points, applyStyle, refresh]);

  const period = last ? `${fmtMonth(new Date(Date.UTC(Number(last.slice(0, 4)), Number(last.slice(5, 7)) - 12, 1)).toISOString())} – ${fmtMonth(last)}` : "";

  return (
    <div className="cm" ref={wrap}>
      <div ref={el} className="cm-canvas" role="region" aria-label={`Crime map around ${label}`} />

      <div className="cm-bar">
        <label className="cm-sel">
          <span className="sr-only">Crime type</span>
          <select value={group} onChange={(e) => setGroup(e.target.value as Group)}>
            {GROUPS.map((g) => <option key={g.k} value={g.k}>{g.label}</option>)}
          </select>
        </label>
        <div className="cm-seg" role="group" aria-label="Number shown">
          <button type="button" aria-pressed={measure === "n"} onClick={() => setMeasure("n")}>Crimes</button>
          <button type="button" aria-pressed={measure === "r"} onClick={() => setMeasure("r")}>Per 1,000</button>
        </div>
        <label className="cm-chk">
          <input type="checkbox" checked={points} onChange={(e) => setPoints(e.target.checked)} />
          <span>Street-level crimes</span>
        </label>
        {period && <span className="cm-period">12 months, {period}</span>}
      </div>

      {state !== "ok" && (
        <div className="cm-toast" role="status">
          {state === "loading" ? "Loading neighbourhoods…" : state === "zoom" ? "Zoom in to see crime by neighbourhood" : "Crime data is unavailable right now"}
        </div>
      )}

      <div className="cm-key-wrap">
        {keyOpen && (
          <div className="cm-key">
            <b>{GROUPS.find((g) => g.k === group)!.label}, rate per 1,000 residents</b>
            <span className="cm-key-sub">vs every neighbourhood in England and Wales</span>
            <span className="cm-ramp" aria-hidden="true">{RAMP.map(([from, col]) => <i key={from} style={{ background: col }} />)}</span>
            <span className="cm-ramp-l"><span>Lower</span><span>Average</span><span>Higher</span></span>
            <span className="sr-only">{RAMP.map(([, , l]) => l).join(", ")}</span>
            <span className="cm-key-row"><i className="cm-key-bubble">12</i>{measure === "n" ? "Crimes recorded, last 12 months" : "Crimes per 1,000 residents"}</span>
            {highlight && <span className="cm-key-row"><i className="cm-key-home" />Neighbourhood holding this postcode</span>}
            {points && (
              <>
                <b style={{ marginTop: 6 }}>Street-level crimes{months.length ? `, ${fmtMonth(months[0])} – ${fmtMonth(months[months.length - 1])}` : ""}</b>
                {POINT_GROUPS.map((g) => <span key={g.label} className="cm-key-row"><i className="dot" style={{ background: g.color }} />{g.label}</span>)}
              </>
            )}
          </div>
        )}
        <button type="button" className="cm-key-toggle" aria-expanded={keyOpen} onClick={() => setKeyOpen(!keyOpen)}>{keyOpen ? "Hide key" : "Key"}</button>
      </div>
    </div>
  );
}
