"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GeoJSONSource, Map as MlMap } from "maplibre-gl";
import { CHOROPLETH_METRICS, formatChoropleth, type ChoroplethMetric } from "@/markets/uk/choropleth";

// Five classes from better to worse for residents; grey = no data.
const PALETTE = ["#1f6b4a", "#6aa36f", "#d9cf8f", "#dc9a5b", "#b83a2e"];
const NO_DATA = "#cfd6d0";
const EW_BOUNDS: [number, number, number, number] = [-5.8, 49.95, 1.8, 55.8];

type Shapes = { type: "FeatureCollection"; features: { type: "Feature"; properties: { code: string; name: string; slug: string }; geometry: unknown }[] };

function quantileBreaks(values: number[]): number[] {
  const s = [...values].sort((a, b) => a - b);
  return [0.2, 0.4, 0.6, 0.8].map((q) => s[Math.min(s.length - 1, Math.floor(q * s.length))]);
}

export function HomeMap() {
  const router = useRouter();
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const shapes = useRef<Shapes | null>(null);
  const [ready, setReady] = useState(false);
  const [metric, setMetric] = useState<ChoroplethMetric>(CHOROPLETH_METRICS[0]);
  const [values, setValues] = useState<Record<string, number> | null>(null);
  const [period, setPeriod] = useState<string | null>(null);
  const [hover, setHover] = useState<{ name: string; v: number | null; rank: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const breaks = useMemo(() => (values ? quantileBreaks(Object.values(values)) : []), [values]);
  // Ranking where 1 = best for residents
  const ranks = useMemo(() => {
    if (!values) return {} as Record<string, number>;
    const sorted = Object.entries(values).sort((a, b) => (metric.direction < 0 ? a[1] - b[1] : b[1] - a[1]));
    return Object.fromEntries(sorted.map(([code], i) => [code, i + 1]));
  }, [values, metric]);

  // Map + outlines, once.
  useEffect(() => {
    let cancelled = false;
    let m: MlMap | null = null;
    (async () => {
      const [ml, res] = await Promise.all([import("maplibre-gl"), fetch("/api/uk/map/lads")]);
      if (!res.ok) { setError("The map could not load. Reload the page to try again."); return; }
      shapes.current = (await res.json()) as Shapes;
      if (cancelled || !el.current) return;
      m = new ml.default.Map({
        container: el.current,
        style: "https://tiles.openfreemap.org/styles/positron",
        bounds: EW_BOUNDS,
        fitBoundsOptions: { padding: 12 },
        maxBounds: [[-25, 45], [15, 62]],
        attributionControl: { compact: true },
        cooperativeGestures: true,
      });
      map.current = m;
      m.addControl(new ml.default.NavigationControl({ showCompass: false }), "top-left");
      m.on("load", () => {
        if (!m) return;
        m.resize();
        m.fitBounds(EW_BOUNDS, { padding: 16, duration: 0 });
        m.addSource("lads", { type: "geojson", data: shapes.current as never, promoteId: "code" });
        const firstLabel = m.getStyle().layers.find((l) => l.type === "symbol")?.id;
        m.addLayer({ id: "lads-fill", type: "fill", source: "lads", paint: { "fill-color": ["coalesce", ["get", "color"], NO_DATA], "fill-opacity": ["case", ["boolean", ["feature-state", "hover"], false], 0.92, 0.72] } }, firstLabel);
        m.addLayer({ id: "lads-line", type: "line", source: "lads", paint: { "line-color": "#ffffff", "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2.5, 0.6] } }, firstLabel);
        let hovered: string | null = null;
        m.on("mousemove", "lads-fill", (e) => {
          const f = e.features?.[0];
          if (!f || !m) return;
          const code = String(f.properties.code);
          if (hovered && hovered !== code) m.setFeatureState({ source: "lads", id: hovered }, { hover: false });
          hovered = code;
          m.setFeatureState({ source: "lads", id: code }, { hover: true });
          m.getCanvas().style.cursor = "pointer";
          const p = f.properties as { name: string; v?: number; rank?: number };
          setHover({ name: p.name, v: p.v ?? null, rank: p.rank ?? null });
        });
        m.on("mouseleave", "lads-fill", () => {
          if (hovered && m) m.setFeatureState({ source: "lads", id: hovered }, { hover: false });
          hovered = null;
          if (m) m.getCanvas().style.cursor = "";
          setHover(null);
        });
        m.on("click", "lads-fill", (e) => {
          const slug = e.features?.[0]?.properties?.slug;
          if (slug) router.push(`/uk/area/${slug}`);
        });
        setReady(true);
      });
    })().catch(() => setError("The map could not load. Reload the page to try again."));
    return () => { cancelled = true; m?.remove(); map.current = null; };
  }, [router]);

  // Values for the chosen measure.
  useEffect(() => {
    let stale = false;
    fetch(`/api/uk/map/lad-values?metric=${encodeURIComponent(metric.id)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: { period: string | null; values: Record<string, number> }) => {
        if (stale) return;
        setValues(d.values);
        setPeriod(d.period);
        setError(null);
      })
      .catch(() => { if (!stale) setError("Figures for this measure are unavailable right now."); });
    return () => { stale = true; };
  }, [metric]);

  // Recolour when values arrive.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !values || !shapes.current) return;
    const cls = (v: number) => {
      let i = breaks.findIndex((b) => v < b);
      if (i < 0) i = 4;
      return metric.direction < 0 ? i : 4 - i;
    };
    const fc = {
      ...shapes.current,
      features: shapes.current.features.map((f) => {
        const v = values[f.properties.code];
        return { ...f, properties: { ...f.properties, v, rank: ranks[f.properties.code], color: v == null ? NO_DATA : PALETTE[cls(v)] } };
      }),
    };
    (m.getSource("lads") as GeoJSONSource | undefined)?.setData(fc as never);
  }, [ready, values, breaks, ranks, metric]);

  const total = values ? Object.keys(values).length : 0;
  const legend = breaks.length === 4
    ? [0, 1, 2, 3, 4].map((i) => {
        const lo = i === 0 ? null : breaks[i - 1];
        const hi = i === 4 ? null : breaks[i];
        const text = lo == null ? `Under ${formatChoropleth(metric, hi!)}` : hi == null ? `${formatChoropleth(metric, lo)} and over` : `${formatChoropleth(metric, lo)} to ${formatChoropleth(metric, hi)}`;
        return { text, color: PALETTE[metric.direction < 0 ? i : 4 - i] };
      })
    : [];

  return (
    <div className="home-map">
      <div className="chips" role="group" aria-label="Measure shown on the map">
        {CHOROPLETH_METRICS.map((m) => (
          <button key={m.id} type="button" className="chip" aria-pressed={m.id === metric.id} onClick={() => setMetric(m)}>{m.label}</button>
        ))}
      </div>
      <div className="map home-map-canvas" role="region" aria-label={`Map of England and Wales: ${metric.label.toLowerCase()} by local authority`}>
        <div ref={el} className="canvas" />
        <div className="home-map-info" aria-live="polite">
          {hover ? (
            <>
              <strong>{hover.name}</strong>
              <span className="num">{hover.v == null ? "No data" : formatChoropleth(metric, hover.v)}</span>
              {hover.rank != null && <span className="m-src">{`Ranked ${ordinal(hover.rank)} of ${total}, where 1st is best for residents`}</span>}
              <span className="m-src">Click to open the area report</span>
            </>
          ) : (
            <>
              <strong>{metric.label}</strong>
              <span className="m-src">{metric.unitNote}{period ? `, ${new Date(period).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" })}` : ""}</span>
              <span className="m-src">Hover over an area for its figure</span>
            </>
          )}
        </div>
        {legend.length > 0 && (
          <div className="map-legend home-legend" aria-label="Map key">
            {legend.map((l) => <span key={l.text}><i style={{ background: l.color }} />{l.text}</span>)}
            <span><i style={{ background: NO_DATA }} />No data</span>
          </div>
        )}
        {error && <div className="map-toast">{error}</div>}
      </div>
    </div>
  );
}

function ordinal(n: number) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
