import type { MetadataRoute } from "next";
import { cacheLife } from "next/cache";
import { scoped, sql } from "@/lib/db";
import { RANKINGS } from "@/server/rankings";

// Index policy (PLAN §3.3): postal sectors/districts, towns with residents, LADs,
// regions, schools and stations. Postcode units stay out until they earn it.
const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export async function generateSitemaps() {
  return [0, 1, 2, 3, 4, 5].map((id) => ({ id }));
}

async function rows(id: number): Promise<{ path: string }[]> {
  "use cache";
  cacheLife("days");
  return scoped(async () => (await query(id)).map((r) => ({ path: String(r.path) })));
}

async function query(id: number): Promise<Record<string, unknown>[]> {
  const area = (level: string, seg: string, extra = sql``) => sql`
    select '/uk/' || ${seg} || '/' || slug as path from core.geo_area
    where market_code = 'uk' and level_code = ${level} and is_active and left(coalesce(attrs->>'country', 'E'), 1) <> 'S' ${extra}
    order by slug`;
  switch (id) {
    case 0: {
      const fixed = ["/", "/uk/compare", "/uk/where-to-live", "/uk/rankings", "/uk/tools", "/sources", "/methodology", "/glossary",
        "/uk/tools/stamp-duty", "/uk/tools/mortgage-affordability", "/uk/tools/moving-costs", "/uk/tools/rent-vs-buy",
        ...RANKINGS.map((r) => `/uk/rankings/${r.slug}/england-and-wales`)].map((path) => ({ path }));
      return [...fixed, ...(await area("region", "region")), ...(await area("lad", "area", sql`and left(code, 1) in ('E', 'W')`))];
    }
    case 1: return [...(await area("district", "district"))];
    case 2: return [...(await area("sector", "sector"))];
    case 3: return [...(await area("town", "town", sql`and coalesce(population, 0) >= 500`))];
    case 4: return [...(await sql`select '/uk/school/' || slug as path from core.poi where market_code = 'uk' and type_code like 'school.%' and slug is not null and status = 'open' order by slug limit 50000`)];
    case 5: return [...(await sql`select '/uk/station/' || slug as path from core.poi where market_code = 'uk' and type_code in ('station.rail', 'station.metro') and slug is not null and status = 'open' order by slug`)];
    default: return [];
  }
}

export default async function sitemap({ id }: { id: Promise<string> }): Promise<MetadataRoute.Sitemap> {
  const n = Number(await id);
  return (await rows(n)).map((r) => ({ url: `${SITE}${r.path}` }));
}
