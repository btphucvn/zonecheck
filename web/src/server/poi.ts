import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";
import type { AreaRef } from "./types";

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface PoiPage {
  id: number;
  type: string;
  typeName: string;
  name: string;
  slug: string;
  externalId: string;
  lon: number;
  lat: number;
  address: string | null;
  postcode: string | null;
  status: string;
  attrs: Record<string, string>;
  ratings: { scheme: string; aspect: string; label: string; rank: number | null; max: number | null; ratedOn: string; url: string | null; current: boolean }[];
  metrics: { id: string; name: string; period: string; v: number }[];
  /** latest value of each distribution-style metric (pupil ethnicity, year groups, destinations, subjects) */
  json: Record<string, { period: string; v: number | null; j: unknown }>;
  /** local authority and England averages for the school's metrics, latest period: metric → { la, eng } */
  bench: Record<string, { period: string; la: number | null; eng: number | null; laJ: unknown; engJ: unknown }>;
  postcodeArea: AreaRef | null;
  sectorArea: AreaRef | null;
  lad: AreaRef | null;
  nearby: { name: string; slug: string; type: string; dist: number }[];
}

export async function getPoiPage(kind: "school" | "station", slug: string): Promise<PoiPage | null> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", `poi:${slug}`);
  return scoped(async () => {
    const types = kind === "school" ? sql`p.type_code like 'school.%'` : sql`p.type_code in ('station.rail', 'station.metro')`;
    const [p] = await sql`
      select p.id::int, p.type_code, coalesce(t.name_i18n->>'en', p.type_code) as type_name, p.name, p.slug, p.external_id,
             st_x(p.geom) lon, st_y(p.geom) lat, p.address, p.postal_code, p.status, p.attrs
      from core.poi p join core.poi_type t on t.code = p.type_code
      where p.market_code = 'uk' and p.slug = ${slug} and ${types}
      limit 1`;
    if (!p) return null;
    // Stations carry no postcode: link them to the nearest live one.
    const pcCode: string | null = p.postal_code ?? (await sql`
      select postcode from mkt_uk.postcode where status = 'live' and geom is not null
      order by geom <-> (select geom from core.poi where id = ${p.id}) limit 1`)[0]?.postcode ?? null;
    const laCode: string | null = p.attrs?.["LA (code)"] ?? null;
    const phase = /special/i.test(p.attrs?.["EstablishmentTypeGroup (name)"] ?? "") ? "special"
      : /independent/i.test(p.attrs?.["EstablishmentTypeGroup (name)"] ?? "") ? "independent"
      : /primary/i.test(p.attrs?.["PhaseOfEducation (name)"] ?? "") ? "primary" : "secondary";
    const [ratings, metrics, pc, nearby, json, bench] = await Promise.all([
      sql`select scheme, aspect, grade_label, grade_rank, grade_scale_max, rated_on::text as rated_on, report_url, is_current
          from core.poi_rating where poi_id = ${p.id} order by rated_on desc, aspect`,
      sql`select v.metric_id, coalesce(t.name, v.metric_id) as name, v.period::text as period, v.value_num
          from core.poi_metric_value v left join core.metric_translation t on t.metric_id = v.metric_id and t.locale_code = 'en'
          where v.poi_id = ${p.id} and v.value_num is not null and not v.is_suppressed
          order by v.metric_id, v.period`,
      pcCode
        ? sql`select q.postcode, q.sector, q.lad_code,
                     (select row_to_json(a) from (select id::int, level_code, code, slug, name, display_name from core.geo_area
                        where market_code = 'uk' and level_code = 'postcode_unit' and code = q.postcode) a) as unit,
                     (select row_to_json(a) from (select id::int, level_code, code, slug, name, display_name from core.geo_area
                        where market_code = 'uk' and level_code = 'sector' and code = q.sector) a) as sector_area,
                     (select row_to_json(a) from (select id::int, level_code, code, slug, name, display_name from core.geo_area
                        where market_code = 'uk' and level_code = 'lad' and code = q.lad_code) a) as lad
              from mkt_uk.postcode q where q.postcode = ${pcCode}`
        : Promise.resolve([] as Row[]),
      sql`select n.name, n.slug, n.type_code, st_distance(n.geom::geography, (select geom from core.poi where id = ${p.id})::geography)::float8 as d
          from core.poi n
          where n.market_code = 'uk' and n.id <> ${p.id} and n.slug is not null and n.status = 'open'
            and ${kind === "school" ? sql`n.type_code like 'school.%'` : sql`n.type_code in ('station.rail', 'station.metro')`}
          order by n.geom <-> (select geom from core.poi where id = ${p.id}) limit 6`,
      kind === "school"
        ? sql`select distinct on (metric_id) metric_id, period::text as period, value_num, value_json from core.poi_metric_value
              where poi_id = ${p.id} and value_json is not null and not is_suppressed order by metric_id, period desc`
        : Promise.resolve([] as Row[]),
      kind === "school"
        ? sql`select distinct on (metric_id, la_code) metric_id, la_code, period::text as period, value_num, value_json
              from mkt_uk.school_benchmark
              where la_code in (${laCode ?? "-"}, 'ENG')
                and (phase in ('ks2', 'ks4', 'ks5') or phase = ${phase})
              order by metric_id, la_code, period desc`.catch(() => [] as Row[])
        : Promise.resolve([] as Row[]),
    ]);
    const benchMap: PoiPage["bench"] = {};
    for (const b of bench as Row[]) {
      const e = benchMap[b.metric_id] ?? { period: b.period, la: null, eng: null, laJ: null, engJ: null };
      if (b.la_code === "ENG") { e.eng = b.value_num; e.engJ = b.value_json; } else { e.la = b.value_num; e.laJ = b.value_json; }
      if (b.period > e.period) e.period = b.period;
      benchMap[b.metric_id] = e;
    }
    const ref = (a: Row | null): AreaRef | null => (a ? { id: a.id, level: a.level_code, code: a.code, slug: a.slug, name: a.name, displayName: a.display_name } : null);
    return {
      id: p.id, type: p.type_code, typeName: p.type_name, name: p.name, slug: p.slug, externalId: p.external_id,
      lon: p.lon, lat: p.lat, address: p.address && p.address.replace(/^[-\s,]+/, "") || null, postcode: p.postal_code, status: p.status, attrs: p.attrs ?? {},
      ratings: ratings.map((r: Row) => ({ scheme: r.scheme, aspect: r.aspect, label: r.grade_label, rank: r.grade_rank, max: r.grade_scale_max, ratedOn: r.rated_on, url: r.report_url, current: r.is_current })),
      metrics: metrics.map((m: Row) => ({ id: m.metric_id, name: m.name, period: m.period, v: m.value_num })),
      json: Object.fromEntries((json as Row[]).map((r) => [r.metric_id, { period: r.period, v: r.value_num, j: r.value_json }])),
      bench: benchMap,
      postcodeArea: ref(pc[0]?.unit ?? null), sectorArea: ref(pc[0]?.sector_area ?? null), lad: ref(pc[0]?.lad ?? null),
      nearby: nearby.map((n: Row) => ({ name: n.name, slug: n.slug, type: n.type_code, dist: n.d })),
    };
  });
}

/** A few well-known slugs to prerender at build time (Cache Components requires ≥ 1 param). */
export const SAMPLE_SCHOOL = "134225-harris-academy-peckham";
export const SAMPLE_STATION = "pmr-peckham-rye";
