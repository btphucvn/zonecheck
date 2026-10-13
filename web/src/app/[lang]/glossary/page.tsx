import type { Metadata } from "next";
import { getI18n } from "@/i18n/dictionaries";

export const metadata: Metadata = {
  title: "Glossary of UK property terms",
  description: "Plain-English definitions of council tax, leasehold, freehold, Ofsted, EPC, stamp duty, LSOA and other terms used on ZoneCheck.",
  alternates: { canonical: "/glossary" },
};

const TERMS: [string, string][] = [
  ["Article 4 direction", "A council order that removes some permitted development rights, so changes like new windows or extensions need planning permission."],
  ["Conservation area", "An area of special architectural or historic interest. Demolition, tree work and some alterations need consent."],
  ["Council tax band", "Every home in England and Wales sits in a band, A to H (A to I in Wales), set from its 1991 (2003 in Wales) value. Band D is the reference rate councils publish."],
  ["EPC", "Energy Performance Certificate. Rates a home from A (most efficient) to G, with its floor area and heating. Needed whenever a home is sold or let."],
  ["Flood Zone 2 and 3", "Environment Agency zones for river and sea flooding, ignoring defences. Zone 3 has a 1% or greater yearly chance from rivers (0.5% from the sea); Zone 2 between 0.1% and 1%."],
  ["Freehold", "You own the building and the land it stands on, with no end date."],
  ["Green belt", "Protected land around towns where new building is tightly restricted."],
  ["Leasehold", "You own the home for a fixed number of years under a lease from the freeholder. Common for flats. Check the years left, ground rent and service charge."],
  ["Listed building", "A building on Historic England's (or Cadw's) list for its historic or architectural interest. Most changes need listed building consent."],
  ["LSOA", "Lower Layer Super Output Area: a small statistical neighbourhood of about 1,500 people, used for crime and deprivation figures."],
  ["Ofsted", "The inspectorate for schools in England. Until 2025 it gave one overall grade (Outstanding to Inadequate); from November 2025 schools get a report card with grades for each area."],
  ["Postcode sector", "The postcode district plus the first digit of the second half, for example SE15 4. Around 3,000 homes."],
  ["Stamp duty (SDLT)", "Tax paid by the buyer of a home in England. Wales has its own Land Transaction Tax. First-time buyers pay less on homes up to £500,000."],
  ["Radon", "A natural radioactive gas from rocks and soil. UKHSA's action level is 200 Bq/m³ in a home. The radon atlas shows the share of homes in each 1 km square expected to exceed it; a 3-month test confirms a single home."],
  ["Coal mining reporting area", "Land over past or present coal workings, mapped by the Mining Remediation Authority (formerly the Coal Authority). Conveyancers order a CON29M search for homes inside it. Development high risk areas have shallow workings or mine entries."],
  ["Shrink–swell clay", "Clay soils that swell when wet and shrink when dry, the most common cause of subsidence in England. BGS GeoSure rates the susceptibility as low, moderate or significant."],
  ["Storm overflow", "A relief point where the sewer system can discharge diluted sewage into rivers or the sea during heavy rain. Water companies report how often and how long each one spills."],
  ["PTAL", "Public Transport Accessibility Level: TfL's London-only measure of access to buses, rail and tube, from 0 (worst) to 6b (best)."],
  ["Residential Property Tribunal", "The First-tier Tribunal (Property Chamber) decides disputes over service charges, leases, rents and licensing. Its decisions are published on GOV.UK."],
  ["Indices of Deprivation", "Official measures ranking every small area in England (IoD 2025) or Wales (WIMD 2025) on income, employment, health, education, crime, housing and living environment."],
];

export default async function Glossary() {
  const { t } = await getI18n();
  return (
    <main className="wrap">
      <div className="page-head"><h1>{t.footer.glossary}</h1><p>Terms you will meet when moving in England and Wales, in plain English.</p></div>
      <dl className="prose">
        {TERMS.map(([k, v]) => (
          <div key={k} id={k.toLowerCase().replace(/[^a-z0-9]+/g, "-")}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </main>
  );
}
