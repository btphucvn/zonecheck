import Link from "next/link";
import type { ReactNode } from "react";
import type { NeighbourValue } from "@/server/topic";

// Topic detail page frame ("street plate"): map band with the postcode plate mounted on it,
// the answer in one sentence, an Ordnance Survey scale bar as the ruler for the key figure,
// then the evidence in two columns and the neighbourhoods next door.

export type Fmt = (v: number) => string;

/** Step of 1, 2, 2.5 or 5 × 10^k giving about five intervals. */
function niceStep(span: number) {
  const raw = span / 5, pow = 10 ** Math.floor(Math.log10(raw)), f = raw / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * pow;
}

export interface Mark { k: "here" | "lad" | "nat" | "ref"; x: number; label: string; sub: string }

export function Ruler({ marks, nearby = [], fmt, caption, refLine, cap }: {
  marks: Mark[]; nearby?: number[]; fmt: Fmt; caption: string; refLine?: { x: number; label: string };
  /** upper bound of the scale, e.g. 100 for a percentage */
  cap?: number;
}) {
  const vals = [...marks.map((m) => m.x), ...(refLine ? [refLine.x] : [])];
  const lo = Math.min(0, ...vals);
  const step = niceStep((Math.max(...vals) * 1.45 - lo) || 1);
  const min = Math.floor(lo / step) * step;
  const max = Math.min(cap ?? Infinity, Math.ceil((Math.max(...vals) * 1.45) / step) * step);
  const ticks = Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => min + i * step);
  const at = (x: number) => `${Math.max(0, Math.min(100, ((x - min) / (max - min)) * 100))}%`;
  // A reference value (e.g. the WHO guideline) is labelled like the other marks so it gets a row too.
  const sorted = [...marks, ...(refLine ? [{ k: "ref" as const, x: refLine.x, label: refLine.label, sub: fmt(refLine.x) }] : [])].sort((a, b) => a.x - b.x);
  // Labels are centred on their stem; one that would overlap the label before it in a row moves
  // up a row. Widths are estimated in % of a ~1,100 px bar from the longer of its two lines.
  const width = (m: Mark) => (Math.max(m.label.length * 8.5, m.sub.length * 7) + 16) / 11;
  const rowEnds: number[] = [];
  const rows = sorted.map((m) => {
    const c = ((m.x - min) / (max - min)) * 100, w = width(m);
    let row = rowEnds.findIndex((end) => c - w / 2 > end);
    if (row < 0) row = rowEnds.length;
    rowEnds[row] = c + w / 2;
    return row;
  });
  const depth = Math.max(...rows);
  const inside = nearby.filter((x) => x >= min && x <= max);
  const beyond = nearby.length - inside.length;
  return (
    <figure className="tp-ruler" aria-label={`${caption}: ${sorted.map((m) => `${m.label} ${m.sub}`).join(", ")}`}>
      <div className="tp-marks" style={{ height: 66 + depth * 50 }}>
        {sorted.map((m, i) => (
          <span key={m.k} className={`tp-mark ${m.k}`} style={{ left: at(m.x), "--row": rows[i] } as React.CSSProperties}>
            <b>{m.label}</b><span>{m.sub}</span>
          </span>
        ))}
      </div>
      <div className="tp-bar" aria-hidden="true">
        {ticks.slice(0, -1).map((t, i) => <i key={t} className={i % 2 ? "w" : "b"} style={{ width: `${(step / (max - min)) * 100}%` }} />)}
        {inside.map((x, i) => <em key={i} style={{ left: at(x) }} />)}
        {refLine && <span className="tp-ref" style={{ left: at(refLine.x) }} />}
        {beyond > 0 && <strong className="tp-beyond">+{beyond}</strong>}
      </div>
      <div className="tp-ticks" aria-hidden="true">
        {ticks.map((t) => <span key={t} style={{ left: at(t) }}>{fmt(t)}</span>)}
      </div>
      <figcaption>
        {caption}.{nearby.length ? ` Ticks under the bar are the ${nearby.length} neighbourhoods within 1 km${beyond ? `; ${beyond} of them are off the scale` : ""}.` : ""}
      </figcaption>
    </figure>
  );
}

/** "Dearer than Southwark, cheaper than the England average" from the key figure. */
export function verdictFor({ here, lad, nat, ladName, natName, words, p, dir }: {
  here: number; lad: number | null; nat: number | null; ladName: string | null; natName: string;
  /** [higher, lower] e.g. ["Dearer", "Cheaper"] */
  words: [string, string]; p?: number | null; dir: -1 | 0 | 1;
}): string {
  const rel = (b: number | null) => (b == null ? null : here > b * 1.05 ? 0 : here < b * 0.95 ? 1 : 2);
  const l = ladName ? rel(lad) : null, n = rel(nat);
  const nn = `the ${natName} average`;
  // Lower-case only the first letter, so "GP" stays "GP" mid-sentence.
  const lc = (w: string) => w.charAt(0).toLowerCase() + w.slice(1);
  const say = (r: number, who: string) => (r === 2 ? `in line with ${who}` : `${lc(words[r])} than ${who}`);
  let s: string;
  if (l != null && n != null) s = l === n ? (l === 2 ? `in line with ${ladName} and ${nn}` : `${lc(words[l])} than both ${ladName} and ${nn}`) : `${say(l, ladName!)}, ${say(n, nn)}`;
  else if (l != null) s = say(l, ladName!);
  else if (n != null) s = say(n, nn);
  else return "";
  // The national mean is pulled by outliers; add the typical neighbourhood when it tells a different story.
  if (p != null && dir !== 0 && n != null && n !== 2) {
    const better = dir > 0 ? p >= 60 : p <= 40, worse = dir > 0 ? p <= 40 : p >= 60;
    const meanBetter = dir > 0 ? n === 0 : n === 1;
    if (meanBetter && worse) s += `, but ${lc(words[dir > 0 ? 1 : 0])} than the typical neighbourhood`;
    if (!meanBetter && better) s += `, but ${lc(words[dir > 0 ? 0 : 1])} than the typical neighbourhood`;
  }
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const GOOD = ["#b8433a", "#e57f66", "#f3b886", "#efe3b2", "#a6cf8b", "#4f9a6a"];
const SEQ = ["#eef2f7", "#c9d7e8", "#9fb8d6", "#6f93c0", "#456fa6", "#26507f"];
export function swatch(p: number | null, dir: -1 | 0 | 1) {
  if (p == null) return "#ccc";
  const x = dir < 0 ? 100 - p : p;
  const i = [95, 80, 60, 40, 20, 0].findIndex((s) => x >= s);
  return (dir === 0 ? SEQ : GOOD)[5 - i];
}

export function NextDoor({ items, own, fmt, dir, caption }: { items: NeighbourValue[]; own: string | null; fmt: Fmt; dir: -1 | 0 | 1; caption: string }) {
  const shown = items.filter((a) => a.v != null).slice(0, 10);
  if (shown.length < 3) return null;
  return (
    <section className="tp-near" aria-labelledby="tp-near-h">
      <h2 id="tp-near-h">Next door</h2>
      <div className="tp-near-row">
        {shown.map((a) => (
          <div key={a.code} className={`tp-chip${a.code === own ? " own" : ""}`} title={`${a.code}, ${a.name}`}>
            <i style={{ background: swatch(a.p, dir) }} />
            <b>{fmt(a.v!)}</b>
            <span>{a.code === own ? "Yours" : a.dist < 1000 ? `${Math.round(a.dist / 10) * 10} m` : "1 km"}</span>
          </div>
        ))}
      </div>
      <p className="tp-note">{caption} Neighbourhoods within 1 km, nearest first; colour follows the map.</p>
    </section>
  );
}

export function TopicShell({ plate, plateSub, map, title, verdict, dek, ruler, main, side, after, source, back }: {
  plate: string; plateSub: string; map: ReactNode; title: string; verdict: string; dek?: ReactNode;
  ruler?: ReactNode; main: ReactNode; side?: ReactNode; after?: ReactNode; source?: ReactNode; back: { href: string; label: string };
}) {
  return (
    <div className="tp">
      <section className="tp-hero">
        <div className="tp-map">{map}</div>
        <div className="tp-plate" aria-hidden="true">{plate}<small>{plateSub}</small></div>
      </section>
      <header className="tp-head">
        <h1>{title}</h1>
        {verdict && <p className="tp-verdict">{verdict}.</p>}
        {dek && <p className="tp-dek">{dek}</p>}
      </header>
      {ruler}
      <div className={`tp-cols${side ? "" : " single"}`}>
        <div className="tp-main">{main}</div>
        {side && <aside className="tp-side">{side}</aside>}
      </div>
      {after}
      {source && <p className="tp-source">{source}</p>}
      <p className="tp-back"><Link href={back.href}>{back.label}</Link></p>
    </div>
  );
}
