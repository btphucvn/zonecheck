import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";

// Figures that belong to a point rather than a neighbourhood: modelled London air quality at the
// postcode (LAEI 2022, 20 m grid), the PTAL of the nearest 100 m cell, the nearest major roads and
// sources of noise nearby. Each part fails soft: a missing table (not loaded yet) leaves it out.

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface PointExtras {
  air: { no2: number | null; pm10: number | null; pm25: number | null; pm10Days: number | null } | null;
  ptal: { band: string; ai: number } | null;
  roads: { cls: string; number: string | null; name: string | null; dist: number }[];
  /** emergency services within 483 m (0.3 miles), bars/pubs/clubs within 161 m (0.1 miles), as CrystalRoof counts them */
  noise: { kind: "fire" | "ambulance" | "ae" | "hospital" | "pub" | "club"; name: string; dist: number }[];
}

const EMPTY: PointExtras = { air: null, ptal: null, roads: [], noise: [] };

async function part<T>(what: string, p: Promise<T>, fallback: T): Promise<T> {
  try { return await p; } catch (e) {
    console.error(`[point] ${what} failed:`, e instanceof Error ? e.message : e);
    try { cacheLife("minutes"); } catch { /* not in a cache scope */ }
    return fallback;
  }
}

export async function getPointExtras(lon: number, lat: number, postcode: string | null): Promise<PointExtras> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", `point:${lon.toFixed(5)},${lat.toFixed(5)}`);
  return scoped(async () => {
    const pt = sql`st_setsrid(st_point(${lon}, ${lat}), 4326)`;
    const [air, ptal, roads, noise] = await Promise.all([
      postcode
        ? part("air", sql`select no2, pm10, pm25, pm10_days from mkt_uk.postcode_air where postcode = ${postcode}`.then((r) => r[0] ?? null), null)
        : Promise.resolve(null),
      part("ptal", sql`select ptal, ai, st_distance(geom::geography, ${pt}::geography)::float8 as d
                       from mkt_uk.ptal_grid order by geom <-> ${pt} limit 1`.then((r) => (r[0] && r[0].d <= 80 ? r[0] : null)), null),
      part("roads", sql`
        select distinct on (road_class) road_class, road_number, name, st_distance(geom::geography, ${pt}::geography)::float8 as d
        from (select * from mkt_uk.road order by geom <-> ${pt} limit 40) r
        order by road_class, d`.then((r) => [...r]), [] as Row[]),
      part("noise", sql`
        select p.type_code, p.name, coalesce(p.attrs->>'emergency', '') as emergency,
               st_distance(p.geom::geography, ${pt}::geography)::float8 as d
        from core.poi p
        where p.market_code = 'uk' and p.status = 'open'
          and p.type_code in ('emergency.fire_station', 'emergency.ambulance_station', 'health.hospital', 'food.pub', 'nightlife.nightclub')
          and st_dwithin(p.geom, ${pt}, 0.008)
          and st_dwithin(p.geom::geography, ${pt}::geography,
                         case when p.type_code in ('food.pub', 'nightlife.nightclub') then 161 else 483 end)
        order by d limit 30`.then((r) => [...r]), [] as Row[]),
    ]);
    return {
      air: air ? { no2: air.no2, pm10: air.pm10, pm25: air.pm25, pm10Days: air.pm10_days } : null,
      ptal: ptal ? { band: ptal.ptal, ai: ptal.ai } : null,
      roads: (roads as Row[]).map((r) => ({ cls: r.road_class, number: r.road_number, name: r.name, dist: r.d })).sort((a, b) => a.dist - b.dist),
      noise: (noise as Row[]).map((r) => ({
        kind: r.type_code === "emergency.fire_station" ? "fire" : r.type_code === "emergency.ambulance_station" ? "ambulance"
          : r.type_code === "health.hospital" ? (r.emergency === "yes" ? "ae" : "hospital") : r.type_code === "food.pub" ? "pub" : "club",
        name: r.name, dist: r.d,
      })),
    } satisfies PointExtras;
  }).catch(() => EMPTY);
}
