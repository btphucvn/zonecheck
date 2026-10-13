import type { CrimeCounts, CrimeDetail } from "@/server/crime";
import type { AreaReport } from "@/server/types";

// Everything the crime topic page shows, derived once from the report and the crime detail.

const ASB = "Anti-social behaviour";

/** Police crime type, label, phrase, and the key of its national metric uk.crime.{key}_rate. */
export const CRIME_TYPES: [string, string, string, string][] = [
  ["Violence and sexual offences", "Violence and sexual offences", "violence and sexual offences", "vso"],
  ["Anti-social behaviour", "Anti-social behaviour", "anti-social behaviour", "asb"],
  ["Vehicle crime", "Vehicle crime", "vehicle crime", "vehicle"],
  ["Burglary", "Burglary", "burglary", "burglary"],
  ["Bicycle theft", "Bicycle theft", "bike theft", "bicycle"],
  ["Other theft", "Other theft", "other theft", "other_theft"],
  ["Theft from the person", "Theft from the person", "pickpocketing and snatch theft", "theft_person"],
  ["Shoplifting", "Shoplifting", "shoplifting", "shoplifting"],
  ["Robbery", "Robbery", "robbery", "robbery"],
  ["Criminal damage and arson", "Criminal damage and arson", "criminal damage", "damage"],
  ["Public order", "Public order", "public order offences", "public_order"],
  ["Drugs", "Drugs", "drug offences", "drugs"],
  ["Possession of weapons", "Possession of weapons", "weapons possession", "weapons"],
  ["Other crime", "Other crime", "other crime", "other_crime"],
];

/** National percentile groups with LSOA metrics (uk.crime.{k}_rate). */
export const GROUPS: { k: string; label: string }[] = [
  { k: "total", label: "All crime" },
  { k: "violent", label: "Violence and robbery" },
  { k: "burglary", label: "Burglary" },
  { k: "vehicle", label: "Vehicle crime" },
  { k: "theft", label: "Theft" },
  { k: "damage", label: "Criminal damage" },
  { k: "asb", label: "Anti-social behaviour" },
];

/** Same colour steps as the crime map: percentile of the rate, higher = more crime. */
export const RAMP: [number, string, string][] = [
  [0, "#4f9a6a", "among the lowest 20% of neighbourhoods"],
  [20, "#a6cf8b", "lower than most neighbourhoods"],
  [40, "#efe3b2", "close to the typical neighbourhood"],
  [60, "#f3b886", "higher than most neighbourhoods"],
  [80, "#e57f66", "among the highest 20% of neighbourhoods"],
  [95, "#b8433a", "in the highest 5% of neighbourhoods"],
];
/** Percentile → 1 to 10: 10 = the tenth of areas with the most of this crime. */
export const decileOf = (p: number) => Math.min(10, Math.floor(p / 10) + 1);
export const rampOf = (p: number | null | undefined) => (p == null ? null : [...RAMP].reverse().find(([from]) => p >= from)!);

export interface TypeRow {
  k: string; label: string; phrase: string; n: number; rate: number; ladRate: number | null; prev: number; change: number | null;
  /** national percentile of the rate (higher = more crime): this area among areas of its kind, the borough among boroughs */
  p: number | null; ladP: number | null;
}

export interface CrimeModel {
  code: string; name: string; town: string | null; lad: string | null; nation: string;
  lsoa: string; pop: number; first: string; last: string;
  total: number; asb: number; rate: number; ladRate: number | null; natRate: number | null;
  /** percentile of the total rate among neighbourhoods (higher = more crime) */
  p: number | null; change: number | null;
  groups: { k: string; label: string; rate: number | null; p: number | null; ladRate: number | null; natRate: number | null }[];
  rows: TypeRow[];
  above: TypeRow[]; below: TypeRow[];
  trend: { label: string; points: { x: string; y: number }[] }[];
  places: { name: string; n: number }[];
  outcomes: { name: string; n: number; share: number }[];
  lon: number; lat: number; bbox: AreaReport["bbox"]; geojson: string | null;
}

const v = (m: AreaReport["metrics"], id: string) => {
  const x = m[id];
  return x && !x.suppressed ? x : undefined;
};

export function crimeModel(r: AreaReport, d: CrimeDetail): CrimeModel | null {
  const c = d.area;
  if (!c) return null;
  const lad = d.lad;
  const rate = (x: CrimeCounts | null, k: string) => (x && x.pop ? ((x.last12[k] ?? 0) / x.pop) * 1000 : null);
  const total = Object.entries(c.last12).reduce((s, [k, n]) => (k === ASB ? s : s + n), 0);
  const rows: TypeRow[] = CRIME_TYPES.map(([k, label, phrase, key]) => {
    const n = c.last12[k] ?? 0, prev = c.prev12[k] ?? 0;
    return {
      k, label, phrase, n, rate: rate(c, k) ?? 0, ladRate: rate(lad, k), prev, change: prev >= 5 ? ((n - prev) / prev) * 100 : null,
      p: v(r.metrics, `uk.crime.${key}_rate`)?.p ?? null, ladP: v(r.ladMetrics, `uk.crime.${key}_rate`)?.p ?? null,
    };
  }).sort((a, b) => b.n - a.n);
  const ratio = (x: TypeRow) => (x.ladRate ? x.rate / x.ladRate : 1);
  const comparable = rows.filter((x) => x.k !== ASB && x.n >= 3 && (lad?.last12[x.k] ?? 0) >= 20);
  const series = (x: CrimeCounts) => x.quarters.map((q) => ({ x: q.end.slice(0, 7), y: ((q.n * 4) / x.pop) * 1000 }));
  const outcomeTotal = d.outcomes.reduce((s, o) => s + o.n, 0);
  const ladName = r.ctx.lad && r.ctx.lad.id !== r.ctx.dataArea.id ? r.ctx.lad.name : null;

  return {
    code: r.head.code, name: r.head.name, town: r.ctx.town?.name ?? null, lad: ladName, nation: r.ctx.nation?.name ?? "England",
    lsoa: r.ctx.dataArea.code, pop: c.pop, first: d.first, last: d.last,
    total, asb: c.last12[ASB] ?? 0,
    rate: v(r.metrics, "uk.crime.total_rate")?.v ?? (total / c.pop) * 1000,
    ladRate: v(r.ladMetrics, "uk.crime.total_rate")?.v ?? null,
    natRate: v(r.nationMetrics, "uk.crime.total_rate")?.v ?? null,
    p: v(r.metrics, "uk.crime.total_rate")?.p ?? null,
    change: v(r.metrics, "uk.crime.total_change_pct")?.v ?? null,
    groups: GROUPS.map((g) => ({
      k: g.k, label: g.label,
      rate: v(r.metrics, `uk.crime.${g.k}_rate`)?.v ?? null, p: v(r.metrics, `uk.crime.${g.k}_rate`)?.p ?? null,
      ladRate: v(r.ladMetrics, `uk.crime.${g.k}_rate`)?.v ?? null, natRate: v(r.nationMetrics, `uk.crime.${g.k}_rate`)?.v ?? null,
    })),
    rows,
    above: comparable.filter((x) => ratio(x) >= 1.3).sort((a, b) => ratio(b) - ratio(a)).slice(0, 3),
    below: comparable.filter((x) => ratio(x) <= 0.7).sort((a, b) => ratio(a) - ratio(b)).slice(0, 3),
    trend: [
      { label: `Neighbourhood ${r.ctx.dataArea.code}`, points: series(c) },
      ...(lad && ladName ? [{ label: ladName, points: series(lad) }] : []),
    ],
    places: d.places,
    outcomes: d.outcomes.map((o) => ({ ...o, share: outcomeTotal ? (o.n / outcomeTotal) * 100 : 0 })),
    lon: r.head.lon, lat: r.head.lat, bbox: r.bbox, geojson: r.geojson,
  };
}

export const joinList = (items: string[]) =>
  items.length <= 1 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;

export const monthLabel = (iso: string) =>
  new Date(`${iso.slice(0, 7)}-01T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });

export const n0 = (x: number) => Math.round(x).toLocaleString("en-GB");
export const n1 = (x: number) => x.toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
