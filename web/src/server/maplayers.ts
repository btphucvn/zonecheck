import "server-only";
import { sql } from "@/lib/db";

// GeoJSON for on-demand map layers. Every query is bounded by a bbox (max ~0.25°
// a side) and a row limit, so a pan never turns into a national scan.

export type BBox = [number, number, number, number];
type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export function parseBBox(s: string | null): BBox | null {
  const v = (s ?? "").split(",").map(Number);
  if (v.length !== 4 || v.some((x) => !Number.isFinite(x))) return null;
  const [x0, y0, x1, y1] = v;
  if (x0 >= x1 || y0 >= y1 || x0 < -9 || x1 > 3 || y0 < 49 || y1 > 61) return null;
  if (x1 - x0 > 0.5 || y1 - y0 > 0.3) return null;
  return [x0, y0, x1, y1];
}

const env = (b: BBox) => sql`st_makeenvelope(${b[0]}, ${b[1]}, ${b[2]}, ${b[3]}, 4326)`;

function fc(rows: Row[], props: (r: Row) => Record<string, unknown>) {
  return {
    type: "FeatureCollection",
    features: rows.filter((r) => r.g).map((r) => ({ type: "Feature", properties: props(r), geometry: JSON.parse(r.g) })),
  };
}

/** Street-level crimes for the latest month (+ the two before it), anonymised points from data.police.uk. */
export async function crimeLayer(b: BBox) {
  // Latest month = end of the crime metrics window (index lookup, no scan of the incident table).
  const [m] = await sql`select max(period)::text as m from core.metric_value where market_code = 'uk' and metric_id = 'uk.crime.total_12m'`;
  if (!m?.m) return { ...fc([], () => ({})), months: [] };
  const rows = await sql`
    select crime_type, month::text as month, last_outcome, location_desc, st_asgeojson(geom, 5) as g
    from mkt_uk.crime_incident
    where month > (${m.m}::date - interval '3 months') and month <= ${m.m}::date
      and geom && ${env(b)}
    limit 6000`;
  const months = [...new Set(rows.map((r: Row) => r.month as string))].sort();
  return {
    ...fc(rows, (r) => ({ t: r.crime_type, m: r.month.slice(0, 7), o: r.last_outcome ?? "", l: r.location_desc ?? "" })),
    months,
  };
}

const ZONE_GROUPS: Record<string, string[]> = {
  flood: ["flood.zone2", "flood.zone3"],
  planning: ["planning.conservation_area", "planning.article4", "planning.green_belt", "nature.sssi", "nature.national_park", "nature.national_landscape", "nature.local_nature_reserve"],
  green: ["greenspace.park", "greenspace.play", "greenspace.playing_field", "greenspace.sports", "greenspace.allotment", "greenspace.cemetery", "greenspace.golf"],
};

/** Zones clipped to the view and simplified for display. */
export async function zoneLayer(group: string, b: BBox) {
  const types = ZONE_GROUPS[group];
  if (!types) return null;
  const tol = Math.max((b[2] - b[0]) / 2500, 0.00002);
  const rows = await sql`
    select z.type_code, z.name, coalesce(t.name_i18n->>'en', z.type_code) as type_name,
           st_asgeojson(st_simplifypreservetopology(st_clipbybox2d(z.geom, ${env(b)}), ${tol}), 5) as g
    from core.zone z join core.zone_type t on t.code = z.type_code
    where z.market_code = 'uk' and z.type_code = any(${types}::text[]) and z.geom && ${env(b)}
    order by z.type_code
    limit 1500`;
  return fc(rows, (r) => ({ t: r.type_code, n: r.name ?? "", tn: r.type_name }));
}

const POI_GROUPS: Record<string, string[]> = {
  amenities: ["health.gp", "health.pharmacy", "health.dentist", "shop.supermarket"],
  schools: ["school.primary", "school.secondary", "school.all_through", "school.special", "school.nursery", "school.post16"],
  transport: ["station.rail", "station.metro", "station.bus", "stop.bus"],
};

export async function poiLayer(group: string, b: BBox) {
  const types = POI_GROUPS[group];
  if (!types) return null;
  const rows = await sql`
    select p.id::int, p.type_code, p.name, p.slug, coalesce(t.name_i18n->>'en', p.type_code) as type_name,
           r.grade_label, r.grade_rank, r.scheme, st_asgeojson(p.geom, 6) as g
    from core.poi p join core.poi_type t on t.code = p.type_code
    left join lateral (
      select grade_label, grade_rank, scheme from core.poi_rating r
      where r.poi_id = p.id and r.is_current and ((r.scheme = 'ofsted_oeif' and r.aspect = 'overall') or r.scheme = 'ofsted_report_card')
      order by r.rated_on desc limit 1) r on ${group === "schools" ? sql`true` : sql`false`}
    where p.market_code = 'uk' and p.status = 'open' and p.type_code = any(${types}::text[]) and p.geom && ${env(b)}
    limit 2500`;
  const seg = (t: string) => (t.startsWith("school.") ? "school" : t.startsWith("station.") && t !== "station.bus" ? "station" : null);
  return fc(rows, (r) => ({
    t: r.type_code, n: r.name, tn: r.type_name,
    href: r.slug && seg(r.type_code) ? `/uk/${seg(r.type_code)}/${r.slug}` : "",
    // ofsted 1 Outstanding … 4 Inadequate; 0 = report card or unrated
    o: r.scheme === "ofsted_oeif" ? r.grade_rank ?? 0 : 0,
    ol: r.scheme === "ofsted_report_card" ? "Report card" : r.grade_label ?? "Not rated",
  }));
}

/** Boundaries of neighbouring areas at one level, with labels and links. Postal levels have no
 *  official polygons, so they are drawn as concave hulls of their live postcodes. */
export async function areaLayer(level: string, b: BBox) {
  if (level === "sector" || level === "district") {
    const rows = await sql`
      select ${level === "sector" ? sql`sector` : sql`district`} as code,
             st_asgeojson(st_buffer(st_concavehull(st_collect(geom), 0.35)::geography, 30)::geometry, 5) as g
      from mkt_uk.postcode
      where status = 'live' and geom && ${env(b)}
      group by 1 having count(*) >= 3
      limit 400`;
    return fc(rows, (r) => ({ n: r.code, href: `/uk/${level}/${String(r.code).toLowerCase().replace(/\s+/g, "-")}` }));
  }
  if (level !== "lad") return null;
  const tol = Math.max((b[2] - b[0]) / 2000, 0.00003);
  const rows = await sql`
    select a.name, a.slug, st_asgeojson(st_simplifypreservetopology(coalesce(a.geom_simplified, a.geom), ${tol}), 5) as g
    from core.geo_area a
    where a.market_code = 'uk' and a.level_code = 'lad' and a.is_active and a.geom && ${env(b)}
    limit 100`;
  return fc(rows, (r) => ({ n: r.name, href: `/uk/area/${r.slug}` }));
}

/** Postcode nearest to a clicked point. */
export async function locate(lon: number, lat: number) {
  const [r] = await sql`
    select p.postcode, p.status, a.slug, st_distance(p.geom::geography, st_setsrid(st_point(${lon}, ${lat}), 4326)::geography)::float8 as d
    from mkt_uk.postcode p
    left join core.geo_area a on a.market_code = 'uk' and a.level_code = 'postcode_unit' and a.code = p.postcode
    where p.geom is not null and p.status = 'live'
    order by p.geom <-> st_setsrid(st_point(${lon}, ${lat}), 4326) limit 1`;
  if (!r || r.d > 1500) return null;
  return { postcode: r.postcode as string, href: r.slug ? `/uk/postcode/${r.slug}` : null, distance: Math.round(r.d) };
}

/** Crime groups with LSOA metrics (uk.crime.{g}_12m / _rate), as derived in derive/crime.py. */
export const CRIME_AREA_GROUPS = ["total", "violent", "burglary", "vehicle", "theft", "damage", "asb"] as const;

/** Neighbourhoods (LSOAs) in view with last-12-month crime counts, rates and national percentiles,
 *  plus a label point inside each one for the count bubble. */
export async function crimeAreaLayer(b: BBox) {
  if (b[2] - b[0] > 0.2 || b[3] - b[1] > 0.12) return { areas: fc([], () => ({})), labels: fc([], () => ({})), last: null };
  const [m] = await sql`select max(period)::text as m from core.metric_value where market_code = 'uk' and metric_id = 'uk.crime.total_12m'`;
  if (!m?.m) return { areas: fc([], () => ({})), labels: fc([], () => ({})), last: null };
  const ids = CRIME_AREA_GROUPS.flatMap((g) => [`uk.crime.${g}_12m`, `uk.crime.${g}_rate`]);
  const tol = Math.max((b[2] - b[0]) / 3000, 0.00002);
  const rows = await sql`
    with a as (
      select id, code, name, population, geom from core.geo_area
      where market_code = 'uk' and level_code = 'lsoa' and is_active and geom && ${env(b)}
      limit 1500)
    select a.code, a.name, a.population,
           st_asgeojson(st_simplifypreservetopology(a.geom, ${tol}), 5) as g,
           st_asgeojson(st_pointonsurface(a.geom), 5) as pt,
           jsonb_object_agg(v.metric_id, jsonb_build_array(v.value_num, v.percentile)) filter (where v.metric_id is not null) as mv
    from a left join core.metric_value v
      on v.market_code = 'uk' and v.area_id = a.id and v.metric_id = any(${ids}::text[]) and v.period = ${m.m}::date
         and not v.is_suppressed
    group by a.id, a.code, a.name, a.population, a.geom`;
  const props = (r: Row) => {
    const o: Record<string, unknown> = { c: r.code, nm: r.name, pop: r.population };
    const mv = (r.mv ?? {}) as Record<string, [number | null, number | null]>;
    for (const g of CRIME_AREA_GROUPS) {
      const n = mv[`uk.crime.${g}_12m`]?.[0];
      const rate = mv[`uk.crime.${g}_rate`];
      if (n != null) o[`${g}_n`] = Math.round(n);
      if (rate?.[0] != null) o[`${g}_r`] = Math.round(rate[0] * 10) / 10;
      if (rate?.[1] != null) o[`${g}_p`] = Math.round(rate[1]);
    }
    return o;
  };
  return {
    areas: fc(rows, props),
    labels: fc(rows.map((r: Row) => ({ ...r, g: r.pt })), props),
    last: m.m as string,
  };
}

const METRIC_ID = /^uk\.[a-z0-9_]+(\.[a-z0-9_]+)+$/;

/** Neighbourhoods (LSOAs) in view with the latest value and national percentile of up to six
 *  metrics, as m0_v / m0_p … in request order, plus a label point for the value bubble. */
export async function metricAreaLayer(b: BBox, ids: string[]) {
  const want = ids.filter((x) => METRIC_ID.test(x)).slice(0, 20);
  const none = { areas: fc([], () => ({})), labels: fc([], () => ({})) };
  if (!want.length || b[2] - b[0] > 0.2 || b[3] - b[1] > 0.12) return none;
  const tol = Math.max((b[2] - b[0]) / 3000, 0.00002);
  const rows = await sql`
    with a as (
      select id, code, name, population, geom from core.geo_area
      where market_code = 'uk' and level_code = 'lsoa' and is_active and geom && ${env(b)}
      limit 1500),
    v as (
      select distinct on (v.area_id, v.metric_id) v.area_id, v.metric_id, v.value_num, v.percentile
      from core.metric_value v join a on a.id = v.area_id
      where v.market_code = 'uk' and v.metric_id = any(${want}::text[]) and not v.is_suppressed and v.value_num is not null
      order by v.area_id, v.metric_id, v.period desc),
    -- metrics published for MSOAs only (household income): each neighbourhood takes its MSOA's value
    vm as (
      select distinct on (a.id, v.metric_id) a.id as area_id, v.metric_id, v.value_num, v.percentile
      from a join core.geo_area_link k on k.child_id = a.id and k.relation = 'best_fit'
      join core.geo_area m on m.id = k.parent_id and m.level_code = 'msoa'
      join core.metric mt on mt.id = any(${want}::text[]) and mt.native_level = 'msoa'
      join core.metric_value v on v.market_code = 'uk' and v.area_id = m.id and v.metric_id = mt.id
      where not v.is_suppressed and v.value_num is not null
      order by a.id, v.metric_id, v.period desc),
    vv as (select * from v union all select * from vm where not exists (select 1 from v where v.area_id = vm.area_id and v.metric_id = vm.metric_id))
    select a.code, a.name, a.population,
           st_asgeojson(st_simplifypreservetopology(a.geom, ${tol}), 5) as g,
           st_asgeojson(st_pointonsurface(a.geom), 5) as pt,
           jsonb_object_agg(v.metric_id, jsonb_build_array(v.value_num, v.percentile)) filter (where v.metric_id is not null) as mv
    from a left join vv v on v.area_id = a.id
    group by a.id, a.code, a.name, a.population, a.geom`;
  const props = (r: Row) => {
    const o: Record<string, unknown> = { c: r.code, nm: r.name, pop: r.population };
    const mv = (r.mv ?? {}) as Record<string, [number | null, number | null]>;
    want.forEach((id, i) => {
      const x = mv[id];
      if (x?.[0] != null) o[`m${i}_v`] = Math.round(x[0] * 100) / 100;
      if (x?.[1] != null) o[`m${i}_p`] = Math.round(x[1]);
    });
    return o;
  };
  return { areas: fc(rows, props), labels: fc(rows.map((r: Row) => ({ ...r, g: r.pt })), props) };
}
