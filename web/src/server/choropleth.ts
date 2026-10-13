import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";
import { CHOROPLETH_METRICS } from "@/markets/uk/choropleth";

/** Local authority outlines for England and Wales, simplified for a national view. */
export async function getLadShapes(): Promise<string> {
  "use cache";
  cacheLife("weeks");
  cacheTag("market:uk", "lad-shapes");
  return scoped(async () => {
    const [r] = await sql`
      select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
        'type', 'Feature',
        'properties', json_build_object('code', a.code, 'name', a.name, 'slug', a.slug),
        'geometry', st_asgeojson(st_simplifypreservetopology(coalesce(a.geom_simplified, a.geom), 0.003), 3)::json)), '[]'::json))::text as fc
      from core.geo_area a
      where a.market_code = 'uk' and a.level_code = 'lad' and a.is_active and a.geom is not null and left(a.code, 1) in ('E', 'W')`;
    return r.fc as string;
  });
}

/** Latest value of one measure for every local authority, keyed by LAD code. */
export async function getLadValues(metricId: string): Promise<{ period: string | null; values: Record<string, number> } | null> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", "lad-values");
  if (!CHOROPLETH_METRICS.some((m) => m.id === metricId)) return null;
  return scoped(async () => {
    const [lp] = await sql`select max(v.period)::text as p from core.metric_value v
                           join core.geo_area a on a.id = v.area_id and a.level_code = 'lad'
                           where v.market_code = 'uk' and v.metric_id = ${metricId}`;
    if (!lp?.p) return { period: null, values: {} };
    const rows = await sql`
      select a.code, v.value_num from core.metric_value v join core.geo_area a on a.id = v.area_id and a.level_code = 'lad'
      where v.market_code = 'uk' and v.metric_id = ${metricId} and v.period = ${lp.p}
        and v.value_num is not null and not v.is_suppressed and left(a.code, 1) in ('E', 'W')`;
    return { period: lp.p, values: Object.fromEntries(rows.map((r) => [r.code, r.value_num as number])) };
  });
}
