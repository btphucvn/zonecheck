import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";

// Extra data for topic detail pages (/uk/postcode/se15-4dx/schools …), beyond what the area
// report already loads. Each part is cached per area and fails soft: a slow part is left out.

const M = "uk";
type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

async function soft<T>(what: string, p: Promise<T>, fallback: T, ms = 9000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([p, new Promise<T>((_, rej) => { timer = setTimeout(() => rej(new Error(`timed out after ${ms} ms`)), ms); })]);
  } catch (e) {
    console.error(`[topic] ${what} failed:`, e instanceof Error ? e.message : e);
    try { cacheLife("minutes"); } catch { /* not in a cache scope */ }
    return fallback;
  } finally { clearTimeout(timer); }
}

const point = (lon: number, lat: number) => sql`st_setsrid(st_point(${lon}, ${lat}), 4326)`;

/* ------------------------------------------------------------ neighbours */

export interface NeighbourValue { code: string; name: string; dist: number; v: number | null; p: number | null }

/** Neighbourhoods (LSOAs) whose centre is within `m` metres, nearest first, with one metric. */
export async function getNeighbourValues(lon: number, lat: number, metricId: string, m = 1000): Promise<NeighbourValue[]> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => soft("neighbours", (async () => {
    const pt = point(lon, lat);
    const rows = await sql`
      with a as (
        select id, code, name, st_distance(centroid::geography, ${pt}::geography)::float8 as d from core.geo_area
        where market_code = ${M} and level_code = 'lsoa' and is_active
          and st_dwithin(centroid, ${pt}, ${m / 60000}) and st_dwithin(centroid::geography, ${pt}::geography, ${m})
        order by d limit 14)
      select a.code, a.name, a.d, x.value_num as v, x.percentile::float8 as p from a
      left join lateral (select value_num, percentile from core.metric_value
                         where market_code = ${M} and area_id = a.id and metric_id = ${metricId} and not is_suppressed
                         order by period desc limit 1) x on true
      order by a.d`;
    return rows.map((r: Row) => ({ code: r.code, name: r.name, dist: r.d, v: r.v, p: r.p }));
  })(), [] as NeighbourValue[]), 2);
}

/* ------------------------------------------------------------ prices */

/** UK HPI average price for the local authority, monthly, last ten years. */
export async function getHpiHistory(ladId: number): Promise<{ period: string; v: number }[]> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => soft("hpi", (async () => {
    const rows = await sql`select period::text as period, value_num as v from core.metric_value
      where market_code = ${M} and area_id = ${ladId} and metric_id = 'uk.hpi.avg_price'
        and period >= current_date - interval '10 years' and value_num is not null order by period`;
    return rows.map((r: Row) => ({ period: r.period, v: r.v }));
  })(), []), 1);
}

/* ------------------------------------------------------------ schools */

export interface SchoolRow {
  id: number; name: string; slug: string | null; type: string; dist: number;
  kind: string | null; gender: string | null; religion: string | null; ages: string | null;
  pupils: number | null; capacity: number | null; fsm: number | null; admissions: string | null;
  rating: { label: string; rank: number | null } | null;
  ks2: number | null; a8: number | null; p8: number | null; offerRate: number | null;
  funding: "State-funded" | "Independent"; oversubscribed: boolean | null;
}

/** Schools within 3 km (up to 60), with GIAS details, Ofsted grade, results and admissions. */
export async function getSchoolsDetail(lon: number, lat: number): Promise<SchoolRow[]> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => soft("schools", (async () => {
    const pt = point(lon, lat);
    const pois = await sql`
      select p.id::int, p.name, p.slug, p.type_code, p.attrs, st_distance(p.geom::geography, ${pt}::geography)::float8 as d
      from core.poi p
      where p.market_code = ${M} and p.status = 'open' and p.type_code in ('school.primary', 'school.secondary', 'school.all_through', 'school.special', 'school.post16')
        and st_dwithin(p.geom, ${pt}, 0.05) and st_dwithin(p.geom::geography, ${pt}::geography, 3000)
      order by p.geom <-> ${pt} limit 60`;
    if (!pois.length) return [];
    const ids = pois.map((p: Row) => p.id);
    const [ratings, metrics] = await Promise.all([
      sql`select distinct on (poi_id) poi_id::int, scheme, grade_label, grade_rank from core.poi_rating
          where poi_id = any(${ids}::bigint[]) and is_current
            and ((scheme = 'ofsted_oeif' and aspect = 'overall') or scheme = 'ofsted_report_card')
          order by poi_id, rated_on desc, (scheme = 'ofsted_oeif') desc`,
      sql`select distinct on (poi_id, metric_id) poi_id::int, metric_id, value_num from core.poi_metric_value
          where poi_id = any(${ids}::bigint[]) and not is_suppressed and value_num is not null
            and metric_id in ('uk.ks2.rwm_expected_pct', 'uk.ks4.attainment8', 'uk.ks4.progress8', 'uk.school.first_pref_offer_rate',
                              'uk.school.first_pref_apps', 'uk.school.places_offered')
          order by poi_id, metric_id, period desc`,
    ]);
    const mv = (id: number, m: string) => (metrics.find((x: Row) => x.poi_id === id && x.metric_id === m)?.value_num as number | undefined) ?? null;
    const num = (x: unknown) => (x == null || x === "" || Number.isNaN(Number(x)) ? null : Number(x));
    return pois.map((p: Row): SchoolRow => {
      const a = (p.attrs ?? {}) as Record<string, string>;
      const r = ratings.find((x: Row) => x.poi_id === p.id);
      const rel = a["ReligiousCharacter (name)"];
      return {
        id: p.id, name: p.name, slug: p.slug, type: p.type_code, dist: p.d,
        kind: a["TypeOfEstablishment (name)"] ?? a["EstablishmentTypeGroup (name)"] ?? null,
        gender: a["Gender (name)"] ?? null,
        religion: rel && !/does not apply|none/i.test(rel) ? rel : null,
        ages: a.StatutoryLowAge && a.StatutoryHighAge ? `${a.StatutoryLowAge} to ${a.StatutoryHighAge}` : null,
        pupils: num(a.NumberOfPupils), capacity: num(a.SchoolCapacity), fsm: num(a.PercentageFSM),
        admissions: a["AdmissionsPolicy (name)"] && !/not applicable/i.test(a["AdmissionsPolicy (name)"]) ? a["AdmissionsPolicy (name)"] : null,
        rating: r ? { label: r.scheme === "ofsted_report_card" ? "Report card" : r.grade_label, rank: r.grade_rank } : null,
        ks2: mv(p.id, "uk.ks2.rwm_expected_pct"), a8: mv(p.id, "uk.ks4.attainment8"), p8: mv(p.id, "uk.ks4.progress8"),
        offerRate: mv(p.id, "uk.school.first_pref_offer_rate"),
        funding: /independent/i.test(a["EstablishmentTypeGroup (name)"] ?? "") ? "Independent" : "State-funded",
        oversubscribed: mv(p.id, "uk.school.first_pref_apps") != null && mv(p.id, "uk.school.places_offered")
          ? mv(p.id, "uk.school.first_pref_apps")! > mv(p.id, "uk.school.places_offered")! : null,
      };
    });
  })(), [] as SchoolRow[], 12000), 3);
}

/* ------------------------------------------------------------ amenities */

export const AMENITY_KINDS: { label: string; types: string[] }[] = [
  { label: "Supermarkets", types: ["shop.supermarket"] },
  { label: "Food shops", types: ["shop.food_retail"] },
  { label: "Restaurants", types: ["food.restaurant"] },
  { label: "Cafes and other food", types: ["food.other"] },
  { label: "Takeaways", types: ["food.takeaway"] },
  { label: "Pubs and bars", types: ["food.pub", "nightlife.nightclub"] },
  { label: "GP practices", types: ["health.gp"] },
  { label: "Pharmacies", types: ["health.pharmacy"] },
  { label: "Dentists", types: ["health.dentist"] },
  { label: "Gyms and sports centres", types: ["leisure.gym", "leisure.sports_centre"] },
  { label: "Libraries", types: ["culture.library"] },
  { label: "Cinemas and theatres", types: ["culture.cinema", "culture.theatre"] },
  { label: "Post offices", types: ["service.post_office"] },
  { label: "Nurseries", types: ["childcare.nursery"] },
  { label: "EV chargers", types: ["transport.ev_charging"] },
];

export interface AmenityKind { label: string; n: number; nearest: { name: string; dist: number }[] }
export interface GpCard { name: string; dist: number; phone: string | null; patients: number | null; rating: string | null; survey: Record<string, number> }

/** Counts within 1 km and the three nearest of each kind; NHS patient survey for the nearest GPs. */
export async function getAmenityDetail(lon: number, lat: number): Promise<{ kinds: AmenityKind[]; gps: GpCard[] }> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => soft("amenities", (async () => {
    const pt = point(lon, lat);
    const types = AMENITY_KINDS.flatMap((k) => k.types);
    const rows = await sql`
      select p.id::int, p.type_code, p.name, p.attrs, st_distance(p.geom::geography, ${pt}::geography)::float8 as d
      from core.poi p
      where p.market_code = ${M} and p.status = 'open' and p.type_code = any(${types}::text[])
        and st_dwithin(p.geom, ${pt}, 0.02) and st_dwithin(p.geom::geography, ${pt}::geography, 1000)`;
    const kinds = AMENITY_KINDS.map((k) => {
      const hit = rows.filter((r: Row) => k.types.includes(r.type_code)).sort((a: Row, b: Row) => a.d - b.d);
      return { label: k.label, n: hit.length, nearest: hit.slice(0, 3).map((r: Row) => ({ name: r.name, dist: r.d })) };
    });
    const gpRows = rows.filter((r: Row) => r.type_code === "health.gp").sort((a: Row, b: Row) => a.d - b.d).slice(0, 4);
    let gps: GpCard[] = [];
    if (gpRows.length) {
      const ids = gpRows.map((r: Row) => r.id);
      const [survey, cqc] = await Promise.all([
        sql`select distinct on (poi_id, metric_id) poi_id::int, metric_id, value_num from core.poi_metric_value
            where poi_id = any(${ids}::bigint[]) and metric_id like 'uk.gp.%' and value_num is not null
            order by poi_id, metric_id, period desc`,
        sql`select distinct on (poi_id) poi_id::int, grade_label from core.poi_rating
            where poi_id = any(${ids}::bigint[]) and scheme = 'cqc' and is_current
            order by poi_id, (aspect = 'overall') desc nulls last, rated_on desc`,
      ]);
      gps = gpRows.map((r: Row) => ({
        name: r.name, dist: r.d, phone: r.attrs?.phone ?? null, patients: r.attrs?.registered_patients ?? null,
        rating: cqc.find((x: Row) => x.poi_id === r.id)?.grade_label ?? null,
        survey: Object.fromEntries(survey.filter((x: Row) => x.poi_id === r.id).map((x: Row) => [x.metric_id, x.value_num])),
      }));
    }
    return { kinds, gps };
  })(), { kinds: [], gps: [] }, 12000), 3);
}

/* ------------------------------------------------------------ planning */

export interface ListedRow { name: string; grade: string | null; dist: number; url: string | null; listed: string | null }

export interface PlanningApp {
  ref: string | null; address: string | null; description: string | null; type: string | null; status: string | null;
  decision: string | null; validDate: string | null; url: string | null; dist: number;
}

/** Planning applications validated in the last two years within 500 m (where published with a location: London so far). */
export async function getPlanningApps(lon: number, lat: number): Promise<{ total: number; recent: PlanningApp[] } | null> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => soft("planning apps", (async () => {
    const pt = point(lon, lat);
    const near = sql`st_dwithin(geom, ${pt}, 0.01) and st_dwithin(geom::geography, ${pt}::geography, 500)
                     and valid_date >= current_date - interval '2 years'`;
    const [[n], rows] = await Promise.all([
      sql`select count(*)::int as n from mkt_uk.planning_application where ${near}`,
      sql`select reference, address, description, app_type_full, status, decision, valid_date::text as vd, url,
                 st_distance(geom::geography, ${pt}::geography)::float8 as d
          from mkt_uk.planning_application where ${near} order by valid_date desc limit 15`,
    ]);
    if (!n?.n) return null;
    return {
      total: n.n,
      recent: rows.map((r: Row) => ({ ref: r.reference, address: r.address, description: r.description, type: r.app_type_full, status: r.status,
        decision: r.decision, validDate: r.vd, url: r.url, dist: r.d })),
    };
  })(), null), 3);
}

/** Listed buildings within 500 m (nearest 12) and brownfield sites within 1 km. */
export async function getPlanningDetail(lon: number, lat: number): Promise<{ listed: ListedRow[]; listedTotal: number; brownfield: number }> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${M}`);
  return scoped(async () => soft("planning", (async () => {
    const pt = point(lon, lat);
    const [listed, [n], [bf]] = await Promise.all([
      sql`select name, attrs, st_distance(geom::geography, ${pt}::geography)::float8 as d from core.poi
          where market_code = ${M} and type_code = 'heritage.listed_building'
            and st_dwithin(geom, ${pt}, 0.01) and st_dwithin(geom::geography, ${pt}::geography, 500)
          order by geom <-> ${pt} limit 12`,
      sql`select count(*)::int as n from core.poi where market_code = ${M} and type_code = 'heritage.listed_building'
          and st_dwithin(geom, ${pt}, 0.01) and st_dwithin(geom::geography, ${pt}::geography, 500)`,
      sql`select count(*)::int as n from core.poi where market_code = ${M} and type_code = 'planning.brownfield_site'
          and st_dwithin(geom, ${pt}, 0.02) and st_dwithin(geom::geography, ${pt}::geography, 1000)`,
    ]);
    return {
      listed: listed.map((r: Row) => ({ name: r.name, grade: r.attrs?.grade ?? null, dist: r.d, url: r.attrs?.documentation_url ?? null, listed: r.attrs?.start_date ?? null })),
      listedTotal: n?.n ?? 0, brownfield: bf?.n ?? 0,
    };
  })(), { listed: [], listedTotal: 0, brownfield: 0 }), 3);
}
