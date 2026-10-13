import type { ReactNode } from "react";

/** Colour for a "goodness" percentile (already flipped so higher = better). */
export function goodColor(p: number): string {
  return p >= 60 ? "var(--good)" : p >= 35 ? "var(--mid)" : "var(--bad)";
}

/** Score bar (0–100, higher = better): a filled track with quarter notches. */
export function Strip({ p, label }: { p: number | null; label?: string }) {
  if (p == null) return <div className="strip-empty" aria-hidden="true" />;
  const v = Math.max(0, Math.min(100, p));
  return <div className="strip" style={{ "--p": v, "--pc": goodColor(v) } as React.CSSProperties} role="img" aria-label={label ?? `${Math.round(v)} out of 100`} />;
}

export interface CompareRow { label: string; v: number; text: string; self?: boolean }

/** Plain comparison: this area against its local authority and nation, as bars from zero
 *  (from a centre axis when any value is negative). The area's bar carries the good/bad colour. */
export function Compare({ rows, good }: { rows: CompareRow[]; good: number | null }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.v)), 1e-9);
  const signed = rows.some((r) => r.v < 0);
  const c = good == null ? "var(--water)" : goodColor(good);
  return (
    <div className={`cmp${signed ? " signed" : ""}`}>
      {rows.map((r) => {
        const w = (Math.abs(r.v) / max) * (signed ? 50 : 100);
        const style = signed ? { left: r.v < 0 ? `${50 - w}%` : "50%", width: `${w}%` } : { width: `${w}%` };
        return (
          <div className={`cmp-row${r.self ? " self" : ""}`} key={r.label}>
            <span className="cmp-k">{r.label}</span>
            <span className="cmp-b"><span style={{ ...style, ...(r.self ? { background: c } : {}) }} /></span>
            <span className="cmp-v num">{r.text}</span>
          </div>
        );
      })}
    </div>
  );
}

export function Metric({ name, value, p, compare, pLabel, note, src }: {
  name: string;
  value: ReactNode;
  /** Goodness 0–100 (higher = better), shown as a score bar when there is nothing to compare against. */
  p?: number | null;
  /** This area against wider areas; replaces the score bar. Colour follows `p` (none = neutral). */
  compare?: { rows: CompareRow[]; neutral?: boolean };
  pLabel?: string;
  note?: ReactNode;
  src?: ReactNode;
}) {
  return (
    <div className="metric">
      <div className="m-head">
        <span className="m-name">{name}</span>
        <span className="m-val">{value}</span>
      </div>
      {compare && compare.rows.length > 1
        ? <Compare rows={compare.rows} good={compare.neutral ? null : p ?? null} />
        : p != null && !compare && <Strip p={p} label={pLabel} />}
      {note && <p className="m-note">{note}</p>}
      {src && <p className="m-src">{src}</p>}
    </div>
  );
}

export function Bars({ rows, format = (v) => String(v), max }: { rows: [string, number][]; format?: (v: number) => string; max?: number }) {
  const m = max ?? Math.max(...rows.map((r) => r[1]), 1);
  return (
    <div className="bars">
      {rows.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span>{k}</span>
          <span className="b"><span style={{ width: `${Math.max(0, (v / m) * 100)}%` }} /></span>
          <span className="num v">{format(v)}</span>
        </div>
      ))}
    </div>
  );
}

export function Flag({ k, v, tone, s }: { k: string; v: ReactNode; tone: "g" | "m" | "b" | "n"; s?: ReactNode }) {
  return (
    <div className="flag">
      <span className="f-k">{k}</span>
      <span className="f-v"><span className={`dot ${tone}`} />{v}</span>
      {s && <span className="f-s">{s}</span>}
    </div>
  );
}

export function Ad({ kind, label }: { kind: "leader" | "inline" | "side"; label: string }) {
  // Reserved box; the AdSense unit mounts here once the CMP has consent (PLAN §5.5).
  return <div className={`ad ${kind}`} aria-hidden="true">{label}</div>;
}

interface Series { label: string; points: { x: string; y: number }[]; dashed?: boolean }

/** Small multi-line chart in SVG; first series is the area, later ones are context. */
export function LineChart({ series, format, ariaLabel, height = 220 }: { series: Series[]; format: (v: number) => string; ariaLabel: string; height?: number }) {
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort();
  const ys = series.flatMap((s) => s.points.map((p) => p.y));
  if (xs.length < 2 || !ys.length) return null;
  const W = 640, H = height, L = 58, R = 14, T = 16, B = 28;
  let min = Math.min(...ys), max = Math.max(...ys);
  const pad = (max - min) * 0.12 || max * 0.1 || 1;
  min = Math.max(0, min - pad); max = max + pad;
  const x = (k: string) => L + (xs.indexOf(k) * (W - L - R)) / (xs.length - 1);
  const y = (v: number) => T + ((max - v) * (H - T - B)) / (max - min);
  const ticks = [0, 1, 2, 3].map((i) => min + ((max - min) * i) / 3);
  const step = Math.ceil(xs.length / 6);
  const main = series[0];
  const last = main.points[main.points.length - 1];
  return (
    <figure style={{ margin: 0 }}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--line)" />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--ink-2)">{format(v)}</text>
          </g>
        ))}
        {xs.map((k, i) => (i % step === 0 || i === xs.length - 1 ? (
          <text key={k} x={x(k)} y={H - 8} textAnchor="middle" fontSize="11" fill="var(--ink-2)">{k.slice(0, 4)}</text>
        ) : null))}
        {series.slice(1).map((s) => (
          <path key={s.label} d={s.points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)} ${y(p.y).toFixed(1)}`).join("")} fill="none" stroke="var(--ink-2)" strokeWidth="2" strokeDasharray="5 4" />
        ))}
        <path d={main.points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)} ${y(p.y).toFixed(1)}`).join("")} fill="none" stroke="var(--brand)" strokeWidth="3" strokeLinejoin="round" />
        {last && (
          <g className="chart-last">
            <circle cx={x(last.x)} cy={y(last.y)} r="5" fill="var(--brand)" />
            <text x={x(last.x) - 8} y={y(last.y) - 10} textAnchor="end" fontSize="12" fontWeight="700" fill="var(--ink)">{format(last.y)}</text>
          </g>
        )}
        {xs.map((k, i) => {
          // Hover column: CSS reveals the guide, dots and tooltip for this x (no client JS needed).
          const cx = x(k), colW = (W - L - R) / (xs.length - 1);
          const hits = series.map((s, si) => ({ s, si, pt: s.points.find((p) => p.x === k) })).filter((h) => h.pt);
          const lines = hits.map((h) => (series.length > 1 ? `${h.s.label}: ` : "") + format(h.pt!.y));
          const bw = Math.max(k.length, ...lines.map((l) => l.length)) * 6.6 + 20, bh = 22 + lines.length * 17;
          const bx = cx + 10 + bw > W - R ? cx - 10 - bw : cx + 10;
          const by = T;
          return (
            <g key={k} className="chart-hov">
              <rect x={i === 0 ? L : cx - colW / 2} y={T} width={i === 0 || i === xs.length - 1 ? colW / 2 : colW} height={H - T - B} fill="transparent" />
              <g className="chart-tip" pointerEvents="none">
                <line x1={cx} x2={cx} y1={T} y2={H - B} stroke="var(--ink-2)" strokeDasharray="3 3" />
                {hits.map((h) => <circle key={h.si} cx={cx} cy={y(h.pt!.y)} r="5" fill={h.si ? "var(--ink-2)" : "var(--brand)"} stroke="var(--surface)" strokeWidth="2" />)}
                <rect x={bx} y={by} width={bw} height={bh} rx="6" fill="var(--surface)" stroke="var(--line)" />
                <text x={bx + 10} y={by + 17} fontSize="12" fontWeight="700" fill="var(--ink)">{k}</text>
                {lines.map((l, li) => <text key={li} x={bx + 10} y={by + 34 + li * 17} fontSize="12" fill={hits[li].si ? "var(--ink-2)" : "var(--ink)"}>{l}</text>)}
              </g>
            </g>
          );
        })}
      </svg>
      {series.length > 1 && (
        <figcaption className="legend">
          {series.map((s, i) => <span key={s.label}><i className={i ? "dash" : ""} />{s.label}</span>)}
        </figcaption>
      )}
    </figure>
  );
}
