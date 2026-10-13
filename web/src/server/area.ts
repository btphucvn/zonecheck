import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { abandon, scoped, sql } from "@/lib/db";
import { SCORE_CATEGORIES, SCORE_MODEL, categoryScore } from "@/markets/uk/scoring";
import { loadMetricCatalog } from "./meta";
import { fallbackPercentile } from "./quantiles";
import type {
  AreaContext, AreaHead, AreaRef, AreaReport, CategoryScore, MetricMap, Overflow, Poi, RiskPoint, Sale, ZoneExposure,
} from "./types";

const M = "uk";

/**
 * Optional report parts: a failure or slow query hides that part only (logged
 * with context) instead of failing the whole page.
 */
async function soft<T>(what: string, ctx: string, p: Promise<T>, fallback: T, ms = 9000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      p,
      new Promise<T>((_, rej) => { timer = setTimeout(() => rej(new Error(`timed out after ${ms} ms`)), ms); }),
    ]);
  } catch (e) {
    abandon();
    console.error(`[area] ${what} failed for ${ctx}:`, e instanceof Error ? e.message : e);
    // A report missing a part must not stay cached for days: the shortest cacheLife wins,
    // so this entry expires in minutes and the next visit retries the part.
    try { cacheLife("minutes"); } catch { /* not inside a "use cache" scope */ }
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function toRef(r: Row | undefined | null): AreaRef | null {
  if (!r) return null;
  return { id: r.id, level: r.level_code, code: r.code, slug: r.slug, name: r.name, displayName: r.display_name ?? null };
}

/** Area by page level + slug (cached a day; ETL publish revalidates tag market:uk). */
export async function getAreaHead(level: string, slug: string): Promise<AreaHead | null> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(() => loadHead(level, slug));
}

async function loadHead(level: string, slug: string): Promise<AreaHead | null> {
  {
    const [r] = await sql`
      select a.id::int, a.level_code, a.code, a.slug, a.name, a.display_name, a.population, a.households,
             a.area_km2::float8 as area_km2, st_x(a.centroid) as lon, st_y(a.centroid) as lat, a.is_active, a.attrs,
             p.status as pc_status, p.terminated_on::text as pc_terminated, p.lsoa21_code, p.district, p.sector
      from core.geo_area a
      left join mkt_uk.postcode p on a.level_code = 'postcode_unit' and p.postcode = a.code
      where a.market_code = ${M} and a.level_code = ${level} and a.slug = ${slug}`;
    if (!r) return null;
    return {
      ...toRef(r)!,
      population: r.population, households: r.households, areaKm2: r.area_km2, lon: r.lon, lat: r.lat,
      active: r.is_active, attrs: r.attrs ?? {},
      postcode: r.level_code === "postcode_unit"
        ? { status: r.pc_status, terminatedOn: r.pc_terminated, lsoa: r.lsoa21_code, district: r.district, sector: r.sector }
        : null,
    };
  }
}

async function loadContext(head: AreaHead): Promise<AreaContext> {
  const pt = sql`st_setsrid(st_point(${head.lon}, ${head.lat}), 4326)`;
  // Admin parents: nearest live postcode to the centroid (postcode units use their own row).
  const [pc] = head.level === "postcode_unit"
    ? await sql`select lad_code, region_code, country_code, sector, district from mkt_uk.postcode where postcode = ${head.code}`
    : await sql`select lad_code, region_code, country_code, sector, district from mkt_uk.postcode
                where status = 'live' and geom is not null order by geom <-> ${pt} limit 1`;
  const wanted: [string, string][] = [];
  if (pc?.lad_code) wanted.push(["lad", pc.lad_code]);
  if (pc?.region_code) wanted.push(["region", pc.region_code]);
  if (pc?.country_code) wanted.push(["nation", pc.country_code]);
  if (head.level === "postcode_unit") {
    wanted.push(["sector", pc?.sector], ["district", pc?.district]);
    if (head.postcode?.lsoa) wanted.push(["lsoa", head.postcode.lsoa]);
  } else if (head.level === "sector" && pc?.district) {
    wanted.push(["district", pc.district]);
  }
  const lv = wanted.filter((w) => w[1]).map((w) => w[0]);
  const cd = wanted.filter((w) => w[1]).map((w) => w[1]);
  const [parents, [town]] = await Promise.all([
    lv.length
      ? sql`select a.id::int, a.level_code, a.code, a.slug, a.name, a.display_name
            from unnest(${lv}::text[], ${cd}::text[]) as w(lv, cd)
            join core.geo_area a on a.market_code = ${M} and a.level_code = w.lv and a.code = w.cd`
      : Promise.resolve([] as Row[]),
    ["postcode_unit", "sector", "district"].includes(head.level)
      ? sql`select id::int, level_code, code, slug, name, display_name from core.geo_area
            where market_code = ${M} and level_code = 'town' order by centroid <-> ${pt} limit 1`
      : Promise.resolve([] as Row[]),
  ]);
  const byLevel = (l: string) => toRef(parents.find((p: Row) => p.level_code === l));
  const self = toRef({ ...head, level_code: head.level, display_name: head.displayName })!;
  return {
    lad: head.level === "lad" ? self : byLevel("lad"),
    region: head.level === "region" ? self : byLevel("region"),
    nation: byLevel("nation"),
    town: toRef(town),
    district: byLevel("district"),
    sector: byLevel("sector"),
    dataArea: head.level === "postcode_unit" ? (byLevel("lsoa") ?? self) : self,
  };
}

/** Latest period of every metric for each area id. */
async function metricsFor(ids: number[]): Promise<Record<number, MetricMap>> {
  if (!ids.length) return {};
  const rows = await sql`
    select distinct on (v.area_id, v.metric_id)
           v.area_id::int, v.metric_id, v.period::text as period, v.value_num, v.value_json, v.sample_size,
           v.percentile::float8 as percentile, v.is_suppressed
    from core.metric_value v
    where v.market_code = ${M} and v.area_id = any(${ids}::bigint[])
    order by v.area_id, v.metric_id, v.period desc`;
  const out: Record<number, MetricMap> = {};
  for (const r of rows) {
    (out[r.area_id] ??= {})[r.metric_id] = {
      v: r.is_suppressed ? null : r.value_num, j: r.is_suppressed ? null : r.value_json, period: r.period,
      n: r.sample_size, p: r.is_suppressed ? null : r.percentile, suppressed: r.is_suppressed,
    };
  }
  return out;
}

function fillPercentiles(map: MetricMap, level: string) {
  for (const [id, mv] of Object.entries(map)) {
    if (mv.p == null && mv.v != null) mv.p = fallbackPercentile(level, id, mv.v);
  }
}

async function nearestPois(lon: number, lat: number, types: string[], limit: number, opts: { withSlug?: boolean; maxM?: number } = {}): Promise<Poi[]> {
  const pt = sql`st_setsrid(st_point(${lon}, ${lat}), 4326)`;
  const rows = await sql`
    select p.id::int, p.type_code, p.name, p.slug, st_x(p.geom) as lon, st_y(p.geom) as lat,
           st_distance(p.geom::geography, ${pt}::geography)::float8 as dist, p.attrs
    from core.poi p
    where p.market_code = ${M} and p.status = 'open' and p.type_code = any(${types}::text[])
      ${opts.withSlug ? sql`and p.slug is not null` : sql``}
    order by p.geom <-> ${pt}
    limit ${limit}`;
  return rows
    .filter((r: Row) => !opts.maxM || r.dist <= opts.maxM)
    .map((r: Row) => ({ id: r.id, type: r.type_code, name: r.name, slug: r.slug, lon: r.lon, lat: r.lat, dist: r.dist, attrs: r.attrs ?? {} }));
}

async function schoolsNear(lon: number, lat: number): Promise<Poi[]> {
  const pois = await nearestPois(lon, lat, ["school.primary", "school.secondary", "school.all_through"], 10, { withSlug: true, maxM: 4000 });
  if (!pois.length) return [];
  const ids = pois.map((p) => p.id);
  const [ratings, kms] = await Promise.all([
    sql`select distinct on (poi_id) poi_id::int, scheme, grade_label, grade_rank, rated_on::text as rated_on
        from core.poi_rating
        where poi_id = any(${ids}::bigint[]) and is_current
          and ((scheme = 'ofsted_oeif' and aspect = 'overall') or scheme = 'ofsted_report_card')
        order by poi_id, rated_on desc, (scheme = 'ofsted_oeif') desc`,
    sql`select distinct on (poi_id) poi_id::int, metric_id, value_num
        from core.poi_metric_value
        where poi_id = any(${ids}::bigint[]) and metric_id in ('uk.ks2.rwm_expected_pct', 'uk.ks4.attainment8')
          and value_num is not null and not is_suppressed
        order by poi_id, period desc`,
  ]);
  return pois.map((p) => {
    const r = ratings.find((x: Row) => x.poi_id === p.id);
    const k = kms.find((x: Row) => x.poi_id === p.id);
    return {
      ...p,
      rating: r ? { scheme: r.scheme, label: r.scheme === "ofsted_report_card" ? "Report card" : r.grade_label, rank: r.grade_rank, ratedOn: r.rated_on } : null,
      keyMetric: k ? { id: k.metric_id, v: k.value_num } : null,
    };
  });
}

async function stationsNear(lon: number, lat: number): Promise<Poi[]> {
  const pois = await nearestPois(lon, lat, ["station.rail", "station.metro"], 8, { withSlug: true, maxM: 8000 });
  const seen = new Set<string>();
  const uniq = pois.filter((p) => (seen.has(p.name) ? false : (seen.add(p.name), true))).slice(0, 5);
  if (!uniq.length) return [];
  const usage = await sql`
    select distinct on (poi_id) poi_id::int, value_num from core.poi_metric_value
    where poi_id = any(${uniq.map((p) => p.id)}::bigint[]) and metric_id = 'uk.rail.entries_exits'
    order by poi_id, period desc`;
  return uniq.map((p) => {
    const u = usage.find((x: Row) => x.poi_id === p.id);
    return { ...p, keyMetric: u ? { id: "uk.rail.entries_exits", v: u.value_num } : null };
  });
}

async function recentSales(head: AreaHead): Promise<Sale[]> {
  let rows: Row[];
  if (head.level === "postcode_unit" || head.level === "sector" || head.level === "district") {
    // Postcodes via the district index, then a few latest sales per postcode via (postcode, date desc).
    const district = head.level === "district" ? head.code : (head.postcode?.district ?? head.code.split(" ")[0]);
    const pcs = head.level === "postcode_unit"
      ? sql`select ${head.code}::text as postcode`
      : sql`select postcode from mkt_uk.postcode where district = ${district}
            ${head.level === "sector" ? sql`and sector = ${head.code}` : sql``}`;
    rows = await sql`
      select x.* from (${pcs}) p cross join lateral (
        select transfer_date::text as d, price, property_type, tenure, is_new_build, street, postcode
        from mkt_uk.price_paid t where t.postcode = p.postcode and t.ppd_category = 'A'
        order by t.transfer_date desc limit 3) x
      order by x.d desc limit 10`;
  } else if (head.level === "town" || head.level === "lad") {
    rows = await sql`
      select transfer_date::text as d, price, property_type, tenure, is_new_build, street, postcode
      from mkt_uk.price_paid
      where lsoa21_code in (
        select c.code from core.geo_area_link k join core.geo_area c on c.id = k.child_id
        where k.parent_id = ${head.id} and k.relation = 'overlaps' and c.level_code = 'lsoa')
        and transfer_date > now() - interval '18 months' and ppd_category = 'A'
      order by transfer_date desc limit 10`;
  } else return [];
  return rows.map((r: Row) => ({ date: r.d, price: r.price, type: r.property_type, tenure: r.tenure, newBuild: r.is_new_build, street: r.street, postcode: r.postcode }));
}

async function epcSummary(head: AreaHead): Promise<AreaReport["epc"]> {
  let range;
  if (head.level === "postcode_unit") range = sql`postcode = ${head.code}`;
  else if (head.level === "sector") range = sql`postcode >= ${head.code + " "} and postcode < ${head.code + "~"}`;
  else return null; // districts and larger: too many certificates to aggregate per request (needs an ETL metric)
  // One pass over the certificates (a sector is a few thousand rows, read cold from disk);
  // five separate aggregates each re-read the same heap pages and blew the soft timeout.
  const rows = await sql`select current_rating as r, potential_rating as pr, property_type as t,
           construction_age_band as a, total_floor_area_m2::float8 as fa
    from mkt_uk.epc_certificate where is_latest_for_address and ${range}`;
  const ratings: Record<string, number> = {}, potential: Record<string, number> = {}, types: Record<string, number> = {}, ages: Record<string, number> = {};
  const areas: number[] = [];
  const bump = (o: Record<string, number>, k: string) => { o[k] = (o[k] ?? 0) + 1; };
  for (const r of rows as Row[]) {
    if (r.r) bump(ratings, r.r);
    if (r.pr) bump(potential, r.pr);
    bump(types, r.t || "Unknown");
    // Bands are free text ("England and Wales: 1930-1949", "Pre-1900", "2019"): bucket by the first year.
    const band = r.a as string | null;
    const y = band ? Number(band.match(/\d{4}/)?.[0]) : NaN;
    if (band && /(before|pre)/i.test(band)) bump(ages, "Before 1900");
    else if (y) bump(ages, y < 1900 ? "Before 1900" : y < 1930 ? "1900 to 1929" : y < 1950 ? "1930 to 1949" : y < 1976 ? "1950 to 1975" : y < 2000 ? "1976 to 1999" : "2000 onwards");
    if (r.fa != null && r.fa >= 10 && r.fa <= 2000) areas.push(r.fa);
  }
  const total = Object.values(ratings).reduce((s, n) => s + n, 0);
  if (!total) return null;
  areas.sort((x, y) => x - y);
  const mid = areas.length / 2;
  const medianFloorArea = !areas.length ? null : areas.length % 2 ? areas[Math.floor(mid)] : (areas[mid - 1] + areas[mid]) / 2;
  return { ratings, potential, total, medianFloorArea, types, ages };
}

async function zonesFor(head: AreaHead, dataAreaId: number): Promise<ZoneExposure[]> {
  const detailed = ["postcode_unit", "sector", "district"].includes(head.level);
  const [exposure, names] = await Promise.all([
    sql`select zone_type_code, intersects, share_of_area::float8 as sa, share_of_addresses::float8 as sh, nearest_distance_m::float8 as nd
        from core.area_zone_exposure where area_id = ${head.level === "postcode_unit" ? dataAreaId : head.id}`,
    detailed
      ? head.level === "postcode_unit"
        ? sql`select type_code, string_agg(distinct name, ', ') as names from core.zone
              where market_code = ${M} and type_code ~ '^(planning|nature|flood)\\.'
                and st_intersects(geom, st_setsrid(st_point(${head.lon}, ${head.lat}), 4326))
              group by 1`
        : sql`select z.type_code, string_agg(distinct z.name, ', ') as names
              from core.geo_area a join core.zone z on z.market_code = ${M} and st_intersects(z.geom, a.geom)
              where a.id = ${head.id} and a.geom is not null and z.type_code ~ '^(planning|nature)\\.'
              group by 1`
      : Promise.resolve([] as Row[]),
  ]);
  const out: ZoneExposure[] = exposure.map((r: Row) => ({
    type: r.zone_type_code, intersects: r.intersects, shareArea: r.sa, shareAddresses: r.sh, nearestM: r.nd,
    names: names.find((n: Row) => n.type_code === r.zone_type_code)?.names ?? null,
  }));
  for (const n of names) {
    if (!out.some((o) => o.type === n.type_code)) {
      out.push({ type: n.type_code, intersects: true, shareArea: null, shareAddresses: null, nearestM: 0, names: n.names });
    }
  }
  return out;
}

async function listedCount(head: AreaHead): Promise<number | null> {
  if (head.level === "postcode_unit") {
    const [r] = await sql`
      select count(*)::int as n from core.poi p
      where p.type_code = 'heritage.listed_building'
        and st_dwithin(p.geom, st_setsrid(st_point(${head.lon}, ${head.lat}), 4326), 0.006)
        and st_dwithin(p.geom::geography, st_setsrid(st_point(${head.lon}, ${head.lat}), 4326)::geography, 250)`;
    return r?.n ?? null;
  }
  if (head.level !== "sector" && head.level !== "district") return null;
  const [r] = await sql`
    select count(*)::int as n from core.geo_area a join core.poi p
      on p.type_code = 'heritage.listed_building' and st_intersects(p.geom, a.geom)
    where a.id = ${head.id} and a.geom is not null`;
  return r?.n ?? null;
}

/** Zone types checked at a postcode's centre for the risk section. */
const POINT_ZONES = [
  "radon.atlas", "coal.high_risk", "coal.low_risk", "geo.shrink_swell", "geo.landslides", "geo.soluble_rocks",
  "geo.compressible_ground", "geo.collapsible_deposits", "geo.running_sand", "geo.mining_non_coal",
  "flood.historic", "flood.wales_historic", "flood.warning_area", "flood.wales_warning_area", "flood.zone2", "flood.zone3",
  "flood.wales_zone2", "flood.wales_zone3", "coast.erosion_2055", "coast.erosion_2105", "coast.ground_instability", "env.aqma",
];

/** Exact checks at a postcode centre: hazard zones, landfill distance, EA homes at risk, modelled noise. */
async function riskAtPoint(head: AreaHead): Promise<RiskPoint | null> {
  if (head.level !== "postcode_unit") return null;
  const pt = sql`st_setsrid(st_point(${head.lon}, ${head.lat}), 4326)`;
  const nearest = (types: string[], maxM: number) => sql`
    select min(st_distance(z.geom::geography, ${pt}::geography))::float8 as d from core.zone z
    where z.market_code = ${M} and z.type_code = any(${types}::text[])
      and st_dwithin(z.geom, ${pt}, ${maxM / 60000}) and st_dwithin(z.geom::geography, ${pt}::geography, ${maxM})`;
  const [zones, [lh], [la], [rf], noiseTable] = await Promise.all([
    sql`select type_code, max(level_rank)::int as rank from core.zone
        where market_code = ${M} and type_code = any(${POINT_ZONES}::text[]) and st_intersects(geom, ${pt})
        group by 1`,
    nearest(["risk.landfill_historic", "risk.landfill_historic_wales"], 500),
    nearest(["risk.landfill_authorised"], 1000),
    sql`select residential, res_high, res_medium, res_low, res_very_low from mkt_uk.postcode_rofrs where postcode = ${head.code}`,
    sql`select to_regclass('mkt_uk.postcode_noise') is not null as ok`,
  ]);
  // Noise is loaded by a separate ETL step; skip quietly until its table exists.
  const [nz] = noiseTable[0]?.ok
    ? await sql`select road_lden, road_lnight, rail_lden, airport_lden from mkt_uk.postcode_noise where postcode = ${head.code}`
    : [];
  return {
    zones: Object.fromEntries(zones.map((z: Row) => [z.type_code, z.rank])),
    landfillHistoricM: lh?.d ?? null,
    landfillAuthorisedM: la?.d ?? null,
    rofrs: rf ? { residential: rf.residential ?? 0, high: rf.res_high ?? 0, medium: rf.res_medium ?? 0, low: rf.res_low ?? 0, veryLow: rf.res_very_low ?? 0 } : null,
    noise: nz ? { roadLden: nz.road_lden, roadLnight: nz.road_lnight, railLden: nz.rail_lden, airportLden: nz.airport_lden } : null,
  };
}

/** Storm overflows within 3 km, the ones that spilled most first. */
async function overflowsNear(lon: number, lat: number): Promise<Overflow[]> {
  const pt = sql`st_setsrid(st_point(${lon}, ${lat}), 4326)`;
  const rows = await sql`
    select name, attrs, st_distance(geom::geography, ${pt}::geography)::float8 as dist from core.poi
    where market_code = ${M} and type_code = 'environment.storm_overflow' and status = 'open'
      and st_dwithin(geom, ${pt}, 0.05) and st_dwithin(geom::geography, ${pt}::geography, 3000)`;
  return rows
    .map((r: Row) => ({
      name: r.name, company: r.attrs?.company ?? null, water: r.attrs?.receiving_water ?? null,
      spills: r.attrs?.spills ?? null, hours: r.attrs?.spill_hours ?? null, year: r.attrs?.year ?? null, dist: r.dist,
    }))
    .sort((a: Overflow, b: Overflow) => (b.hours ?? -1) - (a.hours ?? -1));
}

async function incidentsNear(lon: number, lat: number): Promise<AreaReport["incidents"]> {
  const pt = sql`st_setsrid(st_point(${lon}, ${lat}), 4326)`;
  const [r] = await sql`
    select count(*)::int as total, count(*) filter (where (attrs->>'worst_category')::int <= 2)::int as serious,
           (current_date - interval '10 years')::date::text as since
    from core.poi where market_code = ${M} and type_code = 'environment.pollution_incident'
      and opened_on >= current_date - interval '10 years'
      and st_dwithin(geom, ${pt}, 0.02) and st_dwithin(geom::geography, ${pt}::geography, 1000)`;
  return r ? { total: r.total, serious: r.serious, since: r.since } : null;
}

/** Residential Property Tribunal decisions for addresses in the postcode, sector or district. */
async function tribunalsFor(head: AreaHead): Promise<AreaReport["tribunals"]> {
  let range;
  if (head.level === "postcode_unit") range = sql`postcode = ${head.code}`;
  else if (head.level === "sector" || head.level === "district") range = sql`postcode >= ${head.code + " "} and postcode < ${head.code + "~"}`;
  else return null;
  const [[c], recent] = await Promise.all([
    sql`select count(*)::int as n from mkt_uk.tribunal_decision where ${range}`,
    sql`select title, case_ref, case_type, published_at::date::text as d, link from mkt_uk.tribunal_decision
        where ${range} order by published_at desc nulls last limit 5`,
  ]);
  return {
    total: c?.n ?? 0,
    recent: recent.map((r: Row) => ({ title: r.title, caseRef: r.case_ref, type: r.case_type, date: r.d, link: r.link })),
  };
}

/** Nearest Ofsted-registered nurseries and pre-schools with their latest grade. */
async function nurseriesNear(lon: number, lat: number): Promise<Poi[]> {
  const pois = (await nearestPois(lon, lat, ["childcare.nursery"], 12, { maxM: 3000 }))
    .filter((p) => !/out-of-school/i.test(p.attrs.subtype ?? "")).slice(0, 6);
  if (!pois.length) return [];
  const ratings = await sql`
    select distinct on (poi_id) poi_id::int, scheme, grade_label, grade_rank, rated_on::text as rated_on
    from core.poi_rating where poi_id = any(${pois.map((p) => p.id)}::bigint[]) and is_current
    order by poi_id, rated_on desc`;
  return pois.map((p) => {
    const r = ratings.find((x: Row) => x.poi_id === p.id);
    return { ...p, rating: r ? { scheme: r.scheme, label: r.scheme === "ofsted_ey_report_card" ? "Report card" : r.grade_label, rank: r.grade_rank, ratedOn: r.rated_on } : null };
  });
}

/** Westminster MP for the constituency containing the point (Boundary-Line + Parliament Members API).
 *  The ETL matches names once (OS and Parliament spell them differently) and stores the GSS code on mkt_uk.mp. */
async function mpAt(lon: number, lat: number): Promise<AreaReport["mp"]> {
  const [r] = await sql`
    select m.name, m.party, m.constituency, m.thumbnail_url from core.zone z
    join mkt_uk.mp m on m.gss_code = z.external_id
    where z.market_code = ${M} and z.type_code = 'admin.westminster_const'
      and st_intersects(z.geom, st_setsrid(st_point(${lon}, ${lat}), 4326))
    limit 1`;
  return r ? { name: r.name, party: r.party, constituency: r.constituency, photo: r.thumbnail_url } : null;
}

/** Latest CQC overall rating for GP and dentist POIs (scheme 'cqc', matched by ODS code in the ETL). */
async function withCqc(pois: Poi[]): Promise<Poi[]> {
  const ids = pois.filter((p) => p.type === "health.gp" || p.type === "health.dentist").map((p) => p.id);
  if (!ids.length) return pois;
  const rows = await sql`
    select distinct on (poi_id) poi_id::int, grade_label, grade_rank, rated_on::text as rated_on from core.poi_rating
    where poi_id = any(${ids}::bigint[]) and scheme = 'cqc' and is_current
    order by poi_id, (aspect = 'overall') desc nulls last, rated_on desc`;
  return pois.map((p) => {
    const r = rows.find((x: Row) => x.poi_id === p.id);
    return r ? { ...p, rating: { scheme: "cqc", label: r.grade_label, rank: r.grade_rank, ratedOn: r.rated_on } } : p;
  });
}

async function nearbyAreas(head: AreaHead) {
  const level = head.level === "postcode_unit" ? "sector" : head.level;
  if (level === "region") {
    const rows = await sql`select id::int, level_code, code, slug, name, display_name, 0::float8 as d from core.geo_area
                           where market_code = ${M} and level_code = 'region' and id <> ${head.id} order by name`;
    return rows;
  }
  const pt = sql`st_setsrid(st_point(${head.lon}, ${head.lat}), 4326)`;
  return sql`
    select g.id::int, g.level_code, g.code, g.slug, g.name, g.display_name,
           st_distance(g.centroid::geography, ${pt}::geography)::float8 as d
    from core.geo_area g
    where g.market_code = ${M} and g.level_code = ${level} and g.is_active and g.id <> ${head.id}
      ${level === "town" ? sql`and coalesce(g.population, 0) > 0` : sql``}
    order by g.centroid <-> ${pt} limit 8`;
}

/** A postcode has no open polygon: outline its addresses instead. Addresses are the UPRNs on its
 *  EPC certificates (OS Open UPRN points), dropping strays more than 400 m from the postcode
 *  centroid; a concave hull buffered 15 m, or a 25 m buffer when there are fewer than 3. */
async function postcodeOutline(postcode: string): Promise<{ geojson: string | null; bbox: [number, number, number, number] | null; approx?: boolean }> {
  const [h] = await sql`
    with c as (select geom from mkt_uk.postcode where postcode = ${postcode} and geom is not null),
    pts as (
      select distinct u.geom from mkt_uk.epc_certificate e
      join mkt_uk.uprn_point u on u.uprn = e.uprn
      cross join c
      where e.is_latest_for_address and e.postcode = ${postcode} and e.uprn is not null
        and st_dwithin(u.geom::geography, c.geom::geography, 400)
      union select geom from c),
    hull as (
      select case when count(*) >= 3
                  then st_buffer(st_concavehull(st_collect(geom), 0.5)::geography, 15)::geometry
                  else st_buffer(st_collect(geom)::geography, 25)::geometry end as geom
      from pts having count(*) >= 1)
    select st_asgeojson(geom, 6) as gj, st_xmin(geom) x0, st_ymin(geom) y0, st_xmax(geom) x1, st_ymax(geom) y1 from hull`;
  if (!h?.gj) return { geojson: null, bbox: null };
  return { geojson: h.gj as string, bbox: [h.x0, h.y0, h.x1, h.y1], approx: true };
}

async function loadGeometry(head: AreaHead): Promise<{ geojson: string | null; bbox: [number, number, number, number] | null; approx?: boolean }> {
  if (head.level === "postcode_unit") return postcodeOutline(head.code);
  const tol = head.level === "region" ? 0.004 : head.level === "lad" ? 0.0008 : 0.0001;
  const [g] = await sql`
    with g as (select coalesce(geom_simplified, st_simplifypreservetopology(geom, ${tol})) as geom
               from core.geo_area where id = ${head.id})
    select st_asgeojson(geom, 5) as gj, st_xmin(geom) x0, st_ymin(geom) y0, st_xmax(geom) x1, st_ymax(geom) y1
    from g where geom is not null`;
  if (g) return { geojson: g.gj as string, bbox: [g.x0, g.y0, g.x1, g.y1] };
  if (head.level !== "sector" && head.level !== "district") return { geojson: null, bbox: null };
  // Postal areas have no official polygon: approximate with a concave hull of their live postcodes (+40 m).
  const district = head.level === "district" ? head.code : head.code.split(" ")[0];
  const [h] = await sql`
    with pts as (select geom from mkt_uk.postcode where district = ${district} and status = 'live' and geom is not null
                 ${head.level === "sector" ? sql`and sector = ${head.code}` : sql``}),
    hull as (select st_buffer(st_concavehull(st_collect(geom), 0.35)::geography, 40)::geometry as geom from pts having count(*) >= 3)
    select st_asgeojson(geom, 5) as gj, st_xmin(geom) x0, st_ymin(geom) y0, st_xmax(geom) x1, st_ymax(geom) y1 from hull`;
  if (!h) return { geojson: null, bbox: null };
  return { geojson: h.gj as string, bbox: [h.x0, h.y0, h.x1, h.y1], approx: true };
}

async function dbCategoryScores(areaId: number): Promise<CategoryScore[]> {
  const rows = await sql`
    select category_code, score::float8 as score, coverage::float8 as coverage
    from core.area_category_score where model_id = ${SCORE_MODEL} and area_id = ${areaId}`;
  return rows.map((r: Row) => ({ code: r.category_code, score: r.score, coverage: r.coverage }));
}

/** Category scores from DB, or recomputed from metric percentiles with the same model. */
export function computeCategories(metrics: MetricMap, catalog: Record<string, { direction: number }>): CategoryScore[] {
  return SCORE_CATEGORIES.map((c) => {
    const r = categoryScore(c, (id) => (metrics[id] ? { p: metrics[id].p, direction: catalog[id]?.direction ?? 0 } : undefined));
    return { code: c.code, score: r.score, coverage: r.coverage };
  });
}

export async function getAreaReport(level: string, slug: string): Promise<AreaReport | null> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`, `area:${level}:${slug}`);
  return scoped(async () => {
    const head = await loadHead(level, slug);
    if (!head) return null;
    const ctx = await loadContext(head);
    const dataId = ctx.dataArea.id;
    const ids = [dataId, ctx.lad?.id, ctx.nation?.id].filter((x): x is number => x != null);
    const ladId = ctx.lad?.id;

    const key = `${level}/${slug}`;
    const detailed = ["postcode_unit", "sector", "district"].includes(head.level);
    const [catalog, mm, geo, dbScores, sales, rentHistory, epc, schools, stations, amenities, zones, listed, ctaxBands, nearbyRows, updated, extras] =
      await Promise.all([
        loadMetricCatalog(M, "en"),
        metricsFor([...new Set(ids)]),
        soft("geometry", key, loadGeometry(head), { geojson: null, bbox: null }),
        dbCategoryScores(dataId),
        soft("sales", key, recentSales(head), [] as Sale[]),
        ladId
          ? sql`select period::text as period, value_num as v from core.metric_value
                where market_code = ${M} and area_id = ${ladId} and metric_id = 'uk.pipr.rental_price'
                  and period >= (current_date - interval '10 years') and value_num is not null order by period`
          : Promise.resolve([] as Row[]),
        soft("epc", key, epcSummary(head), null),
        soft("schools", key, schoolsNear(head.lon, head.lat), [] as Poi[]),
        soft("stations", key, stationsNear(head.lon, head.lat), [] as Poi[]),
        soft("amenities", key, Promise.all([
          nearestPois(head.lon, head.lat, ["health.gp"], 2),
          nearestPois(head.lon, head.lat, ["health.pharmacy"], 1),
          nearestPois(head.lon, head.lat, ["health.dentist"], 1),
          nearestPois(head.lon, head.lat, ["shop.supermarket"], 3),
        ]).then((a) => withCqc(a.flat())), [] as Poi[]),
        soft("zones", key, zonesFor(head, dataId), [] as ZoneExposure[]),
        soft("listed", key, listedCount(head), null),
        ctx.lad
          ? sql`select band, amount_gbp::float8 as amount, financial_year from mkt_uk.council_tax_rate
                where lad_code = ${ctx.lad.code} and parish_code = ''
                  and financial_year = (select max(financial_year) from mkt_uk.council_tax_rate where lad_code = ${ctx.lad.code})
                order by band`
          : Promise.resolve([] as Row[]),
        soft("nearby", key, Promise.resolve(nearbyAreas(head)).then((r) => [...r] as Row[]), [] as Row[]),
        sql`select max(fetched_at)::text as t from ops.dataset_release where status in ('loaded', 'published')`,
        Promise.all([
          soft("risk", key, riskAtPoint(head), null),
          detailed ? soft("overflows", key, overflowsNear(head.lon, head.lat), [] as Overflow[]) : Promise.resolve([] as Overflow[]),
          detailed ? soft("incidents", key, incidentsNear(head.lon, head.lat), null) : Promise.resolve(null),
          soft("tribunals", key, tribunalsFor(head), null),
          detailed ? soft("nurseries", key, nurseriesNear(head.lon, head.lat), [] as Poi[]) : Promise.resolve([] as Poi[]),
          detailed ? soft("mp", key, mpAt(head.lon, head.lat), null) : Promise.resolve(null),
        ]),
      ]);
    const [riskPoint, overflows, incidents, tribunals, nurseries, mp] = extras;

    const metrics = mm[dataId] ?? {};
    const ladMetrics = ladId ? (mm[ladId] ?? {}) : {};
    const nationMetrics = ctx.nation ? (mm[ctx.nation.id] ?? {}) : {};
    fillPercentiles(metrics, ctx.dataArea.level);
    fillPercentiles(ladMetrics, "lad");

    const nearbyIds = nearbyRows.map((r: Row) => r.id as number);
    const nearbyMetrics = nearbyIds.length
      ? await sql`select distinct on (area_id, metric_id) area_id::int, metric_id, value_num from core.metric_value
                  where market_code = ${M} and area_id = any(${nearbyIds}::bigint[])
                    and metric_id in ('uk.price.median', 'uk.crime.total_rate') and not is_suppressed
                  order by area_id, metric_id, period desc`
      : [];
    const nb = (id: number, m: string) => nearbyMetrics.find((x: Row) => x.area_id === id && x.metric_id === m)?.value_num ?? null;

    let categories = dbScores;
    let scoreSource: AreaReport["scoreSource"] = "db";
    if (!categories.some((c) => c.score != null)) {
      categories = computeCategories(metrics, catalog);
      scoreSource = categories.some((c) => c.score != null) ? "computed" : "none";
    }

    return {
      head, ctx, geojson: geo.geojson, bbox: geo.bbox, boundaryApprox: !!geo.approx, metrics, ladMetrics, nationMetrics, categories, scoreSource,
      sales, rentHistory: rentHistory.map((r: Row) => ({ period: r.period, v: r.v })), epc, schools, stations, amenities,
      zones, riskPoint, overflows, incidents, tribunals, nurseries, mp, listedCount: listed,
      ctaxBands: ctaxBands.map((r: Row) => ({ band: r.band, amount: r.amount, year: r.financial_year })),
      nearby: nearbyRows.map((r: Row) => ({ ...toRef(r)!, dist: r.d, price: nb(r.id, "uk.price.median"), crime: nb(r.id, "uk.crime.total_rate") })),
      updatedAt: updated[0]?.t ?? null,
    };
  }, 14);
}

/** Compact data for compare tables and area cards. */
export async function getAreaCard(level: string, slug: string) {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => {
    const head = await loadHead(level, slug);
    if (!head) return null;
    const ctx = await loadContext(head);
    const dataId = ctx.dataArea.id;
    const [catalog, mm, dbScores] = await Promise.all([loadMetricCatalog(M, "en"), metricsFor([dataId]), dbCategoryScores(dataId)]);
    const metrics = mm[dataId] ?? {};
    fillPercentiles(metrics, ctx.dataArea.level);
    let categories = dbScores;
    if (!categories.some((c) => c.score != null)) categories = computeCategories(metrics, catalog);
    const [rent] = ctx.lad
      ? await sql`select value_num from core.metric_value where market_code = ${M} and area_id = ${ctx.lad.id}
                  and metric_id = 'uk.pipr.rental_price_two_bed' order by period desc limit 1`
      : [];
    const [st] = await nearestPois(head.lon, head.lat, ["station.rail", "station.metro"], 1);
    return { head, ctx, metrics, categories, twoBedRent: (rent?.value_num as number | undefined) ?? null, nearestStation: st ?? null };
  });
}
