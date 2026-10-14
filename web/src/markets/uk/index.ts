import type { MarketAdapter, PageLevel, ParsedQuery } from "../types";
import { PERSONAS, SCORE_CATEGORIES } from "./scoring";

export const UK_LEVELS: PageLevel[] = [
  { segment: "postcode", level: "postcode_unit", labelKey: "postcode", peerKey: "neighbourhoods", rank: 0 },
  { segment: "sector", level: "sector", labelKey: "sector", peerKey: "sectors", rank: 1 },
  { segment: "district", level: "district", labelKey: "district", peerKey: "districts", rank: 2 },
  { segment: "town", level: "town", labelKey: "town", peerKey: "towns", rank: 3 },
  { segment: "ward", level: "ward", labelKey: "ward", peerKey: "wards", rank: 3 },
  { segment: "area", level: "lad", labelKey: "lad", peerKey: "lads", rank: 4 },
  { segment: "region", level: "region", labelKey: "region", peerKey: "regions", rank: 5 },
];

// Outward code: A9, A99, AA9, AA99, A9A, AA9A. Inward: 9AA.
const OUT = "([A-Z]{1,2}[0-9][A-Z0-9]?)";
const RE_UNIT = new RegExp(`^${OUT}\\s*([0-9][A-Z]{2})$`);
const RE_UNIT_PREFIX = new RegExp(`^${OUT}\\s*([0-9][A-Z])$`);
const RE_SECTOR = new RegExp(`^${OUT}\\s+([0-9])$`);
const RE_SECTOR_TIGHT = new RegExp(`^([A-Z]{1,2}[0-9][A-Z0-9]?)([0-9])$`);
const RE_DISTRICT = new RegExp(`^${OUT}$`);

export function parseUkQuery(raw: string): ParsedQuery {
  const q = raw.trim().toUpperCase().replace(/\s+/g, " ");
  let m = q.match(RE_UNIT);
  if (m) return { kind: "postcode_unit", code: `${m[1]} ${m[2]}` };
  m = q.match(RE_UNIT_PREFIX);
  if (m) return { kind: "unit_prefix", code: `${m[1]} ${m[2]}` };
  m = q.match(RE_SECTOR);
  if (m) return { kind: "sector", code: `${m[1]} ${m[2]}` };
  if (RE_DISTRICT.test(q)) return { kind: "district", code: q };
  // "SE154" is ambiguous (district SE15 + sector digit, or district SE1 54?) – treat as sector of the longest district
  m = q.match(RE_SECTOR_TIGHT);
  if (m && q.length >= 4 && !q.includes(" ")) return { kind: "sector", code: `${m[1]} ${m[2]}` };
  return { kind: "text", text: raw.trim() };
}

/** "SE15 4NX" → "se15-4nx" (matches core.geo_area.slug for postal levels). */
export function postalSlug(code: string): string {
  return code.trim().toLowerCase().replace(/\s+/g, "-");
}

export const uk: MarketAdapter = {
  code: "uk",
  defaultLocale: "en-GB",
  currency: "GBP",
  units: "imperial",
  pageLevels: UK_LEVELS,
  parseQuery: parseUkQuery,
  levelBySegment: (s) => UK_LEVELS.find((l) => l.segment === s),
  segmentForLevel: (lv) => UK_LEVELS.find((l) => l.level === lv)?.segment,
  scoreCategories: SCORE_CATEGORIES,
  personas: PERSONAS,
  attribution:
    "Contains HM Land Registry data © Crown copyright and database right 2026. Contains public sector information licensed under the Open Government Licence v3.0. Contains OS data © Crown copyright and database right 2026. Contains Royal Mail data © Royal Mail copyright and database right 2026. © OpenStreetMap contributors.",
};

export const MARKETS = { uk } as const;
export function getMarket(code: string): MarketAdapter | undefined {
  return (MARKETS as Record<string, MarketAdapter>)[code];
}
