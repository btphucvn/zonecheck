import "server-only";
import { cacheLife } from "next/cache";
import { scoped, sql } from "@/lib/db";
import { parseUkQuery, postalSlug, uk } from "@/markets/uk";

export interface SearchHit {
  kind: "postcode" | "sector" | "district" | "town" | "ward" | "area" | "region" | "school" | "station" | "street";
  label: string;
  detail: string;
  href: string;
}

const LEVEL_KIND: Record<string, SearchHit["kind"]> = { town: "town", ward: "ward", lad: "area", region: "region", district: "district" };

/** "CHOUMERT ROAD" → "Choumert Road", "ST. JOHN'S HILL" → "St. John's Hill". */
function titleCase(s: string): string {
  return s.toLowerCase().replace(/(^|[\s\-(/.])([a-z])/g, (_, p: string, c: string) => p + c.toUpperCase());
}

function unitHit(r: Row): SearchHit {
  const where = [r.street, r.post_town].filter(Boolean).map((x) => titleCase(String(x))).join(", ");
  const detail = r.status === "live" ? "Postcode" : "Postcode no longer in use";
  // a street borrowed from the nearest postcode is a hint, not this postcode's address
  if (where && r.is_nearest) return { kind: "postcode", label: r.postcode, detail: `${detail} near ${where}`, href: `/uk/postcode/${r.slug}` };
  return { kind: "postcode", label: where ? `${where}, ${r.postcode}` : r.postcode, detail, href: `/uk/postcode/${r.slug}` };
}

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/**
 * mkt_uk.postcode_street is filled by the ETL step `derive streets`; until that has run on a database the
 * table is missing, so postcode lookups fall back to plain postcodes instead of failing.
 */
async function withStreets<T>(q: (streets: boolean) => PromiseLike<T>): Promise<T> {
  try {
    return await q(true);
  } catch (e) {
    // 42P01: table missing, 42703: an older build of it without the newer columns
    if (!["42P01", "42703"].includes((e as { code?: string }).code ?? "")) throw e;
    console.warn("[search] mkt_uk.postcode_street is missing or outdated; run `python -m uk derive streets`");
    return q(false);
  }
}

/** Live units whose postcode starts with `prefix` ("SE15 4" / "SE15 4A"), via a range scan on the primary key. */
function unitsWithPrefix(prefix: string, limit: number): Promise<Row[]> {
  return withStreets(
    (st) => sql`
      select p.postcode, p.status, a.slug ${st ? sql`, s.street, s.post_town, s.is_nearest` : sql``}
      from mkt_uk.postcode p
      join core.geo_area a on a.market_code = 'uk' and a.level_code = 'postcode_unit' and a.code = p.postcode
      ${st ? sql`left join mkt_uk.postcode_street s on s.postcode = p.postcode` : sql``}
      where p.postcode >= ${prefix} and p.postcode < ${prefix + "~"} and p.status = 'live'
      order by p.postcode limit ${limit}`,
  );
}

/**
 * Streets whose "street post_town" starts with `q` ("choumert ro", "high street, harrow"), one row per street
 * and post town, linked to its busiest postcode.
 */
async function streetsLike(q: string): Promise<Row[]> {
  const words = q.toUpperCase().replace(/[%_\\,]/g, " ").replace(/\s+/g, " ").trim();
  if (words.length < 4) return [];
  return withStreets(async (st) => {
    if (!st) return [];
    return sql`
      select distinct on (s.street, s.post_town) s.street, s.post_town, s.postcode, a.slug, sum(s.sales) over (partition by s.street, s.post_town) as total
      from mkt_uk.postcode_street s
      join mkt_uk.postcode p on p.postcode = s.postcode and p.status = 'live'
      join core.geo_area a on a.market_code = 'uk' and a.level_code = 'postcode_unit' and a.code = s.postcode
      where s.street || ' ' || coalesce(s.post_town, '') like ${words + "%"} and not s.is_nearest
      order by s.street, s.post_town, s.sales desc`.then((rows) => [...rows].sort((a, b) => b.total - a.total).slice(0, 4));
  });
}

/** Postcodes resolve exactly; places and schools match by trigram similarity. */
export async function search(q: string, limit = 8): Promise<SearchHit[]> {
  "use cache";
  cacheLife("hours");
  return scoped(async () => {
    const query = q.trim().slice(0, 80);
    if (query.length < 2) return [];
    const parsed = parseUkQuery(query);

    if (parsed.kind === "postcode_unit") {
      const [r] = await withStreets(
        (st) => sql`
          select p.postcode, p.status, p.sector, a.slug ${st ? sql`, s.street, s.post_town, s.is_nearest` : sql``}
          from mkt_uk.postcode p
          left join core.geo_area a on a.market_code = 'uk' and a.level_code = 'postcode_unit' and a.code = p.postcode
          ${st ? sql`left join mkt_uk.postcode_street s on s.postcode = p.postcode` : sql``}
          where p.postcode_compact = ${parsed.code.replace(/\s/g, "")}`,
      );
      if (r) {
        if (r.slug) return [unitHit(r)];
        return [{ kind: "sector", label: r.sector, detail: `Postcode ${r.postcode} is no longer in use. Showing its sector`, href: `/uk/sector/${postalSlug(r.sector)}` }];
      }
    }
    if (parsed.kind === "unit_prefix" || parsed.kind === "sector") {
      // "SE15 4" or "SE15 4A": the sector itself, then the live units under it with their street names
      const sector = parsed.kind === "sector" ? parsed.code : parsed.code.slice(0, -1);
      const [[sec], units] = await Promise.all([
        sql`select code, slug from core.geo_area where market_code = 'uk' and level_code = 'sector' and slug = ${postalSlug(sector)}`,
        unitsWithPrefix(parsed.code, limit),
      ]);
      const hits: SearchHit[] = [];
      if (sec && parsed.kind === "sector") hits.push({ kind: "sector", label: sec.code, detail: "Postcode sector", href: `/uk/sector/${sec.slug}` });
      hits.push(...units.map(unitHit));
      if (hits.length) return hits;
    }
    if (parsed.kind === "district") {
      const [r] = await sql`select code, slug from core.geo_area where market_code = 'uk' and level_code = 'district' and slug = ${postalSlug(parsed.code)}`;
      const hits: SearchHit[] = [];
      if (r) hits.push({ kind: "district", label: r.code, detail: "Postcode district", href: `/uk/district/${r.slug}` });
      const sectors = await sql`select code, slug from core.geo_area where market_code = 'uk' and level_code = 'sector'
                                and slug like ${postalSlug(parsed.code) + "-%"} and is_active order by code limit ${limit - 1}`;
      for (const s of sectors) hits.push({ kind: "sector", label: s.code, detail: "Postcode sector", href: `/uk/sector/${s.slug}` });
      if (hits.length) return hits;
    }

    const norm = query.toLowerCase();
    const [places, pois, streets] = await Promise.all([
      sql`
        select level_code, code, slug, name, display_name, population, similarity(core.normalize_text(name), core.normalize_text(${norm})) as sim,
               case when level_code = 'ward' then (select l.name from core.geo_area l where l.market_code = 'uk' and l.level_code = 'lad'
                                                   and l.code = g.attrs->>'lad_code') end as lad_name
        from core.geo_area g
        where market_code = 'uk' and level_code in ('town', 'ward', 'lad', 'region') and is_active
          and core.normalize_text(name) % core.normalize_text(${norm})
        order by (core.normalize_text(name) = core.normalize_text(${norm})) desc,
                 (core.normalize_text(name) like core.normalize_text(${norm}) || '%') desc,
                 sim desc, coalesce(population, 0) desc
        limit ${limit}`,
      sql`
        select type_code, name, slug, postal_code, similarity(core.normalize_text(name), core.normalize_text(${norm})) as sim
        from core.poi
        where market_code = 'uk' and slug is not null and status = 'open'
          and (type_code like 'school.%' or type_code in ('station.rail', 'station.metro'))
          and core.normalize_text(name) % core.normalize_text(${norm})
        order by sim desc limit 5`,
      streetsLike(query),
    ]);

    const placeHits = places.map((p) => {
      const kind = LEVEL_KIND[p.level_code];
      const detail = p.level_code === "lad" ? "Local authority" : p.level_code === "region" ? "Region" : p.level_code === "ward" ? `Ward${p.lad_name ? `, ${p.lad_name}` : ""}` : (p.display_name && p.display_name !== p.name ? p.display_name.replace(`${p.name}, `, "") : "Town or place");
      return { hit: { kind, label: p.name, detail, href: `/uk/${uk.segmentForLevel(p.level_code)}/${p.slug}` } as SearchHit, strong: String(p.name).toLowerCase().startsWith(norm) };
    });
    const streetHits: SearchHit[] = streets.map((r) => ({
      kind: "street", label: [r.street, r.post_town].filter(Boolean).map((x) => titleCase(String(x))).join(", "), detail: `Street, ${r.postcode}`, href: `/uk/postcode/${r.slug}`,
    }));
    // places the query is a prefix of ("send"), then streets ("high street, harr"), then fuzzy place matches
    const out: SearchHit[] = [
      ...placeHits.filter((p) => p.strong).map((p) => p.hit),
      ...streetHits,
      ...placeHits.filter((p) => !p.strong).map((p) => p.hit),
    ];
    for (const p of pois) {
      const station = p.type_code.startsWith("station.");
      out.push({ kind: station ? "station" : "school", label: p.name, detail: `${station ? "Station" : "School"}${p.postal_code ? `, ${p.postal_code}` : ""}`, href: `/uk/${station ? "station" : "school"}/${p.slug}` });
    }
    return out.slice(0, limit + 3);
  });
}
