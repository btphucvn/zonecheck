"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useCallback, useEffect, useRef, useState } from "react";
import type { GeoJSONSource, Map as MlMap, Popup } from "maplibre-gl";
import { MAP_INK } from "./mapIcons";

// Topic map: every neighbourhood (LSOA) shaded by one metric against all neighbourhoods in
// England and Wales, with the value in a bubble, walking rings and the address pin. Same
// visual language as the crime map; the metric list comes from the topic page.

export type MapFmt = "money" | "pct" | "num0" | "num1" | "dist" | "ugm3" | "decile";
export interface MapMetric { id: string; label: string; fmt: MapFmt; /** -1 lower is better, 1 higher is better, 0 neutral */ dir: -1 | 0 | 1; unit?: string }

type FC = { type: "FeatureCollection"; features: { properties: Record<string, unknown> }[] };
type Bounds = [number, number, number, number];

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const MIN_ZOOM = 12.3;
/** worst → best (directional metrics, by goodness percentile) */
const GOOD = ["#b8433a", "#e57f66", "#f3b886", "#efe3b2", "#a6cf8b", "#4f9a6a"];
/** low → high (neutral metrics such as price) */
const SEQ = ["#eef2f7", "#c9d7e8", "#9fb8d6", "#6f93c0", "#456fa6", "#26507f"];
const STEPS = [0, 20, 40, 60, 80, 95];

export function fmtMap(v: number, f: MapFmt): string {
  switch (f) {
    case "money": return v >= 1e6 ? `£${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}m` : v >= 1e4 ? `£${Math.round(v / 1e3)}k` : `£${Math.round(v).toLocaleString("en-GB")}`;
    case "pct": return `${Math.round(v)}%`;
    case "num1": return v.toLocaleString("en-GB", { maximumFractionDigits: 1 });
    case "dist": return v >= 1000 ? `${(v / 1000).toFixed(1)} km` : `${Math.round(v / 10) * 10} m`;
    case "ugm3": return v.toFixed(1);
    case "decile": return String(Math.round(v));
    default: return Math.round(v).toLocaleString("en-GB");
  }
}

const empty = (): FC => ({ type: "FeatureCollection", features: [] });
const contains = (o: Bounds, i: Bounds) => o[0] <= i[0] && o[1] <= i[1] && o[2] >= i[2] && o[3] >= i[3];
const pad = (b: Bounds, f = 0.35): Bounds => { const dx = (b[2] - b[0]) * f, dy = (b[3] - b[1]) * f; return [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy]; };
const tooBig = (b: Bounds) => b[2] - b[0] > 0.2 || b[3] - b[1] > 0.12;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

function circle([lon, lat]: [number, number], m: number, n = 96): [number, number][] {
  const dLat = m / 111320, dLon = m / (111320 * Math.cos((lat * Math.PI) / 180));
  return Array.from({ length: n + 1 }, (_, i) => { const a = (i / n) * 2 * Math.PI; return [lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]; });
}

const goodness = (p: number, dir: number) => (dir < 0 ? 100 - p : p);
const colourOf = (p: number | undefined, dir: number) => {
  if (p == null) return "#ccc";
  const x = dir === 0 ? p : goodness(p, dir);
  const i = [...STEPS].reverse().findIndex((s) => x >= s);
  return (dir === 0 ? SEQ : GOOD)[STEPS.length - 1 - i];
};

export function MetricMap({ center, bbox, geojson, label, metrics, rings = [], highlight, area = "neighbourhood" }: {
  center: [number, number];
  bbox: Bounds | null;
  geojson: string | null;
  label: string;
  metrics: MapMetric[];
  rings?: number[];
  /** neighbourhood code holding the address, outlined */
  highlight?: string | null;
  area?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const popup = useRef<Popup | null>(null);
  const got = useRef<{ bounds: Bounds; areas: FC; labels: FC } | null>(null);
  const busy = useRef(false);
  const [idx, setIdx] = useState(0);
  const [state, setState] = useState<"loading" | "ok" | "zoom" | "error">("loading");
  const [keyOpen, setKeyOpen] = useState(true);
  const idxRef = useRef(0);

  useEffect(() => { if (window.innerWidth < 760) setKeyOpen(false); }, []); // eslint-disable-line react-hooks/set-state-in-effect

  const outer = rings.length ? Math.max(...rings) : 0;
  const initial: Bounds = outer
    ? (() => { const c = circle(center, outer * 1.1, 8); const xs = c.map((p) => p[0]), ys = c.map((p) => p[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] as Bounds; })()
    : bbox ?? [center[0] - 0.015, center[1] - 0.009, center[0] + 0.015, center[1] + 0.009];

  const applyStyle = useCallback((m: MlMap) => {
    if (!m.getLayer("mm-fill")) return;
    const i = idxRef.current, mt = metrics[i];
    const p = ["get", `m${i}_p`];
    const x = mt.dir < 0 ? ["-", 100, p] : p;
    const ramp = mt.dir === 0 ? SEQ : GOOD;
    m.setPaintProperty("mm-fill", "fill-color", ["case", ["!", ["has", `m${i}_p`]], "rgba(0,0,0,0)",
      ["step", x, ramp[0], ...STEPS.slice(1).flatMap((s, k) => [s, ramp[k + 1]])]] as never);
    m.setLayoutProperty("mm-num", "text-field", ["coalesce", ["get", `m${i}_s`], ""] as never);
    m.setFilter("mm-bubble", ["has", `m${i}_s`]);
    m.setFilter("mm-bubble-shadow", ["has", `m${i}_s`]);
  }, [metrics]);

  const addLayers = useCallback((m: MlMap) => {
    const src = (id: string, d: unknown) => { if (!m.getSource(id)) m.addSource(id, { type: "geojson", data: d as never }); };
    src("mm-areas", got.current?.areas ?? empty());
    src("mm-labels", got.current?.labels ?? empty());
    const firstSymbol = m.getStyle().layers.find((l) => l.type === "symbol")?.id;
    m.addLayer({ id: "mm-fill", type: "fill", source: "mm-areas", paint: { "fill-color": "rgba(0,0,0,0)", "fill-opacity": 0.62 } }, firstSymbol);
    m.addLayer({ id: "mm-line", type: "line", source: "mm-areas", paint: { "line-color": "#fff", "line-width": ["interpolate", ["linear"], ["zoom"], 12, 0.6, 16, 1.6], "line-opacity": 0.9 } }, firstSymbol);
    m.addLayer({ id: "mm-hover", type: "line", source: "mm-areas", filter: ["==", ["get", "c"], ""], paint: { "line-color": MAP_INK, "line-width": 2.2 } });
    if (highlight) m.addLayer({ id: "mm-home", type: "line", source: "mm-areas", filter: ["==", ["get", "c"], highlight], paint: { "line-color": MAP_INK, "line-width": 2, "line-dasharray": [2, 1.5] } });
    if (geojson) {
      src("mm-area", { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: JSON.parse(geojson) }] });
      m.addLayer({ id: "mm-area", type: "line", source: "mm-area", paint: { "line-color": "#5b3fd6", "line-width": 2.5 } });
    }
    if (rings.length) {
      src("mm-rings", { type: "FeatureCollection", features: rings.map((r, i) => ({ type: "Feature", properties: { i, l: `${r >= 1000 ? `${(r / 1000).toFixed(1)} km` : `${r} m`}, ${Math.round(r / 80)} min walk` }, geometry: { type: "LineString", coordinates: circle(center, r) } })) });
      m.addLayer({ id: "mm-rings", type: "line", source: "mm-rings", paint: { "line-color": ["match", ["get", "i"], 0, "#3fb6a8", "#6b8fe0"], "line-width": 2.4, "line-opacity": 0.9 } });
      m.addLayer({ id: "mm-rings-label", type: "symbol", source: "mm-rings", layout: { "symbol-placement": "line", "symbol-spacing": 400, "text-field": ["get", "l"], "text-font": ["Noto Sans Bold"], "text-size": 11, "text-offset": [0, -0.7], "text-keep-upright": true }, paint: { "text-color": "#33476a", "text-halo-color": "#fff", "text-halo-width": 1.6 } });
    }
    const rad = ["interpolate", ["linear"], ["zoom"], 12, 12, 14, 18, 16, 23];
    m.addLayer({ id: "mm-bubble-shadow", type: "circle", source: "mm-labels", paint: { "circle-radius": rad as never, "circle-color": "rgba(19,35,58,0.28)", "circle-blur": 0.6, "circle-translate": [0, 2] } });
    m.addLayer({ id: "mm-bubble", type: "circle", source: "mm-labels", paint: { "circle-radius": rad as never, "circle-color": "#fff" } });
    m.addLayer({ id: "mm-num", type: "symbol", source: "mm-labels", layout: {
      "text-field": "", "text-font": ["Noto Sans Bold"], "text-size": ["interpolate", ["linear"], ["zoom"], 12, 9, 14, 11.5, 16, 13.5] as never,
      "text-allow-overlap": true, "text-ignore-placement": true,
    }, paint: { "text-color": MAP_INK } });
    src("mm-pin", { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: center } }] });
    m.addLayer({ id: "mm-pin-halo", type: "circle", source: "mm-pin", paint: { "circle-radius": 14, "circle-color": "#5b3fd6", "circle-opacity": 0.18 } });
    m.addLayer({ id: "mm-pin", type: "circle", source: "mm-pin", paint: { "circle-radius": 8, "circle-color": "#5b3fd6", "circle-stroke-width": 3, "circle-stroke-color": "#fff" } });
    applyStyle(m);
  }, [applyStyle, center, geojson, highlight, rings]);

  const refresh = useCallback(async () => {
    const m = map.current;
    if (!m) return;
    const b = m.getBounds();
    const view: Bounds = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    if (m.getZoom() < MIN_ZOOM || tooBig(view)) { setState("zoom"); return; }
    if (got.current && contains(got.current.bounds, view)) { setState("ok"); return; }
    if (busy.current) return;
    let want = pad(view);
    if (tooBig(want)) want = view;
    busy.current = true;
    setState("loading");
    try {
      const r = await fetch(`/api/uk/map/metric-areas?m=${metrics.map((x) => x.id).join(",")}&bbox=${want.map((v) => v.toFixed(5)).join(",")}`);
      if (!r.ok) throw new Error(String(r.status));
      const d = (await r.json()) as { areas: FC; labels: FC };
      // Bubble text is formatted here once, so the map only swaps which property it shows.
      for (const f of d.labels.features) metrics.forEach((mt, i) => { const v = f.properties[`m${i}_v`]; if (typeof v === "number") f.properties[`m${i}_s`] = fmtMap(v, mt.fmt); });
      got.current = { bounds: want, areas: d.areas, labels: d.labels };
      (m.getSource("mm-areas") as GeoJSONSource | undefined)?.setData(d.areas as never);
      (m.getSource("mm-labels") as GeoJSONSource | undefined)?.setData(d.labels as never);
      setState("ok");
    } catch { setState("error"); }
    finally { busy.current = false; }
  }, [metrics]);

  useEffect(() => {
    let cancelled = false;
    let m: MlMap | null = null;
    (async () => {
      const ml = (await import("maplibre-gl")).default;
      if (cancelled || !el.current) return;
      m = new ml.Map({ container: el.current, style: STYLE, bounds: initial, fitBoundsOptions: { padding: 20, maxZoom: 15.5 },
        maxBounds: [[-11, 48.5], [4, 61.5]], minZoom: 9, attributionControl: { compact: true }, cooperativeGestures: true });
      map.current = m;
      m.addControl(new ml.NavigationControl({ showCompass: false }), "bottom-right");
      m.addControl(new ml.FullscreenControl({ container: wrap.current! }), "top-right");
      m.addControl(new ml.ScaleControl({ unit: "metric", maxWidth: 100 }), "bottom-left");
      m.on("style.load", () => addLayers(m!));
      m.on("moveend", () => refresh());
      m.once("load", () => refresh());
      popup.current = new ml.Popup({ offset: 8, maxWidth: "300px" });
      for (const id of ["mm-fill", "mm-bubble"]) {
        m.on("mousemove", id, (e) => { m!.getCanvas().style.cursor = "pointer"; m!.setFilter("mm-hover", ["==", ["get", "c"], e.features?.[0]?.properties?.c ?? ""]); });
        m.on("mouseleave", id, () => { m!.getCanvas().style.cursor = ""; m!.setFilter("mm-hover", ["==", ["get", "c"], ""]); });
      }
      m.on("click", (e) => {
        const f = m!.queryRenderedFeatures(e.point, { layers: ["mm-bubble", "mm-fill"] })[0];
        if (!f) return;
        const p = (got.current?.areas.features.find((x) => x.properties.c === f.properties?.c)?.properties ?? f.properties) as Record<string, unknown>;
        const rows = metrics.map((mt, i) => {
          const v = p[`m${i}_v`] as number | undefined, pc = p[`m${i}_p`] as number | undefined;
          if (v == null) return "";
          return `<tr${i === idxRef.current ? ' class="on"' : ""}><td><i style="background:${colourOf(pc, mt.dir)}"></i>${esc(mt.label)}</td><td class="r">${esc(fmtMap(v, mt.fmt))}</td><td class="r">${pc != null ? `${pc}%` : "–"}</td></tr>`;
        }).join("");
        popup.current!.setLngLat(e.lngLat).setHTML(`<div class="cm-pop"><strong>Neighbourhood ${esc(p.c)}</strong><span>${esc(p.nm)}, about ${Number(p.pop ?? 0).toLocaleString("en-GB")} residents</span>
          <table><thead><tr><th></th><th class="r">Value</th><th class="r">Higher than</th></tr></thead><tbody>${rows}</tbody></table>
          <em>Higher than: share of neighbourhoods in England and Wales with a lower value.</em></div>`).addTo(m!);
      });
    })();
    return () => { cancelled = true; m?.remove(); map.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    idxRef.current = idx;
    const m = map.current;
    if (m?.isStyleLoaded()) applyStyle(m);
  }, [idx, applyStyle]);

  const mt = metrics[idx];
  return (
    <div className="cm" ref={wrap}>
      <div ref={el} className="cm-canvas" role="region" aria-label={`Map of ${mt.label.toLowerCase()} around ${label}`} />
      {metrics.length > 1 && (
        <div className="cm-bar">
          <label className="cm-sel">
            <span className="sr-only">Shown on the map</span>
            <select value={idx} onChange={(e) => setIdx(Number(e.target.value))}>
              {metrics.map((x, i) => <option key={x.id} value={i}>{x.label}</option>)}
            </select>
          </label>
        </div>
      )}
      {state !== "ok" && (
        <div className="cm-toast" role="status">
          {state === "loading" ? "Loading neighbourhoods…" : state === "zoom" ? `Zoom in to see each ${area}` : "Map data is unavailable right now"}
        </div>
      )}
      <div className="cm-key-wrap">
        {keyOpen && (
          <div className="cm-key">
            <b>{mt.label}{mt.unit ? `, ${mt.unit}` : ""}</b>
            <span className="cm-key-sub">vs every neighbourhood in England and Wales</span>
            <span className="cm-ramp" aria-hidden="true">{(mt.dir === 0 ? SEQ : GOOD).map((c) => <i key={c} style={{ background: c }} />)}</span>
            <span className="cm-ramp-l">{mt.dir === 0 ? <><span>Lower</span><span>Higher</span></> : <><span>Worse</span><span>Better</span></>}</span>
            <span className="cm-key-row"><i className="cm-key-bubble">{fmtMap(mt.fmt === "money" ? 450000 : mt.fmt === "pct" ? 64 : mt.fmt === "dist" ? 420 : 12, mt.fmt)}</i>Value for the neighbourhood</span>
            {highlight && <span className="cm-key-row"><i className="cm-key-home" />Neighbourhood holding this postcode</span>}
          </div>
        )}
        <button type="button" className="cm-key-toggle" aria-expanded={keyOpen} onClick={() => setKeyOpen(!keyOpen)}>{keyOpen ? "Hide key" : "Key"}</button>
      </div>
    </div>
  );
}
