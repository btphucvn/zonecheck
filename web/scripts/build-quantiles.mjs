// Builds fallback percentile tables (data/quantiles/<level>.json) for when the
// ETL scoring step has not yet written core.metric_value.percentile.
// Heavy (about 1–2 minutes per level on the shared DB): run it once by hand.
//   node --env-file=.env.local scripts/build-quantiles.mjs [level ...]
import postgres from "postgres";
import { mkdirSync, writeFileSync } from "node:fs";

const LEVELS = process.argv.slice(2).length ? process.argv.slice(2) : ["lsoa", "sector", "district", "town", "lad", "region"];
const sql = postgres(process.env.DATABASE_URL, { max: 1, connection: { application_name: "zonecheck-web-quantiles", default_transaction_read_only: "on", statement_timeout: 600000 } });
const qs = Array.from({ length: 101 }, (_, i) => i / 100);
mkdirSync("data/quantiles", { recursive: true });

try {
  const metrics = await sql`select id from core.metric where market_code = 'uk' and subject = 'area' and status = 'active'
                            and value_type not in ('distribution', 'category')`;
  const ids = metrics.map((m) => m.id);
  for (const level of LEVELS) {
    const t0 = Date.now();
    const rows = await sql`
      with lp as (select m.id, (select max(period) from core.metric_value v where v.market_code = 'uk' and v.metric_id = m.id) p
                  from unnest(${ids}::text[]) as m(id)),
           lv as materialized (select id from core.geo_area where market_code = 'uk' and level_code = ${level})
      select v.metric_id, count(*)::int as n, percentile_cont(${qs}::float8[]) within group (order by v.value_num) as q
      from lp join core.metric_value v on v.market_code = 'uk' and v.metric_id = lp.id and v.period = lp.p
      join lv on lv.id = v.area_id
      where v.value_num is not null and not v.is_suppressed
      group by 1 having count(*) >= 20`;
    const out = { level, computedAt: new Date().toISOString(), metrics: Object.fromEntries(rows.map((r) => [r.metric_id, r.q])) };
    writeFileSync(`data/quantiles/${level}.json`, JSON.stringify(out));
    console.log(`${level}: ${rows.length} metrics in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
  }
} catch (e) {
  console.error("Failed to build quantiles:", e);
  process.exitCode = 1;
} finally {
  await sql.end();
}
