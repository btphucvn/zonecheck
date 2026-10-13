// Market-agnostic contracts (PLAN §4.3). Core code only talks to these; each
// country implements them in src/markets/<code>/.

export type MarketCode = "uk";

export interface PageLevel {
  /** URL segment, e.g. "sector" in /uk/sector/se15-4 */
  segment: string;
  /** core.geo_level.code */
  level: string;
  /** i18n key under levels.* */
  labelKey: string;
  /** Peer group used for "better than X% of …" wording */
  peerKey: string;
  /** Level ordering, small = detailed */
  rank: number;
}

export type ParsedQuery =
  | { kind: "postcode_unit"; code: string }
  | { kind: "sector"; code: string }
  /** Sector plus the first letter of the unit: "SE15 4A". */
  | { kind: "unit_prefix"; code: string }
  | { kind: "district"; code: string }
  | { kind: "text"; text: string };

export interface ScoreCategoryDef {
  code: string;
  labelKey: string;
  /** metric id → weight; direction comes from core.metric */
  components: Record<string, number>;
  /** report section the category links to */
  section: string;
}

export interface PersonaDef {
  code: string;
  labelKey: string;
  weights: Record<string, number>;
}

export interface MarketAdapter {
  code: MarketCode;
  defaultLocale: string;
  currency: string;
  units: "imperial" | "metric";
  pageLevels: PageLevel[];
  parseQuery(q: string): ParsedQuery;
  levelBySegment(segment: string): PageLevel | undefined;
  segmentForLevel(level: string): string | undefined;
  scoreCategories: ScoreCategoryDef[];
  personas: PersonaDef[];
  attribution: string;
}
