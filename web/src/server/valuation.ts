import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";

// Instant estimate for one home, built only from open data and shown with its workings:
//   value ≈ floor area (latest EPC) × price per m² of comparable sales, each sale moved to today with the
//   local authority's UK House Price Index. Comparables: Land Registry sales matched to an EPC (for floor area),
//   same broad type (flat/maisonette vs house), same postcode sector over 24 months, widened to the district
//   when the sector has fewer than MIN_COMPS. A previous sale of the same address is shown as a cross-check.

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const MIN_COMPS = 12;

export interface AddressOption { key: string; label: string; type: string | null; floorArea: number | null; rooms: number | null }

export interface Valuation {
  address: string; postcode: string; type: string | null; builtForm: string | null; floorArea: number; rooms: number | null;
  epcDate: string; rating: string | null;
  low: number; mid: number; high: number;
  comps: number; scope: string; perSqm: { q1: number; q2: number; q3: number };
  confidence: "high" | "medium" | "low";
  lastSale: { price: number; date: string; adjusted: number | null } | null;
  hpiMonth: string | null;
}

const title = (s: string) => s.toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase()).replace(/\b(\d+)([A-Z])\b/g, (_, n, l) => n + l);
const isFlat = (t: string | null) => /flat|maisonette/i.test(t ?? "");

export async function listAddresses(postcode: string): Promise<AddressOption[]> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", `valuation:${postcode}`);
  return scoped(async () => {
    const rows = await sql`
      select lmk_key, split_part(address_key, '|', 1) as addr, property_type, total_floor_area_m2::float8 as fa, habitable_rooms
      from mkt_uk.epc_certificate
      where postcode = ${postcode} and is_latest_for_address and total_floor_area_m2 > 10
      order by split_part(address_key, '|', 1)`;
    // natural order: "2 Adys Road" before "10 Adys Road"
    return rows.map((r: Row) => ({ key: r.lmk_key, label: title(r.addr), type: r.property_type, floorArea: r.fa, rooms: r.habitable_rooms }))
      .sort((a, b) => a.label.localeCompare(b.label, "en", { numeric: true }));
  });
}

export async function getValuation(lmkKey: string): Promise<Valuation | null> {
  "use cache";
  cacheLife("days");
  cacheTag("market:uk", `valuation:${lmkKey}`);
  return scoped(async () => {
    const [e] = await sql`
      select e.lmk_key, split_part(e.address_key, '|', 1) as addr, e.postcode, e.property_type, e.built_form,
             e.total_floor_area_m2::float8 as fa, e.habitable_rooms, e.lodgement_date::text as d, e.current_rating,
             p.sector, p.district, p.lad_code, p.postcode as pc
      from mkt_uk.epc_certificate e
      join mkt_uk.postcode p on p.postcode = e.postcode
      where e.lmk_key = ${lmkKey}`;
    if (!e || !e.fa) return null;
    const flat = isFlat(e.property_type);
    const [lad] = await sql`select id from core.geo_area where market_code = 'uk' and level_code = 'lad' and code = ${e.lad_code}`;
    const hpi = lad ? await sql`select to_char(period, 'YYYY-MM') as m, value_num as v from core.metric_value
                                 where market_code = 'uk' and area_id = ${lad.id} and metric_id = 'uk.hpi.index' and value_num > 0
                                 order by period` : [];
    const idx = new Map<string, number>(hpi.map((r: Row) => [r.m, r.v]));
    const latest = hpi.length ? hpi[hpi.length - 1] : null;
    const adj = (date: string, price: number) => {
      const at = idx.get(date.slice(0, 7));
      return latest && at ? (price * latest.v) / at : price;
    };
    const comps = async (col: "sector" | "district", code: string) => sql`
      select t.price::float8 as price, t.transfer_date::text as d, ec.total_floor_area_m2::float8 as fa
      from mkt_uk.postcode q
      join mkt_uk.price_paid t on t.postcode = q.postcode
      join mkt_uk.ppd_epc_match m on m.transaction_id = t.transaction_id
      join mkt_uk.epc_certificate ec on ec.lmk_key = m.lmk_key
      where q.${sql(col)} = ${code} and t.ppd_category = 'A' and t.transfer_date >= current_date - interval '24 months'
        and ec.total_floor_area_m2 between 15 and 600
        and ${flat ? sql`t.property_type = 'F'` : sql`t.property_type in ('D', 'S', 'T')`}`;
    let rows = await comps("sector", e.sector);
    let scope = `postcode sector ${e.sector}`;
    if (rows.length < MIN_COMPS) { rows = await comps("district", e.district); scope = `postcode district ${e.district}`; }
    const ppsqm = rows.map((r: Row) => adj(r.d, r.price) / r.fa).filter((x: number) => x > 300 && x < 40000).sort((a: number, b: number) => a - b);
    if (ppsqm.length < 5) return null;
    const q = (p: number) => ppsqm[Math.min(ppsqm.length - 1, Math.max(0, Math.round(p * (ppsqm.length - 1))))];
    const q1 = q(0.25), q2 = q(0.5), q3 = q(0.75);
    const round = (x: number) => Math.round(x / 5000) * 5000;
    const spread = (q3 - q1) / q2;
    const confidence = ppsqm.length >= 30 && spread < 0.35 ? "high" : ppsqm.length >= 12 && spread < 0.6 ? "medium" : "low";
    // previous sale of this address (matched through the EPC register), as a cross-check
    const [ls] = await sql`
      select t.price::float8 as price, t.transfer_date::text as d
      from mkt_uk.ppd_epc_match m join mkt_uk.price_paid t on t.transaction_id = m.transaction_id
      join mkt_uk.epc_certificate x on x.lmk_key = m.lmk_key
      where x.address_key = (select address_key from mkt_uk.epc_certificate where lmk_key = ${lmkKey}) and t.ppd_category = 'A'
      order by t.transfer_date desc limit 1`;
    return {
      address: title(e.addr), postcode: e.pc, type: e.property_type, builtForm: e.built_form, floorArea: e.fa, rooms: e.habitable_rooms,
      epcDate: e.d, rating: e.current_rating,
      low: round(e.fa * q1), mid: round(e.fa * q2), high: round(e.fa * q3),
      comps: ppsqm.length, scope, perSqm: { q1: Math.round(q1), q2: Math.round(q2), q3: Math.round(q3) }, confidence,
      lastSale: ls ? { price: ls.price, date: ls.d, adjusted: idx.size ? round(adj(ls.d, ls.price)) : null } : null,
      hpiMonth: latest?.m ?? null,
    };
  });
}
