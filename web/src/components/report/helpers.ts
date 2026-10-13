import type { Dict } from "@/i18n/dictionaries";
import { fmtDistance, fmtMoney, fmtMonth, fmtNumber, fmtPct } from "@/lib/format";
import type { AreaReport, MetricMap, MetricMeta, MetricValue } from "@/server/types";

/** Everything a section needs: the report, strings, metric registry, peer wording. */
export interface H {
  r: AreaReport;
  t: Dict;
  cat: Record<string, MetricMeta>;
  intl: string;
  /** "postcode sectors" etc. for the level holding the figures */
  peers: string;
}

export function mv(map: MetricMap, id: string): MetricValue | undefined {
  const v = map[id];
  return v && !v.suppressed ? v : undefined;
}

export function val(map: MetricMap, id: string): number | null {
  return mv(map, id)?.v ?? null;
}

/** Percentile flipped so higher = better for the resident. */
export function goodness(h: H, id: string, map: MetricMap = h.r.metrics): number | null {
  const v = mv(map, id);
  if (!v || v.p == null) return null;
  const dir = h.cat[id]?.direction ?? 0;
  return dir < 0 ? 100 - v.p : v.p;
}

/** "Higher than 72% of postcode sectors" from the raw (unflipped) percentile. */
export function rankText(h: H, id: string, map: MetricMap = h.r.metrics): string | undefined {
  const v = mv(map, id);
  if (!v || v.p == null) return undefined;
  const p = Math.round(v.p);
  return p >= 50
    ? h.t.report.higher.replace("{p}", String(p)).replace("{peers}", h.peers)
    : h.t.report.lower.replace("{p}", String(100 - p)).replace("{peers}", h.peers);
}

export function periodLabel(id: string, period: string | undefined, intl: string): string {
  if (!period) return "";
  if (id.startsWith("uk.census21")) return "Census 2021";
  if (id.startsWith("uk.crime.")) return `12 months to ${fmtMonth(period, intl)}`;
  if (id.startsWith("uk.price.")) return `24 months to ${fmtMonth(period, intl)}`;
  if (id.startsWith("uk.iod25")) return "IoD 2025";
  if (id.startsWith("uk.wimd25")) return "WIMD 2025";
  if (id.startsWith("uk.access.") || id.startsWith("uk.schools.")) return fmtMonth(period, intl);
  if (id.startsWith("uk.income.")) return `FYE ${Number(period.slice(0, 4)) + 1}`;
  if (id.startsWith("uk.ctax.band_d")) return `${period.slice(0, 4)}/${String(Number(period.slice(2, 4)) + 1).padStart(2, "0")}`;
  return fmtMonth(period, intl);
}

export function srcLine(h: H, id: string, map: MetricMap = h.r.metrics, extra?: string): string {
  const meta = h.cat[id];
  const v = map[id];
  const who = meta?.source ?? meta?.publisher ?? "";
  const bits = [who, periodLabel(id, v?.period, h.intl)].filter(Boolean);
  if (extra) bits.push(extra);
  return bits.join(", ");
}

export function fmtMetric(h: H, id: string, v: number | null | undefined): string {
  if (v == null) return h.t.report.notAvailable;
  const meta = h.cat[id];
  if (!meta) return fmtNumber(v, h.intl, 1);
  if (meta.valueType === "currency") return fmtMoney(v, "GBP", h.intl);
  if (meta.valueType === "percent") return fmtPct(v, h.intl, Math.abs(v) < 10 ? 1 : 0);
  if (meta.unit === "m") return fmtDistance(v, h.intl);
  if (meta.unit === "µg/m³") return `${fmtNumber(v, h.intl, 1)} µg/m³`;
  if (meta.valueType === "rate") return fmtNumber(v, h.intl, 1);
  if (meta.valueType === "count") return fmtNumber(v, h.intl);
  return fmtNumber(v, h.intl, Math.abs(v) < 100 ? 1 : 0);
}

/**
 * Census-style distribution → [label, share%] rows. Drops totals and "a: b"
 * sub-categories so groups are not double counted.
 */
export function distribution(j: unknown, opts: { exclude?: RegExp; top?: number; order?: string[] } = {}): [string, number][] {
  if (!j || typeof j !== "object") return [];
  const entries = Object.entries(j as Record<string, unknown>)
    .filter(([k, v]) => typeof v === "number" && !/total/i.test(k) && !k.includes(":") && !(opts.exclude?.test(k)))
    .map(([k, v]) => [k, v as number] as [string, number]);
  const sum = entries.reduce((s, [, v]) => s + v, 0);
  if (!sum) return [];
  let rows = entries.map(([k, v]) => [k, (v / sum) * 100] as [string, number]);
  if (opts.order) rows.sort((a, b) => opts.order!.indexOf(a[0]) - opts.order!.indexOf(b[0]));
  else rows.sort((a, b) => b[1] - a[1]);
  if (opts.top) rows = rows.slice(0, opts.top);
  return rows;
}

/** Median age from Census TS007A five-year bands. */
export function medianAge(j: unknown): number | null {
  if (!j || typeof j !== "object") return null;
  const bands = Object.entries(j as Record<string, number>)
    .map(([k, n]) => {
      const m = k.match(/(\d+)\D+(\d+)?/);
      if (!m) return null;
      const lo = /under/i.test(k) ? 0 : Number(m[1]);
      const hi = /over/i.test(k) ? lo + 10 : m[2] ? Number(m[2]) + 1 : lo + 5;
      return { lo, hi, n };
    })
    .filter((x): x is { lo: number; hi: number; n: number } => !!x && typeof x.n === "number")
    .sort((a, b) => a.lo - b.lo);
  const total = bands.reduce((s, b) => s + b.n, 0);
  if (!total) return null;
  let acc = 0;
  for (const b of bands) {
    if (acc + b.n >= total / 2) return Math.round(b.lo + ((total / 2 - acc) / b.n) * (b.hi - b.lo));
    acc += b.n;
  }
  return null;
}

/** Simple age groups for a bar chart from TS007A bands. */
export function ageGroups(j: unknown): [string, number][] {
  if (!j || typeof j !== "object") return [];
  const groups: [string, number, number][] = [["0 to 15", 0, 15], ["16 to 24", 16, 24], ["25 to 44", 25, 44], ["45 to 64", 45, 64], ["65 and over", 65, 200]];
  const acc = groups.map(() => 0);
  let total = 0;
  for (const [k, n] of Object.entries(j as Record<string, number>)) {
    if (typeof n !== "number") continue;
    const m = k.match(/(\d+)/);
    const lo = /under/i.test(k) ? 0 : m ? Number(m[1]) : -1;
    if (lo < 0) continue;
    total += n;
    // TS007A uses 15–19: split it 1/5 to 0–15, 4/5 to 16–24
    if (lo === 15) { acc[0] += n / 5; acc[1] += (n * 4) / 5; continue; }
    const g = groups.findIndex(([, a, b]) => lo >= a && lo <= b);
    if (g >= 0) acc[g] += n;
  }
  return total ? groups.map(([l], i) => [l, (acc[i] / total) * 100] as [string, number]) : [];
}
