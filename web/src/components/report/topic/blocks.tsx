import type { CSSProperties, ReactNode } from "react";
import type { Fmt } from "./Shell";

// Building blocks shared by the topic pages, drawn in the street-plate style.

export function Block({ id, title, note, children }: { id: string; title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="tp-block" aria-labelledby={`tp-${id}`}>
      <h2 id={`tp-${id}`}>{title}</h2>
      {note && <p className="tp-note">{note}</p>}
      {children}
    </section>
  );
}

export interface DotRow {
  k: string; label: string; here: number; other?: number | null; extra?: ReactNode; rank?: ReactNode;
  /** too few cases for the figure to be steady: drawn faded */
  faint?: boolean;
}

/** Column headings, so every number on screen says what it is. `unit` sits over the labels,
 *  `here`/`other` name the dot and the ring (and head their columns), `extra` and `rank` head the columns after them. */
export interface DotHead { unit: string; here: string; other?: string; extra?: string; rank?: string }

/** One row per item: filled dot = this area, ring = the comparison area, joined by a line.
 *  `highIs` colours the dot when it is clearly above the ring. */
export function DotRows({ rows, fmt, head, highIs = "neutral" }: { rows: DotRow[]; fmt: Fmt; head: DotHead; highIs?: "bad" | "good" | "neutral" }) {
  const max = Math.max(...rows.map((r) => Math.max(r.here, r.other ?? 0)), 1e-9);
  const pos = (x: number) => `${(Math.max(0, x) / max) * 100}%`;
  const hasOther = head.other != null && rows.some((r) => r.other != null);
  const hasExtra = head.extra != null && rows.some((r) => r.extra != null);
  const hasRank = head.rank != null && rows.some((r) => r.rank != null);
  const nums = ["4.6em", hasOther && "4.6em", hasExtra && "3.8em", hasRank && "5.4em"].filter(Boolean).join(" ");
  return (
    <ol className="tp-dots" style={{ "--tp-nums": nums } as CSSProperties}>
      <li className="tp-dh" aria-hidden="true">
        <span className="tp-t">{head.unit}</span>
        <span className="tp-key">
          <span><i className="tp-kd" />{head.here}</span>
          {hasOther && <span><i className="tp-kr" />{head.other}</span>}
        </span>
        <span className="tp-v">{head.here}</span>
        {hasOther && <span className="tp-n">{head.other}</span>}
        {hasExtra && <span className="tp-n">{head.extra}</span>}
        {hasRank && <span className="tp-n">{head.rank}</span>}
      </li>
      {rows.map((r) => {
        const up = r.other != null && r.here > r.other * 1.15, down = r.other != null && r.here < r.other * 0.85;
        const tone = highIs === "neutral" ? "" : (up && highIs === "bad") || (down && highIs === "good") ? " bad" : (down && highIs === "bad") || (up && highIs === "good") ? " good" : "";
        const said = `${r.label}: ${fmt(r.here)} ${head.unit.toLowerCase()} in ${head.here.toLowerCase()}${r.other != null && head.other ? `, ${fmt(r.other)} in ${head.other}` : ""}${r.extra != null && head.extra ? `; ${head.extra.toLowerCase()}: ${typeof r.extra === "string" ? r.extra : ""}` : ""}`;
        return (
          <li key={r.k} title={said} className={r.faint ? "few" : undefined}>
            <span className="tp-t">{r.label}</span>
            <span className="tp-track" aria-hidden="true">
              {r.other != null && <span className="tp-link" style={{ left: pos(Math.min(r.here, r.other)), width: `${(Math.abs(r.here - r.other) / max) * 100}%` }} />}
              {r.other != null && <span className="tp-ring" style={{ left: pos(r.other) }} />}
              <span className={`tp-dot${tone}`} style={{ left: pos(r.here) }} />
            </span>
            <span className="tp-v">{fmt(r.here)}</span>
            {hasOther && <span className="tp-n">{r.other != null ? fmt(r.other) : "–"}</span>}
            {hasExtra && <span className="tp-n">{r.extra ?? "–"}</span>}
            {hasRank && <span className="tp-n">{r.rank ?? "–"}</span>}
          </li>
        );
      })}
    </ol>
  );
}

/** Census-style shares: bar for this area, tick for the comparison area. `other` names the tick
 *  and heads the right-hand column. */
export function ShareRows({ rows, other, unit = "Share", max = 100 }: { rows: { label: string; here: number; other?: number | null }[]; other?: string | null; unit?: string; max?: number }) {
  const m = Math.max(max === 100 ? 0 : max, ...rows.map((r) => Math.max(r.here, r.other ?? 0)), 1);
  const hasOther = !!other && rows.some((r) => r.other != null);
  const p = (x: number) => `${x < 1 && x > 0 ? x.toFixed(1) : Math.round(x)}%`;
  return (
    <ul className={`tp-shares${hasOther ? " o" : ""}`}>
      <li className="tp-sh" aria-hidden="true">
        <span className="tp-sl">{unit}</span>
        <span className="tp-key">
          <span><i className="tp-kb" />This area</span>
          {hasOther && <span><i className="tp-kt" />{other}</span>}
        </span>
        <span className="tp-sv">This area</span>
        {hasOther && <span className="tp-so">{other}</span>}
      </li>
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${p(r.here)} in this area${hasOther && r.other != null ? `, ${p(r.other)} in ${other}` : ""}`}>
          <span className="tp-sl">{r.label}</span>
          <span className="tp-sb" aria-hidden="true">
            <i style={{ width: `${(r.here / m) * 100}%` }} />
            {r.other != null && <em style={{ left: `${(r.other / m) * 100}%` }} />}
          </span>
          <span className="tp-sv">{p(r.here)}</span>
          {hasOther && <span className="tp-so">{r.other != null ? p(r.other) : "–"}</span>}
        </li>
      ))}
    </ul>
  );
}

export function Facts({ items }: { items: { k: string; v: ReactNode; note?: ReactNode }[] }) {
  const shown = items.filter((i) => i.v != null && i.v !== "");
  if (!shown.length) return null;
  return (
    <dl className="tp-facts">
      {shown.map((i) => (
        <div key={i.k}>
          <dt>{i.k}</dt>
          <dd><b>{i.v}</b>{i.note && <span>{i.note}</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Census JSON {category: count} → shares in %, dropping totals and sub-categories. */
export function shares(j: unknown, opts: { exclude?: RegExp; top?: number; order?: string[]; rename?: (k: string) => string } = {}): Map<string, number> {
  const out = new Map<string, number>();
  if (!j || typeof j !== "object") return out;
  const e = Object.entries(j as Record<string, unknown>)
    .filter(([k, v]) => typeof v === "number" && !/total/i.test(k) && !k.includes(":") && !opts.exclude?.test(k)) as [string, number][];
  const sum = e.reduce((s, [, v]) => s + v, 0);
  if (!sum) return out;
  let rows = e.map(([k, v]) => [opts.rename ? opts.rename(k) : k, (v / sum) * 100] as [string, number]);
  if (opts.order) rows.sort((a, b) => opts.order!.indexOf(a[0]) - opts.order!.indexOf(b[0]));
  else rows.sort((a, b) => b[1] - a[1]);
  if (opts.top) rows = rows.slice(0, opts.top);
  for (const [k, v] of rows) out.set(k, (out.get(k) ?? 0) + v);
  return out;
}

/** This area's shares against the comparison area's, in this area's order. */
export function compareShares(here: unknown, other: unknown, opts: Parameters<typeof shares>[1] = {}) {
  const a = shares(here, opts), b = shares(other, { ...opts, top: undefined });
  return [...a].map(([label, v]) => ({ label, here: v, other: b.get(label) ?? null }));
}
