import type { Metadata } from "next";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { SCORE_CATEGORIES, PERSONAS, SCORE_MODEL } from "@/markets/uk/scoring";
import { getMetricCatalog } from "@/server/meta";

export const metadata: Metadata = {
  title: "How area scores work",
  description: "The method behind ZoneCheck area scores: percentiles, eight groups, weights for each kind of mover, and what is never scored.",
  alternates: { canonical: "/methodology" },
};

async function Components() {
  const { t } = await getI18n();
  const cat = await getMetricCatalog("uk", "en");
  return (
    <div className="scroll-x">
      <table className="data">
        <thead><tr><th>Group</th><th>Measures (weight)</th></tr></thead>
        <tbody>
          {SCORE_CATEGORIES.map((c) => (
            <tr key={c.code}>
              <th>{t.categories[c.code as keyof typeof t.categories]}</th>
              <td>{Object.keys(c.components).length
                ? Object.entries(c.components).map(([id, w]) => `${cat[id]?.name ?? id} (${w}${cat[id]?.direction === -1 ? ", lower is better" : ""})`).join("; ")
                : "Waiting for Ofcom Connected Nations data. Not counted until then."}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function Methodology() {
  const { t } = await getI18n();
  return (
    <main className="wrap">
      <div className="page-head"><h1>{t.footer.methodology}</h1><p>Model {SCORE_MODEL}. Every step is public so you can check how a number was reached.</p></div>
      <div className="prose">
        <h2>1. Percentiles within a fair comparison group</h2>
        <p>For each measure we rank an area against all areas of the same kind: postcode sectors against postcode sectors, local authorities against local authorities. Measures built differently in England and Wales, such as the deprivation indices, are only ranked within their own nation. The result is a percentile from 0 to 100.</p>
        <p>Where lower is better (crime, prices, distance to a GP), the percentile is flipped so that 100 always means better for residents.</p>
        <h2>2. Eight groups</h2>
        <p>Each group score is the weighted average of its measures. A group needs at least half of its weight to have data, otherwise it is left out.</p>
        <Suspense fallback={<p>Loading…</p>}><Components /></Suspense>
        <h2>3. Weights for who is moving</h2>
        <p>The overall score is a weighted average of the group scores. Each kind of mover starts with its own weights, and you can change them with the sliders on any area page. Groups without data are dropped and the remaining weights re-normalised.</p>
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th />{SCORE_CATEGORIES.map((c) => <th key={c.code} className="r">{t.categories[c.code as keyof typeof t.categories]}</th>)}</tr></thead>
            <tbody>
              {PERSONAS.map((p) => (
                <tr key={p.code}><th>{t.personas[p.code as keyof typeof t.personas]}</th>{SCORE_CATEGORIES.map((c) => <td key={c.code} className="r num">{p.weights[c.code] ?? 0}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
        <h2>4. What we never score</h2>
        <p>Ethnicity, religion and nationality are never used in any score or filter. Census figures on them are published by ONS; we do not rank areas on them.</p>
        <h2>5. Small numbers and estimates</h2>
        <p>Median prices need at least five sales. Figures from fewer records are hidden rather than shown with false precision. Crime figures are hidden for months where a police force did not send data. Estimates are labelled as estimates.</p>
        <h2>6. Flood and ground checks</h2>
        <p>On a postcode page we test the postcode&apos;s centre point against each hazard map: flood zones, the Environment Agency list of homes at risk from rivers and the sea, mapped past floods, the radon atlas, coal mining areas, BGS GeoSure ground hazards, landfill sites and coastal erosion zones. On sector, district and larger pages we show the share of residents, counted at each postcode, inside each zone. A check is green when nothing is found, amber when something is worth asking about, and red when the hazard is significant (for example Flood Zone 3, a coal mining high risk area, or radon above the action level in 5% or more of homes). GeoSure is mapped on 5 km hexagons and is indicative only. The &ldquo;Before you make an offer&rdquo; list is generated from the amber and red checks.</p>
        <h2>7. Limits</h2>
        <p>Area figures describe surroundings, not a particular home. They do not replace a survey, conveyancing searches or financial advice.</p>
      </div>
    </main>
  );
}
