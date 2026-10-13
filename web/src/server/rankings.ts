import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";

// Rankings run on a single metric among local authorities (or sectors in one
// LAD). They read raw values, so they work before the ETL scoring step runs.

export interface RankingDef {
  slug: string;
  metric: string;
  /** 1 = higher value is "top"; -1 = lower value is "top" */
  order: 1 | -1;
  titleKey: string;
}

export const RANKINGS: RankingDef[] = [
  { slug: "safest", metric: "uk.crime.total_rate", order: -1, titleKey: "safest" },
  { slug: "most-affordable", metric: "uk.price.median", order: -1, titleKey: "mostAffordable" },
  { slug: "best-connected", metric: "uk.tcm.overall", order: 1, titleKey: "bestConnected" },
  { slug: "cleanest-air", metric: "uk.pcm.no2", order: -1, titleKey: "cleanestAir" },
  { slug: "highest-income", metric: "uk.income.net", order: 1, titleKey: "highestIncome" },
  { slug: "flood-zone-3", metric: "uk.zone.flood_zone3_share", order: 1, titleKey: "floodZone3" },
  { slug: "radon", metric: "uk.zone.radon_1pct_share", order: 1, titleKey: "radon" },
  { slug: "coal-mining", metric: "uk.zone.coal_reporting_share", order: 1, titleKey: "coalMining" },
  { slug: "subsidence-clay", metric: "uk.zone.shrink_swell_sig_share", order: 1, titleKey: "subsidence" },
  { slug: "safest-roads", metric: "uk.road.ksi_per_1k", order: -1, titleKey: "safestRoads" },
  { slug: "price-to-earnings", metric: "uk.afford.median_ratio", order: -1, titleKey: "priceToEarnings" },
];

export interface RankRow {
  rank: number;
  name: string;
  code: string;
  slug: string;
  level: string;
  value: number;
}

export async function getRanking(slug: string, scope: string): Promise<{ def: RankingDef; scopeName: string; rows: RankRow[]; period: string | null } | null> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", "rankings");
  return scoped(async () => {
    const def = RANKINGS.find((r) => r.slug === slug);
    if (!def) return null;
    const dir = def.order === 1 ? sql`desc` : sql`asc`;
    const [lp] = await sql`select max(period)::text as p from core.metric_value where market_code = 'uk' and metric_id = ${def.metric}`;
    if (!lp?.p) return { def, scopeName: "England and Wales", rows: [], period: null };

    if (scope === "england-and-wales") {
      const rows = await sql`
        select a.name, a.code, a.slug, a.level_code, v.value_num
        from core.metric_value v join core.geo_area a on a.id = v.area_id and a.level_code = 'lad'
        where v.market_code = 'uk' and v.metric_id = ${def.metric} and v.period = ${lp.p}
          and v.value_num is not null and not v.is_suppressed and left(a.code, 1) in ('E', 'W')
        order by v.value_num ${dir} limit 50`;
      return { def, scopeName: "England and Wales", period: lp.p, rows: rows.map((r, i) => ({ rank: i + 1, name: r.name, code: r.code, slug: r.slug, level: r.level_code, value: r.value_num })) };
    }
    // scope = LAD slug → sectors whose population sits mostly in that LAD
    const [lad] = await sql`select id::int, name from core.geo_area where market_code = 'uk' and level_code = 'lad' and slug = ${scope}`;
    if (!lad) return null;
    const rows = await sql`
      with lsoa as (
        select k.child_id from core.geo_area_link k join core.geo_area c on c.id = k.child_id and c.level_code = 'lsoa'
        where k.parent_id = ${lad.id} and k.relation = 'overlaps'),
      sec as (
        select k.parent_id as id, sum(k.weight) w from core.geo_area_link k join lsoa l on l.child_id = k.child_id
        join core.geo_area s on s.id = k.parent_id and s.level_code = 'sector'
        where k.relation = 'overlaps' group by 1 having sum(k.weight) >= 0.5)
      select a.name, a.code, a.slug, a.level_code, v.value_num
      from sec join core.geo_area a on a.id = sec.id
      join core.metric_value v on v.market_code = 'uk' and v.area_id = a.id and v.metric_id = ${def.metric} and v.period = ${lp.p}
      where v.value_num is not null and not v.is_suppressed
      order by v.value_num ${dir} limit 30`;
    return { def, scopeName: lad.name, period: lp.p, rows: rows.map((r, i) => ({ rank: i + 1, name: r.name, code: r.code, slug: r.slug, level: r.level_code, value: r.value_num })) };
  });
}

export async function getLadList(): Promise<{ name: string; slug: string }[]> {
  "use cache";
  cacheLife("days");
  return scoped(async () => {
    const rows = await sql`select name, slug from core.geo_area where market_code = 'uk' and level_code = 'lad'
                           and is_active and left(code, 1) in ('E', 'W') order by name`;
    return rows.map((r) => ({ name: r.name, slug: r.slug }));
  });
}
