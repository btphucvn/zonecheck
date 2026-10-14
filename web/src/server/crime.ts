import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";

// Crime detail page: the 14 police.uk crime types, a three-year trend and where
// and how crimes were recorded. Areas larger than an LSOA are built the same way
// as the uk.crime.* metrics (derive/crime.py): LSOA counts weighted by the share
// of the LSOA's residents living in the area, so totals here match the report.

const M = "uk";

export interface CrimeCounts {
  /** weighted residents in the area */
  pop: number;
  /** crime type → weighted incidents, last 12 months / the 12 months before */
  last12: Record<string, number>;
  prev12: Record<string, number>;
  /** 3-month windows ending at the latest month, oldest first: crimes excl. ASB */
  quarters: { end: string; n: number }[];
  /** crime type → weighted incidents in the last 1, 3 and 6 months (12 months is last12) */
  windows: { m1: Record<string, number>; m3: Record<string, number>; m6: Record<string, number> };
}

export interface WardCrime { name: string; slug: string; rate: number; p: number | null }

export interface CrimeDetail {
  /** latest month in the data (YYYY-MM-01) */
  last: string;
  first: string;
  area: CrimeCounts | null;
  lad: CrimeCounts | null;
  /** police.uk snap points ("On or near …"), last 12 months, most crimes first */
  places: { name: string; n: number }[];
  /** latest outcome recorded for crimes in the last 12 months (ASB has none) */
  outcomes: { name: string; n: number }[];
  /** postcodes only: incidents within NEAR_M of the postcode, last 12 months, crime type → count.
   *  A count, not a rate: there is no exact resident figure for a circle. */
  near: { radius: number; counts: Record<string, number> } | null;
}

const NEAR_M = 800;

/** Incidents within NEAR_M of a point. The box (0.015° ≥ 800 m of longitude up to 61°N) uses the
 *  spatial index; the geography test then keeps the true circle. */
async function nearCounts(lon: number, lat: number, last: string) {
  const rows = await sql`
    select crime_type as t, count(*)::int as n from mkt_uk.crime_incident
    where month > (${last}::date - interval '12 months') and month <= ${last}::date
      and geom && ST_Expand(ST_SetSRID(ST_MakePoint(${lon}, ${lat}), 4326), 0.015)
      and ST_DWithin(geom::geography, ST_MakePoint(${lon}, ${lat})::geography, ${NEAR_M})
    group by 1`;
  return Object.fromEntries((rows as Row[]).map((r) => [r.t, r.n])) as Record<string, number>;
}

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** LSOAs making up an area with their population weight (an LSOA is itself, weight 1). */
const members = (areaId: number) => sql`
  select a.code, 1::float8 as w, coalesce(a.population, 0)::float8 as pop
  from core.geo_area a where a.id = ${areaId} and a.level_code = 'lsoa'
  union all
  select c.code, k.weight::float8, coalesce(c.population, 0)::float8
  from core.geo_area_link k join core.geo_area c on c.id = k.child_id
  where k.parent_id = ${areaId} and k.relation = 'overlaps' and k.weight_basis = 'population'
    and c.level_code = 'lsoa' and k.weight > 0`;

async function countsFor(areaId: number, last: string): Promise<CrimeCounts | null> {
  const [[p], rows] = await Promise.all([
    sql`select sum(w * pop)::float8 as pop from (${members(areaId)}) m`,
    sql`
      select i.month::text as month, i.crime_type as t, sum(m.w)::float8 as n
      from (${members(areaId)}) m
      join mkt_uk.crime_incident i on i.lsoa21_code = m.code
        and i.month > (${last}::date - interval '36 months') and i.month <= ${last}::date
      group by 1, 2`,
  ]);
  if (!p?.pop) return null;
  const monthsAgo = (m: string) => {
    const [y1, m1] = last.split("-").map(Number);
    const [y2, m2] = m.split("-").map(Number);
    return (y1 - y2) * 12 + (m1 - m2);
  };
  const last12: Record<string, number> = {};
  const prev12: Record<string, number> = {};
  const q = new Array(12).fill(0) as number[];
  const windows: CrimeCounts["windows"] = { m1: {}, m3: {}, m6: {} };
  for (const r of rows as Row[]) {
    const ago = monthsAgo(r.month);
    if (ago < 1) windows.m1[r.t] = (windows.m1[r.t] ?? 0) + r.n;
    if (ago < 3) windows.m3[r.t] = (windows.m3[r.t] ?? 0) + r.n;
    if (ago < 6) windows.m6[r.t] = (windows.m6[r.t] ?? 0) + r.n;
    if (ago < 12) last12[r.t] = (last12[r.t] ?? 0) + r.n;
    else if (ago < 24) prev12[r.t] = (prev12[r.t] ?? 0) + r.n;
    if (r.t !== "Anti-social behaviour" && ago < 36) q[11 - Math.floor(ago / 3)] += r.n;
  }
  const [ly, lm] = last.split("-").map(Number);
  const quarters = q.map((n, i) => {
    const back = (11 - i) * 3;
    const d = new Date(Date.UTC(ly, lm - 1 - back, 1));
    return { end: d.toISOString().slice(0, 10), n };
  });
  return { pop: p.pop, last12, prev12, quarters, windows };
}

async function placesAndOutcomes(areaId: number, last: string) {
  const recent = sql`
    select i.location_desc, i.last_outcome, i.crime_type
    from (${members(areaId)}) m
    join mkt_uk.crime_incident i on i.lsoa21_code = m.code
      and i.month > (${last}::date - interval '12 months') and i.month <= ${last}::date
    where m.w >= 0.5`;
  const [places, outcomes] = await Promise.all([
    sql`select regexp_replace(location_desc, '^On or near ', '') as name, count(*)::int as n
        from (${recent}) r where location_desc is not null and location_desc !~* 'no location'
        group by 1 order by 2 desc limit 8`,
    sql`select last_outcome as name, count(*)::int as n
        from (${recent}) r where crime_type <> 'Anti-social behaviour' and last_outcome is not null
        group by 1 order by 2 desc`,
  ]);
  return {
    places: places.map((r: Row) => ({ name: r.name, n: r.n })),
    outcomes: outcomes.map((r: Row) => ({ name: r.name, n: r.n })),
  };
}

/** Crime detail for an area (its data area for postcodes) and its local authority. */
export async function getCrimeDetail(areaId: number, ladId: number | null, near?: [number, number] | null): Promise<CrimeDetail | null> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`, `crime:${areaId}`);
  return scoped(async () => {
    // Window end = end of the uk.crime.* metrics, so the page agrees with the report.
    const [m] = await sql`select max(period)::text as last from core.metric_value
                          where market_code = ${M} and metric_id = 'uk.crime.total_12m'`;
    if (!m?.last) return null;
    const last: string = m.last;
    const [area, lad, po, nc] = await Promise.all([
      countsFor(areaId, last),
      ladId && ladId !== areaId ? countsFor(ladId, last) : Promise.resolve(null),
      placesAndOutcomes(areaId, last),
      near ? nearCounts(near[0], near[1], last) : Promise.resolve(null),
    ]);
    const [ly, lm] = last.split("-").map(Number);
    const first = new Date(Date.UTC(ly, lm - 12, 1)).toISOString().slice(0, 10);
    return { last, first, area, lad, ...po, near: nc && { radius: NEAR_M, counts: nc } };
  }, 8);
}

/** Wards of a local authority by crime rate (uk.crime.total_rate, 12 months), highest first. */
export async function getWardCrime(ladId: number): Promise<WardCrime[]> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`, `crime-wards:${ladId}`);
  return scoped(async () => {
    try {
      const rows = await sql`
        select w.name, w.slug, v.value_num as rate, v.percentile::float8 as p
        from core.geo_area_link k
        join core.geo_area w on w.id = k.child_id and w.level_code = 'ward' and w.is_active
        join lateral (select value_num, percentile from core.metric_value
                      where market_code = ${M} and area_id = w.id and metric_id = 'uk.crime.total_rate' and not is_suppressed
                      order by period desc limit 1) v on true
        where k.parent_id = ${ladId} and k.relation = 'within'
        order by v.value_num desc`;
      return rows.map((r: Row) => ({ name: r.name, slug: r.slug, rate: r.rate, p: r.p }));
    } catch (e) {
      console.error("[crime] wards failed:", e instanceof Error ? e.message : e);
      cacheLife("minutes");
      return [];
    }
  });
}

export interface CrimeHistory {
  /** series name → yearly rate per 1,000 residents (crimes excl. anti-social behaviour), complete years only */
  series: { label: string; points: { year: number; rate: number }[] }[];
  /** high-harm types for the area itself, from 2014 (police categories changed in 2013) */
  types: { label: string; points: { year: number; rate: number }[] }[];
}

// precomputed by the ETL step crime_history (mkt_uk.crime_area_year): k → label
const HIGH_HARM: [string, string][] = [["vso", "Violence and sexual offences"], ["robbery", "Robbery"], ["weapons", "Possession of weapons"]];

async function yearly(areaIds: number[]): Promise<Row[]> {
  return sql`select area_id::int, year::int, k, rate::float8 from mkt_uk.crime_area_year
             where area_id = any(${areaIds}::bigint[]) order by year`;
}

export async function getCrimeHistory(areaId: number, lad: { id: number; name: string } | null, region: { id: number; name: string } | null, label: string): Promise<CrimeHistory | null> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`, `crime-history:${areaId}`);
  return scoped(async () => {
    try {
      const ids = [areaId, lad && lad.id !== areaId ? lad.id : null, region && region.id !== areaId ? region.id : null].filter((x): x is number => x != null);
      const rows = await yearly(ids);
      const pts = (id: number, k: string) => rows.filter((r: Row) => r.area_id === id && r.k === k).map((r: Row) => ({ year: r.year, rate: r.rate }));
      const here = pts(areaId, "total");
      if (here.length < 3) return null;
      const series = [{ label, points: here }];
      if (lad && lad.id !== areaId && pts(lad.id, "total").length) series.push({ label: lad.name, points: pts(lad.id, "total") });
      if (region && region.id !== areaId && pts(region.id, "total").length) series.push({ label: region.name, points: pts(region.id, "total") });
      const t = Object.fromEntries(HIGH_HARM.map(([k]) => [k, pts(areaId, k)]));
      return { series, types: HIGH_HARM.filter(([k]) => t[k].length > 2).map(([k, label]) => ({ label, points: t[k] })) };
    } catch (e) {
      console.error("[crime] history failed:", e instanceof Error ? e.message : e);
      cacheLife("minutes");
      return null;
    }
  }, 8);
}
