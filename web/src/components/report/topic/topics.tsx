import Link from "next/link";
import type { ReactNode } from "react";
import { fmtDistance, fmtMoney, fmtNumber, fmtPct, walkMinutes } from "@/lib/format";
import type { CrimeDetail } from "@/server/crime";
import type { AmenityKind, GpCard, ListedRow, NeighbourValue, SchoolRow } from "@/server/topic";
import { AreaMap, type LayerKey } from "../AreaMap";
import { CrimeMap } from "../CrimeMap";
import { MetricMap, type MapMetric } from "../MetricMap";
import { M } from "../MetricTile";
import { LineChart } from "../bits";
import { mv, val, type H } from "../helpers";
import * as S from "../sections";
import { Block, DotRows, Facts, ShareRows, compareShares } from "./blocks";
import { crimeModel, decileOf, monthLabel, rampOf } from "./crimeModel";
import { NextDoor, Ruler, verdictFor, type Fmt, type Mark } from "./Shell";

// What each topic page shows: its map, the key figure for the ruler and the verdict, and the
// evidence. Topics reuse the report section as their core and add the detail behind it.

export interface TopicData {
  h: H; name: string; base: string;
  crime?: CrimeDetail | null; neighbours?: NeighbourValue[]; hpi?: { period: string; v: number }[];
  schools?: SchoolRow[]; amenities?: { kinds: AmenityKind[]; gps: GpCard[] };
  planning?: { listed: ListedRow[]; listedTotal: number; brownfield: number };
}

export interface TopicView {
  title: string; description: string; verdict: string; dek?: ReactNode; map: ReactNode;
  ruler?: ReactNode; main: ReactNode; side?: ReactNode; after?: ReactNode; source?: ReactNode;
}

/** Neighbourhood metrics used by each topic's next-door strip, loaded by the page. */
export const NEIGHBOUR_METRIC: Record<string, string> = {
  crime: "uk.crime.total_rate", prices: "uk.price.median", schools: "uk.schools.primary_quality", transport: "uk.access.rail_dist_m",
  amenities: "uk.access.gp_dist_m", environment: "uk.pcm.no2", broadband: "uk.bb.gigabit_pct", people: "uk.iod25.imd_decile",
};

/* ------------------------------------------------------------ shared pieces */

const flat = (node: ReactNode) => <div className="tp-flat">{node}</div>;

function mapBase(d: TopicData) {
  const { r } = d.h;
  const unit = r.head.level === "postcode_unit";
  return {
    center: [r.head.lon, r.head.lat] as [number, number], bbox: r.bbox, geojson: r.geojson, label: d.name,
    rings: unit ? [400, 800] : [], highlight: r.ctx.dataArea.level === "lsoa" ? r.ctx.dataArea.code : null,
  };
}

function metricMap(d: TopicData, metrics: MapMetric[]) {
  return <MetricMap {...mapBase(d)} metrics={metrics} />;
}

function areaMap(d: TopicData, layers: Partial<Record<LayerKey, boolean>>) {
  const b = mapBase(d);
  const lv = d.h.r.head.level;
  return (
    <AreaMap center={b.center} bbox={b.bbox} geojson={b.geojson} label={b.label}
      levelForNeighbours={lv === "postcode_unit" ? "sector" : ["sector", "district", "lad"].includes(lv) ? lv : null}
      radiusM={lv === "postcode_unit" ? 800 : undefined}
      initialLayers={{ transport: false, schools: false, amenities: false, ...layers }} />
  );
}

/** Ruler for one metric: this area against its local authority and nation. */
function keyRuler(d: TopicData, id: string, fmt: Fmt, caption: string, refLine?: { x: number; label: string }, cap?: number) {
  const { r } = d.h;
  const here = val(r.metrics, id), lad = val(r.ladMetrics, id), nat = val(r.nationMetrics, id);
  if (here == null || (lad == null && nat == null)) return undefined;
  const marks: Mark[] = [{ k: "here", x: here, label: d.name, sub: fmt(here) }];
  if (lad != null && r.ctx.lad && r.ctx.lad.id !== r.ctx.dataArea.id) marks.push({ k: "lad", x: lad, label: r.ctx.lad.name, sub: fmt(lad) });
  if (nat != null && r.ctx.nation) marks.push({ k: "nat", x: nat, label: r.ctx.nation.name, sub: fmt(nat) });
  if (marks.length < 2) return undefined;
  const nearby = (d.neighbours ?? []).filter((n) => n.v != null && n.code !== r.ctx.dataArea.code).map((n) => n.v!);
  return <Ruler marks={marks} nearby={nearby} fmt={fmt} caption={caption} refLine={refLine} cap={cap ?? (fmt === pct0 ? 100 : undefined)} />;
}

function keyVerdict(d: TopicData, id: string, words: [string, string], dir: -1 | 0 | 1) {
  const { r } = d.h;
  const here = val(r.metrics, id);
  if (here == null) return "";
  return verdictFor({
    here, lad: val(r.ladMetrics, id), nat: val(r.nationMetrics, id),
    ladName: r.ctx.lad && r.ctx.lad.id !== r.ctx.dataArea.id ? r.ctx.lad.name : null, natName: r.ctx.nation?.name ?? "England",
    words, p: mv(r.metrics, id)?.p ?? null, dir,
  });
}

function nextDoor(d: TopicData, fmt: Fmt, dir: -1 | 0 | 1, caption: string) {
  return <NextDoor items={d.neighbours ?? []} own={d.h.r.ctx.dataArea.code} fmt={fmt} dir={dir} caption={caption} />;
}

const money = (d: TopicData) => (v: number) => fmtMoney(v, "GBP", d.h.intl);
const moneyShort = (v: number) => (v >= 1e6 ? `£${(v / 1e6).toFixed(1)}m` : v >= 1e4 ? `£${Math.round(v / 1e3)}k` : `£${Math.round(v).toLocaleString("en-GB")}`);
const pct0 = (v: number) => `${Math.round(v)}%`;
/** Fewer crimes than this in a row and its rate swings with a single incident. */
const FEW = 5;

/** What an area is ranked against nationally, by the level its figures come from. */
const PEERS: Record<string, string> = {
  lsoa: "neighbourhoods", msoa: "neighbourhood groups (MSOAs)", sector: "postcode sectors", district: "postcode districts",
  postal_area: "postcode areas", town: "towns", lad: "local authorities", region: "regions",
};
const lad = (d: TopicData) => (d.h.r.ctx.lad && d.h.r.ctx.lad.id !== d.h.r.ctx.dataArea.id ? d.h.r.ctx.lad.name : null);
const j = (map: H["r"]["metrics"], id: string) => mv(map, id)?.j;

/* ------------------------------------------------------------ crime */

function crime(d: TopicData): TopicView | null {
  const { r, intl } = d.h;
  const m = d.crime ? crimeModel(r, d.crime) : null;
  if (!m) return null;
  const n1 = (x: number) => fmtNumber(x, intl, 1);
  const n0 = (x: number) => fmtNumber(Math.round(x), intl);
  const b = mapBase(d);
  const peers = PEERS[r.ctx.dataArea.level] ?? "areas like it";
  const near = d.crime?.near ? (() => {
    const e = Object.entries(d.crime!.near!.counts);
    const crimes = e.filter(([t]) => t !== "Anti-social behaviour");
    return {
      radius: d.crime!.near!.radius, crimes: crimes.reduce((s, [, n]) => s + n, 0), asb: d.crime!.near!.counts["Anti-social behaviour"] ?? 0,
      top: crimes.sort((a, b) => b[1] - a[1]).slice(0, 3),
    };
  })() : null;
  const rank = (p: number | null, ladP: number | null) => p == null ? undefined : (
    <>
      <b className="tp-rk" style={{ background: rampOf(p)![1], color: p >= 95 || p < 20 ? "#fff" : undefined }}>{decileOf(p)}/10</b>
      {m.lad && ladP != null && <span className="tp-rk-sub">{m.lad} {decileOf(ladP)}/10</span>}
    </>
  );
  return {
    title: `Crime in ${d.name}`,
    description: `Crime in ${d.name}: ${n1(m.rate)} crimes per 1,000 residents in the last 12 months, all 14 police crime types compared with ${m.lad ?? "the local authority"}, the three-year trend and the streets where crimes were recorded.`,
    verdict: keyVerdict(d, "uk.crime.total_rate", ["Busier", "Quieter"], -1),
    dek: <>{n0(m.total)} crimes recorded in the neighbourhood around {r.head.level === "postcode_unit" ? "this postcode" : d.name} from {monthLabel(m.first)} to {monthLabel(m.last)}. Anti-social behaviour, {n0(m.asb)} incidents, is counted separately.</>,
    map: <CrimeMap {...b} rings={b.rings} />,
    ruler: keyRuler(d, "uk.crime.total_rate", (x) => fmtNumber(x, intl, 0), "Crimes per 1,000 residents a year"),
    main: (
      <>
        <Block id="types" title="What gets reported" note={<>Crimes recorded over the last 12 months, by type. Rates are crimes per 1,000 residents, so a small neighbourhood and a whole borough compare fairly; further right means more crime. Red: clearly above {m.lad ?? "the borough"}; green: clearly below. &ldquo;Crimes&rdquo; is the actual number recorded here; faded rows have fewer than {FEW}, so one crime more or less moves the rate a lot.{m.rows.some((x) => x.p != null) && <> &ldquo;Nationally&rdquo; ranks the rate against all {peers} in England and Wales: 1/10 is the tenth with the least of that crime, 10/10 the tenth with the most.{m.lad ? ` The line under it ranks ${m.lad} among all local authorities.` : ""}</>}</>}>
          <DotRows rows={m.rows.map((x) => ({ k: x.k, label: x.label, here: x.rate, other: x.ladRate, extra: n0(x.n), rank: rank(x.p, x.ladP), faint: x.n < FEW }))} fmt={n1} highIs="bad"
            head={{ unit: "Per 1,000 residents", here: "This area", other: m.lad ?? "Borough", extra: "Crimes", rank: "Nationally" }} />
          {near && (
            <p className="tp-near-c">
              Within {fmtDistance(near.radius, intl)} of this postcode: <b>{n0(near.crimes)}</b> crimes and <b>{n0(near.asb)}</b> anti-social behaviour incidents in the same 12 months
              {near.top.length > 0 && <>, most often {near.top.map(([t, n], i) => <span key={t}>{i ? ", " : ""}{t.toLowerCase()} ({n0(n)})</span>)}</>}.
              {" "}A count, not a rate: a circle has no exact resident figure. The map shows where.
            </p>
          )}
        </Block>
        <Block id="nat" title="Against every neighbourhood in England and Wales" note="Each group compared with the local authority and the country.">
          <div className="metrics">
            <M h={d.h} id="uk.crime.violent_rate" name="Violence, robbery and weapons" />
            <M h={d.h} id="uk.crime.burglary_rate" name="Burglary" />
            <M h={d.h} id="uk.crime.vehicle_rate" name="Vehicle crime" />
            <M h={d.h} id="uk.crime.theft_rate" name="Theft" />
            <M h={d.h} id="uk.crime.damage_rate" name="Criminal damage and arson" />
            <M h={d.h} id="uk.crime.asb_rate" name="Anti-social behaviour" />
          </div>
        </Block>
        {(val(r.metrics, "uk.road.collisions_per_1k") != null || val(r.ladMetrics, "uk.flytip.per_1k") != null) && (
          <Block id="roads" title="Roads and street care">
            <div className="metrics">
              <M h={d.h} id="uk.road.collisions_per_1k" />
              <M h={d.h} id="uk.road.ksi_per_1k" />
              {r.ctx.lad && <M h={d.h} id="uk.flytip.per_1k" map={r.ladMetrics} note={`Whole of ${r.ctx.lad.name}, latest year`} />}
            </div>
          </Block>
        )}
      </>
    ),
    side: (
      <>
        <Block id="trend" title="Year on year" note={<>{m.change != null ? `${Math.abs(m.change) < 1 ? "Flat" : m.change > 0 ? `Up ${n0(m.change)}%` : `Down ${n0(-m.change)}%`} on the previous 12 months. ` : ""}Rolling three-month rate per 1,000 a year, anti-social behaviour excluded.</>}>
          <LineChart series={m.trend.map((s, i) => ({ ...s, dashed: i > 0 }))} format={(x) => n0(x)} ariaLabel="Crime rate by quarter" height={200} />
        </Block>
        {m.places.length > 0 && (
          <Block id="streets" title="Streets with most reports" note="Number of crimes pinned to each street in the last 12 months. Police pin each crime to the nearest street point, never an address.">
            <ul className="tp-list">{m.places.slice(0, 8).map((p) => <li key={p.name}><span>{p.name}</span><b>{p.n}<em> {p.n === 1 ? "crime" : "crimes"}</em></b></li>)}</ul>
          </Block>
        )}
        {m.outcomes.length > 0 && (
          <Block id="after" title="After a report" note="Latest recorded outcome, crimes in the last 12 months.">
            <div className="tp-stack" aria-hidden="true">{m.outcomes.slice(0, 5).map((o, i) => <span key={o.name} style={{ width: `${o.share}%`, opacity: 1 - i * 0.17 }} />)}</div>
            <ul className="tp-outcomes">{m.outcomes.slice(0, 5).map((o) => <li key={o.name}><b>{n0(o.share)}%</b> of crimes: {o.name.toLowerCase()}</li>)}</ul>
          </Block>
        )}
      </>
    ),
    after: nextDoor(d, (x) => fmtNumber(x, intl, 0), -1, "Crimes per 1,000 residents."),
    source: `Source: data.police.uk street-level crime, ${monthLabel(m.first)} to ${monthLabel(m.last)}. Rates use Census 2021 residents; areas larger than one neighbourhood weight each neighbourhood by the share of its residents living in the area.`,
  };
}

/* ------------------------------------------------------------ prices */

function prices(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const mny = money(d);
  const types = (["flat", "terraced", "semi", "detached"] as const)
    .map((k) => ({ k, label: { flat: "Flats", terraced: "Terraced", semi: "Semi-detached", detached: "Detached" }[k], here: val(r.metrics, `uk.price.median_${k}`), other: val(r.ladMetrics, `uk.price.median_${k}`) }))
    .filter((x) => x.here != null) as { k: string; label: string; here: number; other: number | null }[];
  const byYear = Object.entries((j(r.metrics, "uk.price.median_by_year") ?? {}) as Record<string, { median: number; n: number }>).filter(([, v]) => v?.n).sort(([a], [b]) => b.localeCompare(a));
  const median = val(r.metrics, "uk.price.median");
  return {
    title: `House prices in ${d.name}`,
    description: `House prices in ${d.name}: median sale price${median ? ` ${mny(median)}` : ""}, prices by property type, the price trend, recent sales and how ${d.name} compares with ${lad(d) ?? "the local authority"}.`,
    verdict: keyVerdict(d, "uk.price.median", ["Dearer", "Cheaper"], 0),
    dek: median ? <>Median sale price {mny(median)} from {fmtNumber(val(r.metrics, "uk.price.sales") ?? 0, intl)} sales over the last 24 months{val(r.metrics, "uk.price.change_5y_pct") != null ? `, ${fmtPct(val(r.metrics, "uk.price.change_5y_pct")!, intl, 0)} on five years ago` : ""}.</> : undefined,
    map: metricMap(d, [
      { id: "uk.price.median", label: "Median sale price", fmt: "money", dir: 0 },
      { id: "uk.price.per_sqm", label: "Price per square metre", fmt: "money", dir: 0 },
      { id: "uk.price.change_5y_pct", label: "Change over five years", fmt: "pct", dir: 0 },
    ]),
    ruler: keyRuler(d, "uk.price.median", moneyShort, "Median sale price, last 24 months"),
    main: (
      <>
        {types.length > 0 && (
          <Block id="types" title="By property type" note={<>Median (middle) sale price of each type of home over the last 24 months, here and in {lad(d) ?? "the local authority"}.</>}>
            <DotRows rows={types} fmt={moneyShort} head={{ unit: "Median sale price", here: "This area", other: lad(d) ?? "Local authority" }} />
          </Block>
        )}
        {flat(<S.Prices h={d.h} />)}
      </>
    ),
    side: (
      <>
        <Facts items={[
          { k: "Price per square metre", v: val(r.metrics, "uk.price.per_sqm") != null ? mny(val(r.metrics, "uk.price.per_sqm")!) : null },
          { k: "Typical floor area", v: val(r.metrics, "uk.price.floor_area") != null ? `${fmtNumber(val(r.metrics, "uk.price.floor_area")!, intl)} m²` : null },
          { k: "Sales in 24 months", v: val(r.metrics, "uk.price.sales") != null ? fmtNumber(val(r.metrics, "uk.price.sales")!, intl) : null },
          { k: `${lad(d) ?? "Local"} prices, last 12 months`, v: val(r.ladMetrics, "uk.hpi.change_12m") != null ? fmtPct(val(r.ladMetrics, "uk.hpi.change_12m")!, intl, 1) : null, note: "UK House Price Index" },
          { k: "Price to earnings", v: val(r.ladMetrics, "uk.afford.median_ratio") != null ? `${fmtNumber(val(r.ladMetrics, "uk.afford.median_ratio")!, intl, 1)} × earnings` : null, note: `Median home against median pay in ${r.ctx.lad?.name ?? "the area"}` },
        ]} />
        {(d.hpi?.length ?? 0) > 12 && r.ctx.lad && (
          <Block id="hpi" title={`${r.ctx.lad.name}, ten years`} note="UK House Price Index average price, all property types.">
            <LineChart series={[{ label: r.ctx.lad.name, points: d.hpi!.map((p) => ({ x: p.period, y: p.v })) }]} format={moneyShort} ariaLabel={`Average price in ${r.ctx.lad.name} over ten years`} height={190} />
          </Block>
        )}
        {byYear.length > 1 && (
          <Block id="years" title="Year by year" note="Median price and number of standard sales.">
            <ul className="tp-list">{byYear.slice(0, 8).map(([y, v]) => <li key={y}><span>{y}</span><b>{moneyShort(v.median)}<em> median</em></b><em>{v.n} sales</em></li>)}</ul>
          </Block>
        )}
      </>
    ),
    after: nextDoor(d, moneyShort, 0, "Median sale price."),
    source: "Sources: HM Land Registry Price Paid Data (standard sales), UK House Price Index, ONS house price to earnings ratios.",
  };
}

/* ------------------------------------------------------------ rent */

function rent(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const L = r.ladMetrics;
  const mny = money(d);
  const rentV = val(L, "uk.pipr.rental_price");
  const change = val(L, "uk.pipr.annual_change");
  const rows = (pairs: [string, string][]) => pairs.map(([label, k]) => ({ label, v: val(L, `uk.pipr.rental_price_${k}`), c: val(L, `uk.pipr.annual_change_${k}`) })).filter((x) => x.v != null);
  const beds = rows([["One bedroom", "one_bed"], ["Two bedrooms", "two_bed"], ["Three bedrooms", "three_bed"], ["Four or more", "four_or_more_bed"]]);
  const kinds = rows([["Flat or maisonette", "flat_maisonette"], ["Terraced", "terraced"], ["Semi-detached", "semidetached"], ["Detached", "detached"]]);
  const table = (title: string, id: string, rs: typeof beds) => rs.length > 0 && (
    <Block id={id} title={title} note={`Average monthly rent in ${r.ctx.lad?.name ?? "the local authority"} and the change on a year ago.`}>
      <table className="data"><thead><tr><th></th><th className="r">Monthly rent</th><th className="r">Year on year</th></tr></thead>
        <tbody>{rs.map((x) => <tr key={x.label}><td>{x.label}</td><td className="r num">{mny(x.v!)}</td><td className="r num">{x.c != null ? `${x.c > 0 ? "+" : ""}${fmtNumber(x.c, intl, 1)}%` : "–"}</td></tr>)}</tbody>
      </table>
    </Block>
  );
  const tenure = compareShares(j(r.metrics, "uk.census21.ts054"), j(r.ladMetrics, "uk.census21.ts054"), { exclude: /lives rent free/i });
  return {
    title: `Renting in ${d.name}`,
    description: `Renting in ${d.name}: average rents in ${r.ctx.lad?.name ?? "the local authority"} by bedrooms and property type, the yearly change and how many households rent.`,
    verdict: rentV && r.ctx.lad ? `Average rent in ${r.ctx.lad.name} is ${mny(rentV)} a month${change != null ? `, ${change >= 0 ? "up" : "down"} ${fmtNumber(Math.abs(change), intl, 1)}% on a year ago` : ""}` : "",
    dek: "Official rents are published for each local authority, not for single streets, so the figures below describe the wider area.",
    map: areaMap(d, { transport: true }),
    main: <>{table("By bedrooms", "beds", beds)}{table("By property type", "kinds", kinds)}{flat(<S.Rent h={d.h} />)}</>,
    side: tenure.length > 0 ? (
      <Block id="tenure" title="Who rents here" note={`Share of households that own, rent privately or rent socially, here and in ${lad(d) ?? "the local authority"}. Census 2021.`}>
        <ShareRows rows={tenure} other={lad(d) ?? "Local authority"} unit="% of households" />
      </Block>
    ) : undefined,
    source: "Sources: ONS Price Index of Private Rents; Census 2021 (tenure).",
  };
}

/* ------------------------------------------------------------ flood and ground risk */

function risk(d: TopicData): TopicView {
  const { r } = d.h;
  const z = r.riskPoint?.zones ?? {};
  const wales = r.ctx.nation?.code?.startsWith("W");
  const z3 = z[wales ? "flood.wales_zone3" : "flood.zone3"] !== undefined, z2 = z3 || z[wales ? "flood.wales_zone2" : "flood.zone2"] !== undefined;
  const share = val(r.metrics, "uk.zone.flood_zone2plus_share");
  const verdict = r.riskPoint
    ? z3 ? "In Flood Zone 3, the highest risk of flooding from rivers or the sea" : z2 ? "In Flood Zone 2, a medium risk of flooding from rivers or the sea" : "Outside the river and sea flood zones"
    : share != null ? (share === 0 ? "No homes here sit in a river or sea flood zone" : `${fmtNumber(share, d.h.intl, share < 1 ? 1 : 0)}% of residents live in a river or sea flood zone`) : "";
  return {
    title: `Flood and ground risk in ${d.name}`,
    description: `Flood and ground risk in ${d.name}: river, sea and surface water flooding, flood history, radon, subsidence, mining, landfill and coastal erosion checks.`,
    verdict,
    dek: "Each check below says what was found and what to ask the seller or your surveyor when it is not clear.",
    map: areaMap(d, { flood: true }),
    main: flat(<S.Risk h={d.h} />),
    side: <Facts items={[
      { k: "Residents in flood zone 2 or 3", v: share != null ? `${fmtNumber(share, d.h.intl, share < 1 ? 1 : 0)}%` : null },
      { k: "Residents in flood zone 3", v: val(r.metrics, "uk.zone.flood_zone3_share") != null ? `${fmtNumber(val(r.metrics, "uk.zone.flood_zone3_share")!, d.h.intl, 0)}%` : null },
      { k: "Area flooded before", v: val(r.metrics, "uk.zone.flood_historic_share") != null ? `${fmtNumber(val(r.metrics, "uk.zone.flood_historic_share")!, d.h.intl, 0)}%` : null, note: "Share of residents in recorded historic flood outlines" },
    ]} />,
    source: "Sources: Environment Agency and Natural Resources Wales flood maps, British Geological Survey, UKHSA radon, Coal Authority.",
  };
}

/* ------------------------------------------------------------ schools */

function schools(d: TopicData): TopicView {
  const { r, intl, t } = d.h;
  const list = d.schools ?? [];
  const phase = (x: string) => ({ "school.primary": "Primary", "school.secondary": "Secondary", "school.all_through": "All-through", "school.special": "Special", "school.post16": "16 plus" })[x] ?? x;
  const ofsted = (x: SchoolRow["rating"]) => !x ? <span className="m-src">Not rated</span> : <span className={`ofsted r${x.rank ?? 0}`}>{x.label}</span>;
  const good = list.filter((s) => s.rating?.rank != null && s.rating.rank <= 2).length;
  return {
    title: `Schools near ${d.name}`,
    description: `Schools near ${d.name}: ${list.length} schools within 3 km with Ofsted grades, results, first-choice offer rates, pupil numbers and free school meals.`,
    verdict: keyVerdict(d, "uk.schools.primary_quality", ["Stronger primary results", "Weaker primary results"], 1) || `${list.length} schools within 3 km`,
    dek: list.length ? <>{list.length} schools within 3 km; {good} rated Good or Outstanding by Ofsted. Distances are straight lines; catchments depend on each school&apos;s admissions rules.</> : undefined,
    map: areaMap(d, { schools: true }),
    ruler: keyRuler(d, "uk.schools.primary_quality", pct0, "Nearby primaries: share of pupils meeting the expected standard at age 11"),
    main: (
      <>
        {list.length > 0 && (
          <Block id="list" title="Every school within 3 km" note="Results: KS2 share meeting the expected standard (primary), Attainment 8 and Progress 8 (secondary). Offers: share of first-choice applicants offered a place.">
            <div className="scroll-x">
              <table className="data tp-schools">
                <thead><tr><th>School</th><th>Ofsted</th><th className="r">Results</th><th className="r">Offers</th><th className="r">Pupils</th><th className="r">FSM</th><th className="r">Distance</th></tr></thead>
                <tbody>
                  {list.map((s) => (
                    <tr key={s.id}>
                      <td>
                        {s.slug ? <Link href={`/uk/school/${s.slug}`}>{s.name}</Link> : s.name}
                        <span className="m-src">{[phase(s.type), s.ages ? `ages ${s.ages}` : null, s.kind, s.gender && s.gender !== "Mixed" ? s.gender : null, s.religion, s.admissions === "Selective" ? "Selective" : null].filter(Boolean).join(", ")}</span>
                      </td>
                      <td>{ofsted(s.rating)}</td>
                      <td className="r num">{s.ks2 != null ? `${fmtNumber(s.ks2, intl)}%` : s.a8 != null ? <>A8 {fmtNumber(s.a8, intl, 1)}{s.p8 != null ? <span className="m-src">P8 {s.p8 > 0 ? "+" : ""}{fmtNumber(s.p8, intl, 2)}</span> : null}</> : "–"}</td>
                      <td className="r num">{s.offerRate != null ? `${fmtNumber(s.offerRate, intl)}%` : "–"}</td>
                      <td className="r num">{s.pupils != null ? fmtNumber(s.pupils, intl) : "–"}{s.capacity ? <span className="m-src">of {fmtNumber(s.capacity, intl)}</span> : null}</td>
                      <td className="r num">{s.fsm != null ? `${fmtNumber(s.fsm, intl)}%` : "–"}</td>
                      <td className="r num">{fmtDistance(s.dist, intl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>
        )}
        {r.nurseries.length > 0 && (
          <Block id="nurseries" title={t.report.schools.nurseries} note={t.report.schools.nurseryNote}>
            <ul className="tp-list">{r.nurseries.map((n) => <li key={n.id}><span>{n.name}{n.rating ? <span className="m-src"> {n.rating.label}</span> : null}</span><b>{fmtDistance(n.dist, intl)}</b></li>)}</ul>
          </Block>
        )}
      </>
    ),
    side: (
      <>
        <Facts items={[
          { k: "Nearest primary", v: val(r.metrics, "uk.access.primary_dist_m") != null ? fmtDistance(val(r.metrics, "uk.access.primary_dist_m")!, intl) : null },
          { k: "Nearest secondary", v: val(r.metrics, "uk.access.secondary_dist_m") != null ? fmtDistance(val(r.metrics, "uk.access.secondary_dist_m")!, intl) : null },
          { k: "Good or Outstanding within 3 km", v: list.length ? `${good} of ${list.length}` : null },
        ]} />
        <div className="metrics tp-one">
          <M h={d.h} id="uk.schools.primary_quality" name="Nearby primaries, % meeting KS2 standard" />
          <M h={d.h} id="uk.schools.secondary_quality" name="Nearby secondaries, Attainment 8" />
        </div>
      </>
    ),
    after: nextDoor(d, pct0, 1, "Nearby primaries: share meeting the KS2 standard."),
    source: "Sources: DfE Get Information about Schools, Ofsted, DfE school performance tables and secondary and primary admissions statistics.",
  };
}

/* ------------------------------------------------------------ transport */

function transport(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const first = r.stations[0];
  const modes = ([["Public transport", "public_transport"], ["Walking", "walking"], ["Cycling", "cycling"], ["Driving", "driving"]] as const)
    .map(([label, k]) => ({ k, label, here: val(r.metrics, `uk.tcm.${k}_overall`), other: val(r.ladMetrics, `uk.tcm.${k}_overall`) }))
    .filter((x) => x.here != null) as { k: string; label: string; here: number; other: number | null }[];
  const dist = compareShares(j(r.metrics, "uk.census21.ts058"), j(r.ladMetrics, "uk.census21.ts058"), { exclude: /not in employment|works mainly|no fixed|offshore|outside/i });
  const cars = compareShares(j(r.metrics, "uk.census21.ts045"), j(r.ladMetrics, "uk.census21.ts045"));
  const fmtD = (x: number) => (x >= 1000 ? `${fmtNumber(x / 1000, intl, 1)} km` : `${Math.round(x / 10) * 10} m`);
  return {
    title: `Transport in ${d.name}`,
    description: `Transport in ${d.name}: nearest stations with walking times, how well connected the area is by public transport, walking, cycling and car, and how people get to work.`,
    verdict: first ? `${first.name.replace(/ (Rail|Underground) Station$/, "")} is ${walkMinutes(first.dist)} minutes' walk away` : keyVerdict(d, "uk.access.rail_dist_m", ["Further from a station", "Closer to a station"], -1),
    dek: first && keyVerdict(d, "uk.access.rail_dist_m", ["Further from a station", "Closer to a station"], -1) ? <>{keyVerdict(d, "uk.access.rail_dist_m", ["Further from a station", "Closer to a station"], -1)}.</> : undefined,
    map: areaMap(d, { transport: true }),
    ruler: keyRuler(d, "uk.access.rail_dist_m", fmtD, "Distance to the nearest rail, Underground or tram station"),
    main: (
      <>
        {modes.length > 0 && (
          <Block id="modes" title="How well connected" note={<>Department for Transport connectivity score from 0 (poorly connected) to 100 (best connected in Great Britain), by how you travel. Green: clearly better than {lad(d) ?? "the local authority"}; red: clearly worse.</>}>
            <DotRows rows={modes} fmt={(x) => fmtNumber(x, intl, 0)} highIs="good" head={{ unit: "Score out of 100", here: "This area", other: lad(d) ?? "Local authority" }} />
          </Block>
        )}
        {flat(<S.Transport h={d.h} />)}
      </>
    ),
    side: (
      <>
        <Facts items={[
          { k: "Bus stops within 500 m", v: val(r.metrics, "uk.access.bus_stops_500m") != null ? `${fmtNumber(val(r.metrics, "uk.access.bus_stops_500m")!, intl)} stops` : null },
          { k: "Nearest station", v: first ? fmtDistance(first.dist, intl) : null, note: first?.name },
          { k: "Travel zone", v: first?.attrs.tfl_zone ?? null },
        ]} />
        {dist.length > 0 && <Block id="dist" title="Distance to work" note="How far working residents travel to their workplace. Census 2021."><ShareRows rows={dist} other={lad(d) ?? "Local authority"} unit="% of workers" /></Block>}
        {cars.length > 0 && <Block id="cars" title="Cars or vans per household" note="Census 2021."><ShareRows rows={cars} other={lad(d) ?? "Local authority"} unit="% of households" /></Block>}
      </>
    ),
    after: nextDoor(d, fmtD, -1, "Distance to the nearest station."),
    source: "Sources: NaPTAN and ORR station usage, DfT Transport Connectivity Metric, TfL PTAL (London), Census 2021.",
  };
}

/* ------------------------------------------------------------ amenities */

function amenities(d: TopicData): TopicView {
  const { intl } = d.h;
  const a = d.amenities ?? { kinds: [], gps: [] };
  const fmtD = (x: number) => fmtDistance(x, intl);
  const pc = (x: number | undefined) => (x == null ? "–" : `${Math.round(x)}%`);
  return {
    title: `Amenities near ${d.name}`,
    description: `Amenities near ${d.name}: shops, supermarkets, restaurants, pubs, GPs with patient survey results, pharmacies, dentists, gyms and libraries within 1 km.`,
    verdict: keyVerdict(d, "uk.access.gp_dist_m", ["Further from a GP", "Closer to a GP"], -1),
    dek: a.kinds.length ? <>{a.kinds.reduce((s, k) => s + k.n, 0)} shops, places to eat and services within 1 km.</> : undefined,
    map: areaMap(d, { amenities: true, green: true }),
    ruler: keyRuler(d, "uk.access.gp_dist_m", fmtD, "Distance to the nearest GP practice"),
    main: (
      <>
        {a.kinds.length > 0 && (
          <Block id="within" title="Within 1 km" note="Straight-line distance from the postcode centre.">
            <div className="tp-kinds">
              {a.kinds.filter((k) => k.n > 0).map((k) => (
                <div key={k.label}>
                  <b>{k.n}</b><span>{k.label}</span>
                  <ul>{k.nearest.map((n) => <li key={n.name + n.dist}>{n.name} <em>{fmtD(n.dist)}</em></li>)}</ul>
                </div>
              ))}
            </div>
          </Block>
        )}
        {a.gps.length > 0 && (
          <Block id="gps" title="GP practices" note="NHS GP Patient Survey: share of patients answering good or easy. CQC: latest inspection rating.">
            <div className="scroll-x">
              <table className="data">
                <thead><tr><th>Practice</th><th className="r">Overall good</th><th className="r">Easy by phone</th><th className="r">Needs met</th><th className="r">Patients</th><th className="r">Distance</th></tr></thead>
                <tbody>
                  {a.gps.map((g) => (
                    <tr key={g.name}>
                      <td>{g.name}<span className="m-src">{[g.rating ? `CQC ${g.rating}` : null, g.phone].filter(Boolean).join(", ")}</span></td>
                      <td className="r num">{pc(g.survey["uk.gp.overall_good"])}</td>
                      <td className="r num">{pc(g.survey["uk.gp.phone_easy"])}</td>
                      <td className="r num">{pc(g.survey["uk.gp.needs_met"])}</td>
                      <td className="r num">{g.patients != null ? fmtNumber(g.patients, intl) : "–"}</td>
                      <td className="r num">{fmtD(g.dist)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>
        )}
      </>
    ),
    side: flat(<S.Amenities h={d.h} />),
    after: nextDoor(d, fmtD, -1, "Distance to the nearest GP."),
    source: "Sources: NHS ODS, NHS GP Patient Survey, CQC, OpenStreetMap, Geolytix retail points, Food Standards Agency.",
  };
}

/* ------------------------------------------------------------ environment */

const POLLUTANTS: [string, string, number, number, string][] = [
  ["uk.pcm.no2", "Nitrogen dioxide (NO₂)", 10, 40, "Mostly from road traffic. Raises asthma attacks, especially in children and older people with heart disease."],
  ["uk.pcm.pm25", "Fine particles (PM2.5)", 5, 20, "From traffic, wood burning and industry. Small enough to reach the bloodstream; linked to heart and lung disease."],
  ["uk.pcm.pm10", "Particles (PM10)", 15, 40, "Dust, brake and tyre wear, construction. Irritates airways and worsens bronchitis and asthma."],
];

function environment(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const ug = (x: number) => fmtNumber(x, intl, 1);
  return {
    title: `Air, noise and climate in ${d.name}`,
    description: `Air quality, noise and climate in ${d.name}: nitrogen dioxide and particle levels against WHO guidelines, road and rail noise, storm overflows and local weather.`,
    verdict: keyVerdict(d, "uk.pcm.no2", ["More polluted air", "Cleaner air"], -1),
    dek: "Annual mean concentrations, modelled for every 1 km square and averaged over the neighbourhood.",
    map: metricMap(d, [
      { id: "uk.pcm.no2", label: "Nitrogen dioxide", fmt: "ugm3", dir: -1, unit: "µg/m³" },
      { id: "uk.pcm.pm25", label: "Fine particles PM2.5", fmt: "ugm3", dir: -1, unit: "µg/m³" },
      { id: "uk.pcm.pm10", label: "Particles PM10", fmt: "ugm3", dir: -1, unit: "µg/m³" },
    ]),
    ruler: keyRuler(d, "uk.pcm.no2", ug, "Nitrogen dioxide, annual mean in µg/m³", { x: 10, label: "WHO guideline" }),
    main: (
      <>
        <Block id="pollutants" title="What the air contains" note="WHO guideline (2021) and the UK legal limit, annual means in µg/m³.">
          <div className="scroll-x">
            <table className="data">
              <thead><tr><th>Pollutant</th><th className="r">Here</th><th className="r">WHO</th><th className="r">UK limit</th></tr></thead>
              <tbody>{POLLUTANTS.map(([id, label, who, uk, note]) => {
                const v = val(r.metrics, id);
                return v == null ? null : (
                  <tr key={id}><td>{label}<span className="m-src">{note}</span></td><td className={`r num ${v > who ? "tp-over" : "tp-under"}`}>{ug(v)}</td><td className="r num">{who}</td><td className="r num">{uk}</td></tr>
                );
              })}</tbody>
            </table>
          </div>
        </Block>
        {flat(<S.Environment h={d.h} />)}
      </>
    ),
    side: <Facts items={[
      { k: "Average temperature", v: val(r.metrics, "uk.climate.tas") != null ? `${fmtNumber(val(r.metrics, "uk.climate.tas")!, intl, 1)} °C` : null },
      { k: "Rainfall a year", v: val(r.metrics, "uk.climate.rainfall") != null ? `${fmtNumber(val(r.metrics, "uk.climate.rainfall")!, intl)} mm` : null },
      { k: "Days over 25 °C", v: val(r.metrics, "uk.climate.summer_days") != null ? `${fmtNumber(val(r.metrics, "uk.climate.summer_days")!, intl)} days a year` : null },
      { k: "Days with air frost", v: val(r.metrics, "uk.climate.airfrost_days") != null ? `${fmtNumber(val(r.metrics, "uk.climate.airfrost_days")!, intl)} days a year` : null },
      { k: "Days with 10 mm rain", v: val(r.metrics, "uk.climate.rain10mm_days") != null ? `${fmtNumber(val(r.metrics, "uk.climate.rain10mm_days")!, intl)} days a year` : null },
    ]} />,
    after: nextDoor(d, ug, -1, "Nitrogen dioxide, µg/m³."),
    source: "Sources: Defra Pollution Climate Mapping, Defra strategic noise maps, Local Authority AQMAs, water company storm overflow returns, Met Office HadUK-Grid.",
  };
}

/* ------------------------------------------------------------ broadband */

function broadband(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const rows = ([["Gigabit (1,000 Mbit/s)", "gigabit_pct"], ["Ultrafast (300 Mbit/s)", "ufbb_pct"], ["Superfast (30 Mbit/s)", "sfbb_pct"], ["No decent broadband", "no_decent_pct"]] as const)
    .map(([label, k]) => ({ k, label, here: val(r.metrics, `uk.bb.${k}`), other: val(r.ladMetrics, `uk.bb.${k}`) })).filter((x) => x.here != null) as { k: string; label: string; here: number; other: number | null }[];
  return {
    title: `Broadband and mobile in ${d.name}`,
    description: `Broadband and mobile coverage in ${d.name}: gigabit, ultrafast and superfast availability and 4G and 5G coverage, compared with ${lad(d) ?? "the local authority"}.`,
    verdict: keyVerdict(d, "uk.bb.gigabit_pct", ["Better connected", "Less connected"], 1),
    dek: val(r.metrics, "uk.bb.gigabit_pct") != null ? <>{fmtNumber(val(r.metrics, "uk.bb.gigabit_pct")!, intl)}% of premises can get gigabit broadband.</> : undefined,
    map: metricMap(d, [
      { id: "uk.bb.gigabit_pct", label: "Gigabit available", fmt: "pct", dir: 1 },
      { id: "uk.bb.ufbb_pct", label: "Ultrafast available", fmt: "pct", dir: 1 },
      { id: "uk.bb.no_decent_pct", label: "No decent broadband", fmt: "pct", dir: -1 },
    ]),
    ruler: keyRuler(d, "uk.bb.gigabit_pct", pct0, "Premises able to get gigabit broadband"),
    main: (
      <>
        {rows.length > 0 && <Block id="speeds" title="Speeds available" note={<>Share of homes and businesses that can order each speed, here and in {lad(d) ?? "the local authority"}.</>}><DotRows rows={rows} fmt={pct0} head={{ unit: "% of premises", here: "This area", other: lad(d) ?? "Local authority" }} /></Block>}
        {flat(<S.Connectivity h={d.h} />)}
      </>
    ),
    after: nextDoor(d, pct0, 1, "Premises able to get gigabit broadband."),
    source: "Source: Ofcom Connected Nations.",
  };
}

/* ------------------------------------------------------------ people */

const IOD: [string, string][] = [
  ["imd", "Overall"], ["income", "Income"], ["employment", "Employment"], ["education", "Education and skills"], ["health", "Health"],
  ["crime", "Crime"], ["barriers", "Housing and services"], ["living_env", "Living environment"], ["idaci", "Children in low-income homes"], ["idaopi", "Older people in low-income homes"],
];

function people(d: TopicData): TopicView {
  const { r } = d.h;
  const england = r.ctx.nation?.code?.startsWith("E");
  const cmp = (id: string, opts: Parameters<typeof compareShares>[2] = {}) => compareShares(j(r.metrics, id), j(r.ladMetrics, id), opts);
  const work = cmp("uk.census21.ts066", { top: 7 });
  const jobs = cmp("uk.census21.ts063", { rename: (k) => k.replace(/^\d+\.\s*/, "") });
  const homes = cmp("uk.census21.ts003", { top: 7 });
  const health = cmp("uk.census21.ts037");
  const born = cmp("uk.census21.ts004", { top: 6 });
  const ethnic = cmp("uk.census21.ts021", { top: 8 });
  const religion = cmp("uk.census21.ts030", { top: 7 });
  const share = (title: string, id: string, rows: ReturnType<typeof cmp>, note?: string, unit = "% of residents") => rows.length > 0 && (
    <Block id={id} title={title} note={note ?? `Share of residents in each group, here and in ${lad(d) ?? "the local authority"}. Census 2021.`}><ShareRows rows={rows} other={lad(d) ?? "Local authority"} unit={unit} /></Block>
  );
  return {
    title: `People and affluence in ${d.name}`,
    description: `Who lives in ${d.name}: income, deprivation in detail, jobs, households, health and background from Census 2021 and the Indices of Deprivation, compared with ${lad(d) ?? "the local authority"}.`,
    verdict: keyVerdict(d, "uk.income.net", ["Higher household incomes", "Lower household incomes"], 1),
    dek: "Census 2021 and the Indices of Deprivation describe the neighbourhood as a whole, not any one household. None of the background figures feed a score.",
    map: england ? metricMap(d, [
      { id: "uk.iod25.imd_decile", label: "Deprivation decile (10 = least deprived)", fmt: "decile", dir: 1 },
      { id: "uk.iod25.income_decile", label: "Income decile", fmt: "decile", dir: 1 },
      { id: "uk.iod25.education_decile", label: "Education decile", fmt: "decile", dir: 1 },
      { id: "uk.iod25.health_decile", label: "Health decile", fmt: "decile", dir: 1 },
      { id: "uk.iod25.living_env_decile", label: "Living environment decile", fmt: "decile", dir: 1 },
    ]) : areaMap(d, {}),
    ruler: keyRuler(d, "uk.income.net", moneyShort, "Average household income after tax, a year"),
    main: (
      <>
        {england && (
          <Block id="iod" title="Deprivation in detail" note="English Indices of Deprivation 2025. Decile 1 is the most deprived tenth of neighbourhoods in England, 10 the least.">
            <ul className="tp-deciles">
              {IOD.map(([k, label]) => {
                const v = val(r.metrics, `uk.iod25.${k}_decile`);
                if (v == null) return null;
                return (
                  <li key={k}>
                    <span>{label}</span>
                    <span className="tp-dec" role="img" aria-label={`${label}: decile ${Math.round(v)} of 10`}>
                      {Array.from({ length: 10 }, (_, i) => <i key={i} className={i + 1 === Math.round(v) ? "on" : undefined} />)}
                    </span>
                    <b>{Math.round(v)}</b>
                  </li>
                );
              })}
            </ul>
          </Block>
        )}
        {flat(<S.People h={d.h} />)}
        {share("Work", "work", work)}
        {share("Jobs", "jobs", jobs, "Occupation of working residents. Census 2021.", "% of workers")}
        {share("Households", "homes", homes, "Share of households of each kind. Census 2021.", "% of households")}
      </>
    ),
    side: (
      <>
        <Facts items={[
          { k: "Household income after tax", v: val(r.metrics, "uk.income.net") != null ? moneyShort(val(r.metrics, "uk.income.net")!) : null, note: "ONS small area estimate, a year" },
          { k: "After housing costs", v: val(r.metrics, "uk.income.net_ahc") != null ? moneyShort(val(r.metrics, "uk.income.net_ahc")!) : null },
          { k: "Before tax", v: val(r.metrics, "uk.income.total") != null ? moneyShort(val(r.metrics, "uk.income.total")!) : null },
        ]} />
        {share("Health", "health", health, "Self-reported general health. Census 2021.")}
        {share("Country of birth", "born", born)}
        {share("Ethnic group", "ethnic", ethnic)}
        {share("Religion", "religion", religion)}
      </>
    ),
    after: nextDoor(d, (x) => `D${Math.round(x)}`, 1, "Deprivation decile, 10 = least deprived."),
    source: `Sources: Census 2021 (ONS), ${england ? "English Indices of Deprivation 2025" : "Welsh Index of Multiple Deprivation 2025"}, ONS small area income estimates.`,
  };
}

/* ------------------------------------------------------------ energy */

function energy(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const e = r.epc;
  const good = e ? (["A", "B", "C"].reduce((s, k) => s + (e.ratings[k] ?? 0), 0) / e.total) * 100 : null;
  const beds = compareShares(j(r.metrics, "uk.census21.ts050"), j(r.ladMetrics, "uk.census21.ts050"));
  const types = e ? Object.entries(e.types).sort((a, b) => b[1] - a[1]).map(([label, n]) => ({ label, here: (n / e.total) * 100 })) : [];
  return {
    title: `Homes and energy in ${d.name}`,
    description: `Homes in ${d.name}: energy ratings, building age, property types, bedrooms and heating, from the EPC register and Census 2021.`,
    verdict: good != null ? `${fmtNumber(good, intl)}% of homes are rated EPC A to C` : "",
    dek: e ? <>From {fmtNumber(e.total, intl)} energy certificates, the latest for each address.{e.medianFloorArea ? ` Typical floor area ${fmtNumber(e.medianFloorArea, intl)} m².` : ""}</> : undefined,
    map: areaMap(d, {}),
    main: flat(<S.Energy h={d.h} />),
    side: (
      <>
        {types.length > 0 && <Block id="types" title="Certified homes by type" note="Share of homes with an energy certificate, by type. EPC register."><ShareRows rows={types.slice(0, 6)} unit="% of homes" /></Block>}
        {beds.length > 0 && <Block id="beds" title="Bedrooms" note="Share of households by number of bedrooms. Census 2021."><ShareRows rows={beds} other={lad(d) ?? "Local authority"} unit="% of households" /></Block>}
      </>
    ),
    source: "Sources: MHCLG Energy Performance Certificates register, Census 2021.",
  };
}

/* ------------------------------------------------------------ planning */

function planning(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const p = d.planning ?? { listed: [], listedTotal: 0, brownfield: 0 };
  // A postcode is inside a zone only when its centre point is (those rows carry the zone's names);
  // `intersects` on the other rows describes its whole neighbourhood. Larger areas use the share of residents.
  const unit = r.head.level === "postcode_unit";
  const zone = (type: string, metric: string) => {
    const z = r.zones.find((x) => x.type === type && (x.intersects || (x.shareArea ?? 0) > 0));
    const share = val(r.metrics, metric);
    const inside = unit ? !!z?.names : (share ?? 0) >= 99.5;
    return { z, share, in: inside, part: !inside && share != null && share > 0 };
  };
  const ca = zone("planning.conservation_area", "uk.zone.conservation_area_share");
  const a4 = zone("planning.article4", "uk.zone.article4_share");
  const pc = (x: number) => fmtNumber(x, intl, x < 1 ? 1 : 0);
  const verdict = ca.in ? `Inside ${ca.z?.names ? `the ${ca.z.names.split(",")[0]} conservation area` : "a conservation area"}`
    : a4.in ? "Covered by an Article 4 direction"
    : ca.part ? `A conservation area covers ${pc(ca.share!)}% of residents here`
    : a4.part ? `An Article 4 direction covers ${pc(a4.share!)}% of residents here`
    : "No conservation area or Article 4 direction here";
  const limited = ca.in || a4.in || ca.part || a4.part;
  return {
    title: `Planning and conservation in ${d.name}`,
    description: `Planning in ${d.name}: conservation areas, Article 4 directions, green belt, protected landscapes, listed buildings nearby and brownfield land.`,
    verdict,
    dek: limited ? "Extensions, windows, doors and front gardens may need permission. Check the council's map for the exact boundary before you buy if you plan changes." : "Normal permitted development rights apply, subject to the council's rules.",
    map: areaMap(d, { planning: true }),
    main: (
      <>
        {flat(<S.Planning h={d.h} />)}
        {p.listed.length > 0 && (
          <Block id="listed" title="Listed buildings nearby" note={`${p.listedTotal} within 500 m; the nearest are below. Grade I and II* are the most protected.`}>
            <ul className="tp-list">
              {p.listed.map((x) => (
                <li key={x.name + x.dist}>
                  <span>{x.url ? <a href={x.url} rel="noopener">{x.name}</a> : x.name}{x.grade ? <span className="m-src"> Grade {x.grade}</span> : null}</span>
                  <b>{fmtDistance(x.dist, intl)}</b>
                </li>
              ))}
            </ul>
          </Block>
        )}
      </>
    ),
    side: <Facts items={[
      { k: "Listed buildings within 500 m", v: fmtNumber(p.listedTotal, intl) },
      { k: "Brownfield sites within 1 km", v: fmtNumber(p.brownfield, intl), note: "Land the council lists as suitable for housing" },
    ]} />,
    source: "Sources: planning.data.gov.uk, Historic England, Natural England, local brownfield land registers.",
  };
}

/* ------------------------------------------------------------ costs */

function costs(d: TopicData): TopicView {
  const { r, intl } = d.h;
  const bandD = val(r.ladMetrics, "uk.ctax.band_d");
  const stock = compareShares(j(r.metrics, "uk.ctax.stock"), j(r.ladMetrics, "uk.ctax.stock"),
    { order: ["A", "B", "C", "D", "E", "F", "G", "H", "I"], rename: (k) => `Band ${k}` });
  return {
    title: `Running costs in ${d.name}`,
    description: `Running costs in ${d.name}: council tax for every band in ${r.ctx.lad?.name ?? "the local authority"}, the bands of local homes and stamp duty.`,
    verdict: bandD && r.ctx.lad ? `Band D council tax in ${r.ctx.lad.name} is ${fmtMoney(bandD, "GBP", intl)} a year` : "",
    dek: "Council tax is set by the local authority each April. Your band depends on the home's 1991 value (2003 in Wales).",
    map: areaMap(d, {}),
    main: flat(<S.Costs h={d.h} />),
    side: stock.length > 0 ? <Block id="stock" title="Homes by council tax band" note="Share of homes in each band; band A is the cheapest. Valuation Office Agency."><ShareRows rows={stock} other={lad(d) ?? "Local authority"} unit="% of homes" /></Block> : undefined,
    source: "Sources: MHCLG and Welsh Government council tax levels, Valuation Office Agency, HMRC stamp duty rates.",
  };
}

/* ------------------------------------------------------------ registry */

export const TOPICS: Record<string, (d: TopicData) => TopicView | null> = {
  crime, prices, rent, "flood-risk": risk, schools, transport, amenities, environment, broadband, people, energy, planning, costs,
};

