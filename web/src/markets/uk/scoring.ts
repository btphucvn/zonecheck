import type { PersonaDef, ScoreCategoryDef } from "../types";

// Mirror of model uk.v1 in get-data/uk/derive/scoring.py (PLAN §3.5).
// When core.area_category_score has rows for the active model the web reads
// those; otherwise it rebuilds category scores from metric percentiles with
// exactly these components. Keep the two files in sync.
export const SCORE_MODEL = "uk.v1";

export const SCORE_CATEGORIES: ScoreCategoryDef[] = [
  { code: "affordability", labelKey: "affordability", section: "prices", components: { "uk.price.median": 2, "uk.ctax.band_d": 1 } },
  {
    code: "safety", labelKey: "safety", section: "safety",
    components: { "uk.crime.total_rate": 2, "uk.crime.violent_rate": 1, "uk.crime.burglary_rate": 1, "uk.crime.asb_rate": 1 },
  },
  {
    code: "schools", labelKey: "schools", section: "schools",
    components: { "uk.schools.primary_quality": 1, "uk.schools.secondary_quality": 1, "uk.access.primary_dist_m": 0.5, "uk.access.secondary_dist_m": 0.5 },
  },
  { code: "transport", labelKey: "transport", section: "transport", components: { "uk.tcm.overall": 2, "uk.access.rail_dist_m": 1, "uk.access.bus_stops_500m": 1 } },
  {
    code: "amenities", labelKey: "amenities", section: "amenities",
    components: { "uk.access.gp_dist_m": 1, "uk.access.supermarket_dist_m": 1, "uk.access.pharmacy_dist_m": 0.5, "uk.access.park_dist_m": 1, "uk.access.food_1km": 0.5 },
  },
  { code: "environment", labelKey: "environment", section: "environment", components: { "uk.pcm.no2": 1, "uk.pcm.pm25": 1, "uk.zone.flood_zone3_share": 1, "uk.zone.sw_high_share": 1 } },
  { code: "connectivity", labelKey: "connectivity", section: "connectivity", components: { "uk.bb.gigabit_pct": 2, "uk.bb.sfbb_pct": 1, "uk.bb.no_decent_pct": 1 } },
  { code: "economy", labelKey: "economy", section: "people", components: { "uk.income.net": 1, "uk.iod25.imd_score": 1, "uk.wimd25.overall_score": 1 } },
];

export const PERSONAS: PersonaDef[] = [
  { code: "buyer", labelKey: "buyer", weights: { affordability: 3, safety: 2, schools: 1, transport: 2, amenities: 1, environment: 2, connectivity: 1, economy: 1 } },
  { code: "family", labelKey: "family", weights: { affordability: 2, safety: 3, schools: 3, transport: 1, amenities: 2, environment: 2, connectivity: 1, economy: 1 } },
  { code: "renter", labelKey: "renter", weights: { affordability: 3, safety: 2, schools: 0.5, transport: 3, amenities: 2, environment: 1, connectivity: 2, economy: 1 } },
  { code: "commuter", labelKey: "commuter", weights: { affordability: 2, safety: 1, schools: 0.5, transport: 4, amenities: 1, environment: 1, connectivity: 2, economy: 1 } },
  { code: "newcomer", labelKey: "newcomer", weights: { affordability: 3, safety: 2, schools: 1, transport: 3, amenities: 2, environment: 1, connectivity: 2, economy: 1 } },
  { code: "retiree", labelKey: "retiree", weights: { affordability: 2, safety: 3, schools: 0, transport: 1, amenities: 3, environment: 3, connectivity: 1, economy: 1 } },
];

export const SCORING_METRICS = [...new Set(SCORE_CATEGORIES.flatMap((c) => Object.keys(c.components)))];

/** Category score (0–100) from component percentiles; null when < 50% of weight has data. */
export function categoryScore(
  cat: ScoreCategoryDef,
  pct: (metricId: string) => { p: number | null; direction: number } | undefined,
): { score: number | null; coverage: number } {
  let sw = 0, sum = 0, all = 0;
  for (const [id, w] of Object.entries(cat.components)) {
    all += w;
    const v = pct(id);
    if (!v || v.p == null) continue;
    sum += w * (v.direction < 0 ? 100 - v.p : v.p);
    sw += w;
  }
  if (!all) return { score: null, coverage: 0 };
  const coverage = sw / all;
  return { score: coverage >= 0.5 ? Math.round((sum / sw) * 10) / 10 : null, coverage };
}

/** Overall persona score; categories without a score are dropped and weights re-normalised. */
export function overallScore(cats: Record<string, number | null>, weights: Record<string, number>): number | null {
  let s = 0, t = 0;
  for (const [c, w] of Object.entries(weights)) {
    const v = cats[c];
    if (v == null || !w) continue;
    s += v * w;
    t += w;
  }
  return t ? Math.round(s / t) : null;
}
