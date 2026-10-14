import type { ReactNode } from "react";
import { fmtNumber } from "@/lib/format";
import { mv, val } from "../helpers";
import type { MapMetric } from "../MetricMap";
import { Block, Facts, Score, ShareRows } from "./blocks";
import { decileOf } from "./crimeModel";
import { areaMap, keyRuler, keyVerdict, lad, metricMap, moneyShort, nextDoor, type TopicData, type TopicView } from "./topics";

// Affluence: household income, deprivation in detail, occupations and qualifications, one sub-tab each
// (/uk/<level>/<slug>/affluence, …/affluence/deprivation, …/occupation, …/qualification).

export const AFFLUENCE_TABS = [
  { id: "income", label: "Household income" },
  { id: "deprivation", label: "Deprivation" },
  { id: "occupation", label: "Occupation" },
  { id: "qualification", label: "Qualifications" },
];

/** Shares of residents (uk.share.*): this area against the borough, the region and the country. */
export function shareTable(d: TopicData, rows: { id: string; label: string }[], unit: string, against: "lad" | "region" = "lad") {
  const { r } = d.h;
  const otherMap = against === "region" ? r.regionMetrics : r.ladMetrics;
  const otherName = against === "region" ? r.ctx.region?.name : lad(d);
  const out = rows.map((x) => ({ label: x.label, here: val(r.metrics, x.id), other: val(otherMap, x.id) }))
    .filter((x): x is { label: string; here: number; other: number | null } => x.here != null);
  return out.length ? <ShareRows rows={out} other={otherName ?? null} unit={unit} /> : null;
}

/** "In SE15 4: 66%, Southwark 42%, London 38%, England 34%" as facts. */
export function threeWay(d: TopicData, id: string, fmt: (x: number) => string): { k: string; v: ReactNode }[] {
  const { r } = d.h;
  const items: { k: string; v: ReactNode }[] = [{ k: d.name, v: val(r.metrics, id) != null ? fmt(val(r.metrics, id)!) : null }];
  if (r.ctx.lad && r.ctx.lad.id !== r.ctx.dataArea.id) items.push({ k: r.ctx.lad.name, v: val(r.ladMetrics, id) != null ? fmt(val(r.ladMetrics, id)!) : null });
  if (r.ctx.region) items.push({ k: r.ctx.region.name, v: val(r.regionMetrics, id) != null ? fmt(val(r.regionMetrics, id)!) : null });
  if (r.ctx.nation) items.push({ k: r.ctx.nation.name, v: val(r.nationMetrics, id) != null ? fmt(val(r.nationMetrics, id)!) : null });
  return items;
}

const pct = (x: number) => `${x < 10 ? x.toFixed(1) : Math.round(x)}%`;
const level = (p: number) => (p >= 80 ? "very high" : p >= 60 ? "high" : p >= 40 ? "about average" : p >= 20 ? "low" : "very low");

/* ------------------------------------------------------------ deprivation domains */

// Wording is our own summary of the MHCLG technical report; sub-domains sit under their domain.
const DOMAINS: { k: string; label: string; what: string; subs?: [string, string][] }[] = [
  { k: "income", label: "Income", what: "People on low incomes, in or out of work, who pass the means tests for benefits and tax credits." },
  { k: "employment", label: "Employment", what: "Working-age people who want to work but cannot because of unemployment, sickness, disability or caring." },
  { k: "education", label: "Education, skills and training", what: "Low attainment among children and a lack of qualifications among adults.",
    subs: [["sub_children", "Children and young people"], ["sub_adult_skills", "Adult skills"]] },
  { k: "health", label: "Health and disability", what: "Risk of dying early and of poor physical or mental health." },
  { k: "crime", label: "Crime", what: "Risk of being a victim of violence, burglary, theft or criminal damage." },
  { k: "barriers", label: "Barriers to housing and services", what: "How far away key services are, and how hard it is to afford or find a home.",
    subs: [["sub_geo_barriers", "Distance to services"], ["sub_wider_barriers", "Affordability, overcrowding and homelessness"]] },
  { k: "living_env", label: "Living environment", what: "Quality of housing indoors, and air quality and road accidents outdoors.",
    subs: [["sub_indoors", "Indoors: housing condition and heating"], ["sub_outdoors", "Outdoors: air quality and road traffic accidents"]] },
  { k: "idaci", label: "Children in low-income families", what: "Share of children aged 0 to 15 living in income-deprived households." },
  { k: "idaopi", label: "Older people in low-income homes", what: "Share of people aged 60 and over who are income deprived." },
];

/** IoD decile (1 = most deprived) → CrystalRoof-style "deprivation level" where 10 is the most deprived. */
const depLevel = (decile: number) => 11 - Math.round(decile);

/** IoD decile of a domain (1 = most deprived): the LSOA's own, or for larger areas from the national rank of the
 *  population-weighted score (higher score = more deprived). */
function iodDecile(d: TopicData, k: string): number | null {
  const { r } = d.h;
  const dec = val(r.metrics, `uk.iod25.${k}_decile`);
  if (dec != null) return dec;
  const p = mv(r.metrics, `uk.iod25.${k}_score`)?.p;
  return p == null ? null : 11 - decileOf(p);
}

function DepRow({ label, decile, what, sub }: { label: string; decile: number; what?: string; sub?: boolean }) {
  const lvl = depLevel(decile);
  return (
    <li className={sub ? "sub" : undefined}>
      <span>{label}{what && <small>{what}</small>}</span>
      <span className="tp-dec" role="img" aria-label={`${label}: deprivation level ${lvl} of 10`}>
        {Array.from({ length: 10 }, (_, i) => <i key={i} className={i + 1 === lvl ? "on" : undefined} />)}
      </span>
      <b>{lvl}/10</b>
    </li>
  );
}

const IOD_MAP: MapMetric[] = [
  ["imd", "Overall deprivation"], ["income", "Income"], ["employment", "Employment"], ["education", "Education, skills and training"],
  ["health", "Health and disability"], ["crime", "Crime"], ["barriers", "Barriers to housing and services"], ["living_env", "Living environment"],
  ["idaci", "Children in low-income families"], ["idaopi", "Older people in low-income homes"], ["sub_children", "Sub-domain: children and young people"],
  ["sub_adult_skills", "Sub-domain: adult skills"], ["sub_geo_barriers", "Sub-domain: distance to services"], ["sub_wider_barriers", "Sub-domain: wider barriers"],
  ["sub_indoors", "Sub-domain: indoors"], ["sub_outdoors", "Sub-domain: outdoors"],
].map(([k, label]) => ({ id: `uk.iod25.${k}_decile`, label: `${label} (decile, 10 = least deprived)`, fmt: "decile", dir: 1 }));

/* ------------------------------------------------------------ tabs */

function income(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const p = mv(r.metrics, "uk.income.net")?.p ?? null;
  const facts = threeWay(d, "uk.income.net", moneyShort);
  return {
    title: `Household income in ${d.name}`,
    description: `Average household income in ${d.name} after tax and after housing costs, rated against England and Wales and compared with ${lad(d) ?? "the local authority"} and ${r.ctx.region?.name ?? "the region"}.`,
    verdict: keyVerdict(d, "uk.income.net", ["Higher household incomes", "Lower household incomes"], 1),
    dek: "ONS small-area income estimates are modelled for neighbourhoods of about 3,000 households (MSOAs), so neighbouring streets share one figure.",
    map: metricMap(d, [
      { id: "uk.income.net", label: "Household income after tax, a year", fmt: "money", dir: 1 },
      { id: "uk.income.net_ahc", label: "Household income after housing costs", fmt: "money", dir: 1 },
      { id: "uk.iod25.income_decile", label: "Income deprivation decile (10 = least deprived)", fmt: "decile", dir: 1 },
    ]),
    ruler: keyRuler(d, "uk.income.net", moneyShort, "Average household income after tax, a year"),
    main: (
      <>
        <Block id="income" title="How well off" note="Score out of 10 against every neighbourhood in England and Wales: 10 is the richest tenth.">
          <Score p={p} label={p != null ? `${level(p)[0].toUpperCase()}${level(p).slice(1)} household income` : ""}
            sub={val(r.metrics, "uk.income.net") != null ? `${moneyShort(val(r.metrics, "uk.income.net")!)} a year after tax` : undefined} />
          <Facts items={facts.map((f) => ({ ...f, k: `After tax: ${f.k}` }))} />
        </Block>
        <Block id="ahc" title="After housing costs" note="Income left after rent or mortgage, water and council tax, the measure ONS uses for poverty.">
          <Facts items={threeWay(d, "uk.income.net_ahc", moneyShort)} />
        </Block>
      </>
    ),
    side: <Facts items={[
      { k: "Before tax", v: val(r.metrics, "uk.income.total") != null ? moneyShort(val(r.metrics, "uk.income.total")!) : null, note: "Total household income" },
      { k: "Universal Credit claimants", v: val(r.metrics, "uk.benefit.uc_rate") != null ? `${fmtNumber(val(r.metrics, "uk.benefit.uc_rate")!, intl, 1)} per 100` : null, note: "Residents aged 16 to 64, DWP" },
      { k: "House price to earnings", v: val(r.ladMetrics, "uk.afford.median_ratio") != null ? `${fmtNumber(val(r.ladMetrics, "uk.afford.median_ratio")!, intl, 1)}×` : null, note: `${r.ctx.lad?.name ?? "Local authority"}, ONS` },
    ]} />,
    after: nextDoor(d, (x) => `D${Math.round(x)}`, 1, "Income deprivation decile of the neighbourhoods next door, 10 = least deprived."),
    source: "Sources: ONS income estimates for small areas (financial year ending 2023), DWP Stat-Xplore, ONS housing affordability.",
  };
}

// WIMD 2025 domains (Wales): ranks 1–1,917 (1 = most deprived) shown on the same 1–10 deprivation-level scale
const WIMD: [string, string][] = [["overall", "Overall (WIMD)"], ["income", "Income"], ["employment", "Employment"], ["health", "Health"],
  ["education", "Education"], ["access", "Access to services"], ["housing", "Housing"], ["safety", "Community safety"], ["environment", "Physical environment"]];
const WIMD_N = 1917;

function walesDeprivation(d: TopicData): TopicView {
  const { r } = d.h;
  const rank = (k: string) => val(r.metrics, `uk.wimd25.${k}_rank`);
  const dec = (x: number) => Math.min(10, Math.floor(((x - 1) / WIMD_N) * 10) + 1);
  const overall = rank("overall");
  return {
    title: `Deprivation in ${d.name}`,
    description: `How deprived ${d.name} is on each domain of the Welsh Index of Multiple Deprivation 2025.`,
    verdict: overall != null ? `Deprivation level ${11 - dec(overall)} out of 10 (10 = most deprived tenth of Wales)` : "",
    dek: "The Welsh Index of Multiple Deprivation ranks all 1,917 neighbourhoods in Wales on eight domains. Levels run from 1 (least deprived tenth) to 10 (most deprived).",
    map: areaMap(d, {}),
    main: (
      <Block id="domains" title="Deprivation domains (Wales)" note="Ranked within Wales only, so levels are not comparable with English neighbourhoods.">
        <ul className="tp-deciles tp-domains">
          {WIMD.map(([k, label]) => { const v = rank(k); return v == null ? null : <DepRow key={k} label={label} decile={dec(v)} />; })}
        </ul>
      </Block>
    ),
    side: <Facts items={[{ k: "National rank", v: overall != null ? `${fmtNumber(overall, d.h.intl)} of ${fmtNumber(WIMD_N, d.h.intl)}` : null, note: "1 = most deprived" }]} />,
    source: "Source: Welsh Government, Welsh Index of Multiple Deprivation 2025.",
  };
}

function deprivation(d: TopicData): TopicView {
  const { r } = d.h;
  const england = r.ctx.nation?.code?.startsWith("E");
  if (!england && r.ctx.nation?.code?.startsWith("W")) return walesDeprivation(d);
  const imd = iodDecile(d, "imd");
  return {
    title: `Deprivation in ${d.name}`,
    description: `How deprived ${d.name} is on each of the seven domains of the English Indices of Deprivation 2025 and their sub-domains, with a map of every neighbourhood.`,
    verdict: imd != null ? `Deprivation level ${depLevel(imd)} out of 10 (10 = most deprived tenth of England)` : "",
    dek: england ? "The Indices of Deprivation rank all 33,755 neighbourhoods in England on seven domains. Levels here run from 1 (least deprived tenth) to 10 (most deprived)." : "Wales publishes its own index (WIMD 2025); the overall rank is shown in the report.",
    map: england ? metricMap(d, IOD_MAP) : areaMap(d, {}),
    main: england ? (
      <Block id="domains" title="Deprivation domains" note="Each domain is ranked separately; the overall index weights income and employment most (22.5% each).">
        <ul className="tp-deciles tp-domains">
          {imd != null && <DepRow label="Overall (Index of Multiple Deprivation)" decile={imd} />}
          {DOMAINS.map((x) => {
            const v = iodDecile(d, x.k);
            if (v == null) return null;
            return [
              <DepRow key={x.k} label={x.label} decile={v} what={x.what} />,
              ...(x.subs ?? []).map(([sk, sl]) => {
                const sv = iodDecile(d, sk);
                return sv == null ? null : <DepRow key={sk} label={sl} decile={sv} sub />;
              }),
            ];
          })}
        </ul>
      </Block>
    ) : <p>The English Indices of Deprivation cover England only.</p>,
    side: england ? <Facts items={[
      { k: "National rank", v: val(r.metrics, "uk.iod25.imd_rank") != null ? `${fmtNumber(val(r.metrics, "uk.iod25.imd_rank")!, d.h.intl)} of 33,755` : null, note: "1 = most deprived" },
      { k: lad(d) ?? "Local authority", v: mv(r.ladMetrics, "uk.iod25.imd_score")?.p != null ? `Level ${decileOf(mv(r.ladMetrics, "uk.iod25.imd_score")!.p!)}/10` : null, note: "Rank of the average score among local authorities" },
    ]} /> : undefined,
    after: nextDoor(d, (x) => `D${Math.round(x)}`, 1, "Overall deprivation decile next door, 10 = least deprived."),
    source: "Source: MHCLG English Indices of Deprivation 2025 (File 7).",
  };
}

const OCC = [
  { id: "uk.share.managerial_professional", label: "Managerial and professional" },
  { id: "uk.share.intermediate_occupations", label: "Intermediate, small employers, self-employed" },
  { id: "uk.share.routine_manual", label: "Routine and manual" },
  { id: "uk.share.never_worked", label: "Never worked, long-term unemployed" },
  { id: "uk.share.fulltime_students", label: "Full-time students" },
];

function occupation(d: TopicData): TopicView {
  const { r } = d.h;
  const prof = mv(r.metrics, "uk.share.managerial_professional");
  const routine = mv(r.metrics, "uk.share.routine_manual");
  return {
    title: `Occupations in ${d.name}`,
    description: `What residents of ${d.name} do for a living: managerial and professional, intermediate and routine occupations (NS-SEC, Census 2021), compared with ${lad(d) ?? "the local authority"} and ${r.ctx.region?.name ?? "the region"}.`,
    verdict: prof?.v != null && prof.p != null ? `${pct(prof.v)} of residents aged 16+ work in managerial or professional jobs, a ${level(prof.p)} share` : "",
    dek: "A high share of professionals usually goes with better services and steadier house prices. Census 2021, residents aged 16 and over, by the National Statistics Socio-economic Classification.",
    map: metricMap(d, OCC.map((x) => ({ id: x.id, label: `${x.label} (%)`, fmt: "pct", dir: 0 }))),
    ruler: keyRuler(d, "uk.share.managerial_professional", (x) => pct(x), "Managerial and professional occupations, % of residents aged 16+"),
    main: (
      <>
        <Block id="score" title="Concentration of professionals" note="Score out of 10 against every neighbourhood in England and Wales.">
          <Score p={prof?.p} label={`${pct(prof?.v ?? 0)} managerial and professional`} sub={routine?.v != null ? `${pct(routine.v)} in routine and manual jobs (${decileOf(routine.p ?? 0)}/10)` : undefined} />
        </Block>
        <Block id="nssec" title="Occupation groups" note={`Share of residents aged 16+ in each group, here and in ${lad(d) ?? "the local authority"}.`}>
          {shareTable(d, OCC, "% of residents 16+")}
        </Block>
      </>
    ),
    side: <Facts items={threeWay(d, "uk.share.managerial_professional", pct).map((f) => ({ ...f, k: `Managerial & professional: ${f.k}` }))} />,
    source: "Source: ONS Census 2021, table TS062 (NS-SeC).",
  };
}

const QUAL = [
  { id: "uk.share.degree", label: "University degree or higher" },
  { id: "uk.share.alevels", label: "A levels or equivalent" },
  { id: "uk.share.apprenticeship", label: "Apprenticeship" },
  { id: "uk.share.gcses", label: "5+ GCSEs or equivalent" },
  { id: "uk.share.some_gcses", label: "1–4 GCSEs or entry level" },
  { id: "uk.share.other_qualifications", label: "Other (vocational, foreign)" },
  { id: "uk.share.no_qualifications", label: "No qualifications" },
];

function qualification(d: TopicData): TopicView {
  const { r } = d.h;
  const deg = mv(r.metrics, "uk.share.degree");
  const none = mv(r.metrics, "uk.share.no_qualifications");
  return {
    title: `Qualifications in ${d.name}`,
    description: `Highest qualification of residents of ${d.name}: degree holders, A levels, GCSEs, apprenticeships and no qualifications (Census 2021).`,
    verdict: deg?.v != null && deg.p != null ? `${pct(deg.v)} of residents aged 16+ hold a degree or higher, a ${level(deg.p)} share` : "",
    dek: "Census 2021, highest level of qualification of residents aged 16 and over.",
    map: metricMap(d, [
      { id: "uk.share.degree", label: "Degree or higher (%)", fmt: "pct", dir: 0 },
      { id: "uk.share.no_qualifications", label: "No qualifications (%)", fmt: "pct", dir: 0 },
      { id: "uk.share.alevels", label: "A levels or equivalent (%)", fmt: "pct", dir: 0 },
      { id: "uk.share.apprenticeship", label: "Apprenticeship (%)", fmt: "pct", dir: 0 },
    ]),
    ruler: keyRuler(d, "uk.share.degree", (x) => pct(x), "Residents aged 16+ with a degree or higher"),
    main: (
      <>
        <Block id="score" title="Concentration of degree holders" note="Score out of 10 against every neighbourhood in England and Wales.">
          <Score p={deg?.p} label={`${pct(deg?.v ?? 0)} with a degree or higher`} sub={none?.v != null ? `${pct(none.v)} have no qualifications (${decileOf(none.p ?? 0)}/10)` : undefined} />
        </Block>
        <Block id="levels" title="Highest qualification" note={`Share of residents aged 16+, here and in ${lad(d) ?? "the local authority"}.`}>
          {shareTable(d, QUAL, "% of residents 16+")}
        </Block>
      </>
    ),
    side: <Facts items={threeWay(d, "uk.share.degree", pct).map((f) => ({ ...f, k: `Degree or higher: ${f.k}` }))} />,
    source: "Source: ONS Census 2021, table TS067.",
  };
}

export function affluence(d: TopicData): TopicView | null {
  switch (d.tab) {
    case null: case "income": return income(d);
    case "deprivation": return deprivation(d);
    case "occupation": return occupation(d);
    case "qualification": return qualification(d);
    default: return null;
  }
}
