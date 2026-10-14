import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";

// Context that a single neighbourhood figure hides: how the streets next door compare, and how the
// neighbourhoods inside a larger area split between better- and worse-off. Both use the LSOA-level
// IoD 2025 deciles (England) so every area is measured the same way.

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface Composition {
  /** share of residents (0–100) living in neighbourhoods in the bottom 3 / middle 4 / top 3 national deciles */
  low: number; mid: number; high: number;
  /** number of neighbourhoods (LSOAs) counted */
  n: number;
}

export interface AreaInsights {
  /** neighbouring LSOAs (touching the data LSOA) */
  borders: {
    /** lowest income decile among neighbours, and this neighbourhood's own */
    incomeMin: number | null; incomeHere: number | null;
    /** highest social-rented share among neighbours, with the regional average */
    socialMax: number | null; socialHere: number | null;
  } | null;
  /** income deprivation (IoD income domain) and overall deprivation across a wider area */
  income: Composition | null;
  deprivation: Composition | null;
  /** the area that composition describes (the area itself, or the sector of a postcode) */
  scopeName: string | null;
}

/** Deprivation: IoD decile of each LSOA (1–3 deprived, 8–10 least deprived). Income: national percentile of the
 *  MSOA household income estimate each LSOA sits in, put on the same 1–10 scale. */
async function composition(areaId: number, metric: string): Promise<Composition | null> {
  const msoa = metric === "uk.income.net";
  const [r] = await sql`
    with m as (
      select c.id, k.weight * c.population as w, v.value_num as d
      from core.geo_area_link k
      join core.geo_area c on c.id = k.child_id and c.level_code = 'lsoa'
      join lateral (${msoa
        ? sql`select least(10, floor(x.percentile / 10) + 1) as value_num from core.geo_area_link b
              join core.metric_value x on x.market_code = 'uk' and x.area_id = b.parent_id and x.metric_id = ${metric}
              join core.geo_area pm on pm.id = b.parent_id and pm.level_code = 'msoa'
              where b.child_id = c.id and b.relation = 'best_fit' and x.percentile is not null order by x.period desc limit 1`
        : sql`select value_num from core.metric_value
              where market_code = 'uk' and area_id = c.id and metric_id = ${metric} order by period desc limit 1`}) v on true
      where k.parent_id = ${areaId} and k.relation = 'overlaps' and k.weight_basis = 'population')
    select count(*)::int as n, sum(w)::float8 as w,
           sum(w) filter (where d <= 3)::float8 as low, sum(w) filter (where d between 4 and 7)::float8 as mid,
           sum(w) filter (where d >= 8)::float8 as high
    from m`;
  if (!r || !r.n || !r.w) return null;
  const pc = (x: number | null) => Math.round(((x ?? 0) / r.w) * 100);
  return { n: r.n, low: pc(r.low), mid: pc(r.mid), high: pc(r.high) };
}

export async function getAreaInsights(level: string, slug: string, ids: { dataId: number; dataLevel: string; scopeId: number | null; scopeName: string | null }): Promise<AreaInsights> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", `area:${level}:${slug}`);
  return scoped(async () => {
    try {
      let borders: AreaInsights["borders"] = null;
      if (ids.dataLevel === "lsoa") {
        const rows = await sql`
          with me as (select id, geom from core.geo_area where id = ${ids.dataId}),
          nb as (select a.id from core.geo_area a, me
                 where a.market_code = 'uk' and a.level_code = 'lsoa' and a.is_active and a.id <> me.id
                   and a.geom && me.geom and st_touches(a.geom, me.geom))
          select v.area_id = ${ids.dataId} as own, v.metric_id, v.value_num
          from core.metric_value v
          where v.market_code = 'uk' and v.area_id in (select id from nb union all select ${ids.dataId})
            and v.metric_id in ('uk.iod25.income_decile', 'uk.share.social_rented') and not v.is_suppressed`;
        const of = (m: string, own: boolean) => rows.filter((x: Row) => x.metric_id === m && x.own === own).map((x: Row) => x.value_num as number);
        const inc = of("uk.iod25.income_decile", false), soc = of("uk.share.social_rented", false);
        borders = {
          incomeMin: inc.length ? Math.min(...inc) : null, incomeHere: of("uk.iod25.income_decile", true)[0] ?? null,
          socialMax: soc.length ? Math.max(...soc) : null, socialHere: of("uk.share.social_rented", true)[0] ?? null,
        };
      }
      const scope = ids.scopeId;
      const [income, deprivation] = scope
        ? await Promise.all([composition(scope, "uk.income.net"), composition(scope, "uk.iod25.imd_decile")])
        : [null, null];
      return { borders, income, deprivation, scopeName: ids.scopeName };
    } catch (e) {
      console.error("[insights] failed:", e instanceof Error ? e.message : e);
      cacheLife("minutes");
      return { borders: null, income: null, deprivation: null, scopeName: null };
    }
  });
}

export interface Classification {
  group: { code: string; name: string; text: string | null };
  supergroup: { code: string; name: string; text: string | null };
  /** share of the area's postcodes in this group (100 for a single postcode) */
  share: number;
}

/** UK Output Area Classification 2021/22 for a postcode (its OA), or the most common group across an area's postcodes. */
export async function getClassification(level: string, code: string): Promise<Classification | null> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", `oac:${level}:${code}`);
  const col = { postcode_unit: sql`p.postcode`, sector: sql`p.sector`, district: sql`p.district`, ward: sql`p.ward_code`, lad: sql`p.lad_code` }[level];
  if (!col) return null;
  return scoped(async () => {
    try {
      const [r] = await sql`
        with g as (
          select o.grp, o.supergroup, count(*) as n, sum(count(*)) over () as total
          from mkt_uk.postcode p join mkt_uk.oac o on o.oa21_code = p.oa21_code
          where ${col} = ${code} and p.status = 'live'
          group by 1, 2 order by 3 desc limit 1)
        select g.grp, g.supergroup, (100.0 * g.n / g.total)::float8 as share,
               lg.name as g_name, lg.pen_portrait as g_text, ls.name as s_name, ls.pen_portrait as s_text
        from g join mkt_uk.oac_label lg on lg.level = 'group' and lg.code = g.grp
        join mkt_uk.oac_label ls on ls.level = 'supergroup' and ls.code = g.supergroup`;
      if (!r) return null;
      return {
        group: { code: r.grp, name: r.g_name, text: r.g_text }, supergroup: { code: r.supergroup, name: r.s_name, text: r.s_text },
        share: Math.round(r.share),
      };
    } catch (e) {
      // table not loaded yet, or a slow query: leave the block out
      console.error("[insights] classification failed:", e instanceof Error ? e.message : e);
      cacheLife("minutes");
      return null;
    }
  });
}
