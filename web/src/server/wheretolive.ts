import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";
import { SCORE_MODEL } from "@/markets/uk/scoring";

// "Where should I live?": areas ranked on the persona score from the ETL scoring
// step (core.area_overall_score), filtered by place, budget and a few must-haves.

export interface WhereQuery {
  persona: string;
  /** "england-and-wales", "region:<slug>" or "lad:<slug>" */
  scope: string;
  level: "sector" | "district";
  maxPrice: number | null;
  /** keep areas where at most 5% of residents are in Flood Zone 3 */
  lowFlood: boolean;
  /** nearest rail, tube or tram station within 1.5 km */
  nearStation: boolean;
  /** crime rate at or below the median for the level */
  lowCrime: boolean;
}

export interface WhereRow {
  code: string;
  slug: string;
  name: string;
  place: string | null;
  score: number;
  strengths: string[];
  price: number | null;
  crime: number | null;
  flood: number | null;
  stationM: number | null;
}

export interface ScopeOption { value: string; label: string; group: "region" | "lad" }

export async function getScopeOptions(): Promise<ScopeOption[]> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk");
  return scoped(async () => {
    const rows = await sql`
      select level_code, name, slug from core.geo_area
      where market_code = 'uk' and level_code in ('region', 'lad') and is_active and left(code, 1) in ('E', 'W')
      order by level_code desc, name`;
    return rows.map((r) => ({ value: `${r.level_code}:${r.slug}`, label: r.name as string, group: r.level_code as "region" | "lad" }));
  });
}

export async function findPlaces(q: WhereQuery): Promise<WhereRow[]> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", "where-to-live");
  return scoped(async () => {
    let inScope = sql``;
    const m = q.scope.match(/^(region|lad):([a-z0-9-]+)$/);
    if (m) {
      const [a] = await sql`select code from core.geo_area where market_code = 'uk' and level_code = ${m[1]} and slug = ${m[2]}`;
      if (!a) return [];
      // An area belongs to the region or LAD that holds most of its live postcodes.
      const key = q.level === "sector" ? sql`sector` : sql`district`;
      const col = m[1] === "region" ? sql`region_code` : sql`lad_code`;
      inScope = sql`and a.code in (
        select k from (select distinct on (k) k, c from (
          select ${key} as k, ${col} as c, count(*) as n from mkt_uk.postcode where status = 'live' group by 1, 2) t
          order by k, n desc) d
        where c = ${a.code})`;
    }
    const latest = (id: string) => sql`(select v.value_num from core.metric_value v
      where v.market_code = 'uk' and v.area_id = a.id and v.metric_id = ${id} and not v.is_suppressed
      order by v.period desc limit 1)`;
    const [med] = q.lowCrime
      ? await sql`select percentile_cont(0.5) within group (order by v.value_num)::float8 as m
                  from core.metric_value v join core.geo_area a on a.id = v.area_id and a.level_code = ${q.level}
                  where v.market_code = 'uk' and v.metric_id = 'uk.crime.total_rate'
                    and v.period = (select max(period) from core.metric_value where market_code = 'uk' and metric_id = 'uk.crime.total_rate')`
      : [{ m: null }];
    const rows = await sql`
      select y.*, (select t.name from core.geo_area t where t.market_code = 'uk' and t.level_code = 'town'
                    and coalesce(t.population, 0) > 0 order by t.centroid <-> y.centroid limit 1) as town,
             (select l.name from core.geo_area l where l.market_code = 'uk' and l.level_code = 'lad'
                    and st_intersects(l.geom, y.centroid) limit 1) as lad
      from (select * from (
        select a.code, a.slug, a.name, a.display_name, a.centroid, s.score::float8 as score, s.strengths,
               ${latest("uk.price.median")} as price, ${latest("uk.crime.total_rate")} as crime,
               ${latest("uk.zone.flood_zone3_share")} as flood, ${latest("uk.access.rail_dist_m")} as station_m
        from core.area_overall_score s
        join core.geo_area a on a.id = s.area_id
        where s.model_id = ${SCORE_MODEL} and s.persona_code = ${q.persona} and s.score is not null and s.coverage >= 0.6
          and a.market_code = 'uk' and a.level_code = ${q.level} and a.is_active
          and coalesce(a.population, 0) >= 500 -- skip PO box and business-only sectors
          and left(coalesce(a.attrs->>'country', 'E'), 1) <> 'S'
          ${inScope}
      ) x
      where true
        ${q.maxPrice ? sql`and x.price <= ${q.maxPrice}` : sql``}
        ${q.lowFlood ? sql`and coalesce(x.flood, 0) <= 5` : sql``}
        ${q.nearStation ? sql`and x.station_m <= 1500` : sql``}
        ${q.lowCrime && med?.m != null ? sql`and x.crime <= ${med.m}` : sql``}
      order by x.score desc
      limit 30) y
      order by y.score desc`;
    return rows.map((r) => ({
      code: r.code, slug: r.slug, name: r.name, place: [r.town, r.lad].filter((x, i, a) => x && a.indexOf(x) === i).join(", ") || null, score: r.score,
      strengths: (r.strengths as string[] | null) ?? [], price: r.price, crime: r.crime, flood: r.flood, stationM: r.station_m,
    }));
  });
}
