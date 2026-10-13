// Measures offered on the home-page map of local authorities (shared by client and server).

export interface ChoroplethMetric {
  id: string;
  label: string;
  /** -1: lower is better for residents (drawn green), 1: higher is better */
  direction: -1 | 1;
  format: "money" | "moneyMonth" | "rate" | "decimal" | "score";
  unitNote: string;
}

export const CHOROPLETH_METRICS: ChoroplethMetric[] = [
  { id: "uk.price.median", label: "House prices", direction: -1, format: "money", unitNote: "Median sale price, last 24 months" },
  { id: "uk.pipr.rental_price", label: "Rents", direction: -1, format: "moneyMonth", unitNote: "Average private rent per month" },
  { id: "uk.crime.total_rate", label: "Crime", direction: -1, format: "rate", unitNote: "Crimes per 1,000 residents, last 12 months" },
  { id: "uk.income.net", label: "Income", direction: 1, format: "money", unitNote: "Net household income per year" },
  { id: "uk.pcm.no2", label: "Air quality", direction: -1, format: "decimal", unitNote: "Background NO₂, µg/m³" },
  { id: "uk.tcm.overall", label: "Transport", direction: 1, format: "score", unitNote: "Connectivity score, 0 to 100" },
];

export function formatChoropleth(m: ChoroplethMetric, v: number): string {
  const gbp = (x: number) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 }).format(x);
  switch (m.format) {
    case "money": return gbp(v);
    case "moneyMonth": return `${gbp(v)}/mo`;
    case "rate": return v.toLocaleString("en-GB", { maximumFractionDigits: 0 });
    case "decimal": return v.toLocaleString("en-GB", { maximumFractionDigits: 1 });
    default: return v.toLocaleString("en-GB", { maximumFractionDigits: 0 });
  }
}
