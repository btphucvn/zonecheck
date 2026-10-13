// Plain, serialisable shapes passed from cached server functions to components.

export interface AreaRef {
  id: number;
  level: string;
  code: string;
  slug: string;
  name: string;
  displayName: string | null;
}

export interface MetricValue {
  v: number | null;
  j: unknown;
  period: string;
  n: number | null;
  /** 0–100, higher = larger value, within level + comparison scope */
  p: number | null;
  suppressed: boolean;
}
export type MetricMap = Record<string, MetricValue>;

export interface MetricMeta {
  id: string;
  category: string;
  valueType: string;
  unit: string | null;
  decimals: number;
  direction: number;
  nativeLevel: string | null;
  scope: string | null;
  isEstimate: boolean;
  scorable: boolean;
  sensitivity: string;
  name: string;
  shortName: string | null;
  description: string | null;
  caveats: string | null;
  source: string | null;
  publisher: string | null;
}

export interface Poi {
  id: number;
  type: string;
  name: string;
  slug: string | null;
  lon: number;
  lat: number;
  dist: number;
  attrs: Record<string, string>;
  rating?: { scheme: string; label: string; rank: number | null; ratedOn: string } | null;
  keyMetric?: { id: string; v: number } | null;
}

export interface Sale {
  date: string;
  price: number;
  type: string;
  tenure: string;
  newBuild: boolean;
  street: string | null;
  postcode: string | null;
}

export interface ZoneExposure {
  type: string;
  intersects: boolean;
  shareArea: number | null;
  shareAddresses: number | null;
  nearestM: number | null;
  names?: string | null;
}

/** Hazard checks at a postcode's centre point (postcode units only). */
export interface RiskPoint {
  /** zone type → highest class at the point (level_rank, null for yes/no zones) */
  zones: Record<string, number | null>;
  landfillHistoricM: number | null;
  landfillAuthorisedM: number | null;
  /** EA homes in this postcode by river/sea flood risk band */
  rofrs: { residential: number; high: number; medium: number; low: number; veryLow: number } | null;
  /** Defra Round 4 modelled noise at the postcode centre, dB (0 = below the modelled floor) */
  noise: { roadLden: number | null; roadLnight: number | null; railLden: number | null; airportLden: number | null } | null;
}

export interface Overflow {
  name: string;
  company: string | null;
  water: string | null;
  spills: number | null;
  hours: number | null;
  year: number | null;
  dist: number;
}

export interface TribunalCase {
  title: string;
  caseRef: string | null;
  type: string | null;
  date: string | null;
  link: string;
}

export interface AreaHead extends AreaRef {
  population: number | null;
  households: number | null;
  areaKm2: number | null;
  lon: number;
  lat: number;
  active: boolean;
  attrs: Record<string, unknown>;
  /** postcode units only */
  postcode?: { status: string; terminatedOn: string | null; lsoa: string | null; district: string; sector: string } | null;
}

export interface AreaContext {
  lad: AreaRef | null;
  region: AreaRef | null;
  nation: AreaRef | null;
  town: AreaRef | null;
  district: AreaRef | null;
  sector: AreaRef | null;
  /** level actually holding the statistics shown (LSOA for postcode units) */
  dataArea: AreaRef;
}

export interface CategoryScore {
  code: string;
  score: number | null;
  coverage: number;
}

export interface AreaReport {
  head: AreaHead;
  ctx: AreaContext;
  geojson: string | null;
  bbox: [number, number, number, number] | null;
  /** boundary drawn from postcode points, not an official polygon */
  boundaryApprox: boolean;
  metrics: MetricMap;
  ladMetrics: MetricMap;
  nationMetrics: MetricMap;
  categories: CategoryScore[];
  scoreSource: "db" | "computed" | "none";
  sales: Sale[];
  rentHistory: { period: string; v: number }[];
  epc: {
    ratings: Record<string, number>; potential: Record<string, number>; total: number; medianFloorArea: number | null;
    types: Record<string, number>; ages: Record<string, number>;
  } | null;
  schools: Poi[];
  stations: Poi[];
  amenities: Poi[];
  zones: ZoneExposure[];
  riskPoint: RiskPoint | null;
  overflows: Overflow[];
  /** EA pollution incidents within 1 km over the last 10 years */
  incidents: { total: number; serious: number; since: string } | null;
  tribunals: { total: number; recent: TribunalCase[] } | null;
  nurseries: Poi[];
  mp: { name: string; party: string | null; constituency: string; photo: string | null } | null;
  listedCount: number | null;
  ctaxBands: { band: string; amount: number; year: string }[];
  nearby: (AreaRef & { dist: number; price: number | null; crime: number | null })[];
  updatedAt: string | null;
}
