import Link from "next/link";
import type { ReactNode } from "react";
import type { AreaInsights, Classification } from "@/server/insights";
import type { PointExtras } from "@/server/point";
import { mv, val, type H } from "./helpers";
import { uk } from "@/markets/uk";
import { topicHref } from "./nav";
import { decileOf, rampOf } from "./topic/crimeModel";

// "Data says": one line per topic with a score out of 10 against every comparable area in England
// and Wales, plus what the single figure hides (poorer streets next door, deprived pockets in the
// wider area). Each line links to the topic page with the detail.

const CRIME_TYPES: [string, string][] = [
  ["vso", "Violence"], ["robbery", "Robbery"], ["burglary", "Burglary"], ["vehicle", "Vehicle crime"], ["bicycle", "Bicycle theft"],
  ["drugs", "Drugs"], ["theft_person", "Theft from the person"], ["shoplifting", "Shoplifting"], ["asb", "Anti-social behaviour"],
  ["damage", "Criminal damage"], ["public_order", "Public order"], ["weapons", "Weapons"],
];

const pct = (x: number) => `${x < 10 ? x.toFixed(1) : Math.round(x)}%`;

function Badge({ p, bad, of = 10 }: { p: number | null | undefined; bad?: boolean; of?: number }) {
  if (p == null) return null;
  const d = of === 10 ? decileOf(p) : Math.round(p);
  const bg = bad ? rampOf(of === 10 ? p : (d / of) * 100)![1] : `hsl(214 45% ${92 - (of === 10 ? d : (d / of) * 10) * 5.5}%)`;
  const dark = bad ? (of === 10 ? p >= 95 || p < 20 : false) : (of === 10 ? d : (d / of) * 10) >= 7;
  return <b className="tp-rk" style={{ background: bg, color: dark ? "#fff" : undefined }}>{d}/{of}</b>;
}

interface Line { id: string; topic: string; title: string; verdict: ReactNode; badge?: ReactNode; note?: ReactNode; extra?: ReactNode }

export function DataSays({ h, insights, oac, point }: { h: H; insights: AreaInsights | null; oac?: Classification | null; point?: PointExtras | null }) {
  const { r } = h;
  const m = r.metrics;
  const region = r.ctx.region?.name ?? "the region";
  const lines: Line[] = [];
  const href = (section: string) => topicHref(r.head, section);

  // ---- income
  const inc = mv(m, "uk.income.net");
  if (inc?.p != null) {
    const p = inc.p;
    const d = decileOf(p);
    const word = d >= 7 ? "Wealthy area" : d >= 4 ? "Average incomes" : "Lower-income area";
    const b = insights?.borders;
    const note = b && b.incomeHere != null && b.incomeMin != null && b.incomeMin <= 3 && b.incomeHere >= 5
      ? "Borders lower-income neighbourhoods" : undefined;
    const comp = insights?.income;
    lines.push({
      id: "income", topic: "affluence", title: "Income", verdict: word, badge: <Badge p={p} />, note,
      extra: comp && comp.n > 1 ? <>{insights?.scopeName ?? "The area"}: {comp.high}% of residents in wealthier neighbourhoods, {comp.mid}% average, {comp.low}% low-income.</> : undefined,
    });
  }
  // ---- deprivation (England)
  // deprivation level 1–10 (10 = most deprived): LSOA decile, or for larger areas the national rank of their score
  const imdDec = val(m, "uk.iod25.imd_decile"), imdP = mv(m, "uk.iod25.imd_score")?.p;
  const imd = imdDec ?? (imdP != null ? 11 - decileOf(imdP) : null);
  if (imd != null) {
    const lvl = 11 - Math.round(imd);
    const comp = insights?.deprivation;
    lines.push({
      id: "deprivation", topic: "affluence", title: "Deprivation",
      verdict: lvl >= 8 ? "Deprived area" : lvl >= 4 ? "Average deprivation" : "Not deprived",
      badge: <Badge p={(lvl - 0.5) * 10} bad />,
      note: comp && comp.low >= 25 && lvl < 8 ? `The wider area ${insights?.scopeName ?? ""} contains a significant number of deprived neighbourhoods (${comp.low}% of residents)` : undefined,
    });
  }
  // ---- crime
  const crime = mv(m, "uk.crime.total_rate");
  if (crime?.p != null) {
    const p = crime.p;
    const top = CRIME_TYPES.map(([k, label]) => ({ label, p: mv(m, `uk.crime.${k}_rate`)?.p ?? null }))
      .filter((x) => x.p != null && x.p >= 60).sort((a, b) => b.p! - a.p!).slice(0, 4);
    lines.push({
      id: "crime", topic: "safety", title: "Crime", verdict: decileOf(p) >= 8 ? "High crime rate" : decileOf(p) >= 4 ? "Average crime rate" : "Low crime rate",
      badge: <Badge p={p} bad />, note: top.length ? `Highest relative: ${top.map((x) => `${x.label} ${decileOf(x.p!)}/10`).join(", ")}` : undefined,
    });
  }
  // ---- occupations, degrees
  const prof = mv(m, "uk.share.managerial_professional");
  if (prof?.v != null && prof.p != null) {
    lines.push({ id: "prof", topic: "affluence", title: "Professional occupations", badge: <Badge p={prof.p} />,
      verdict: `${pct(prof.v)} of residents in managerial and professional jobs` });
  }
  const deg = mv(m, "uk.share.degree");
  if (deg?.v != null && deg.p != null) {
    lines.push({ id: "degree", topic: "affluence", title: "Residents with degrees", badge: <Badge p={deg.p} />,
      verdict: `${pct(deg.v)} of residents aged 16+ hold a degree or higher` });
  }
  // ---- tenure
  const own = val(m, "uk.share.owned"), prv = val(m, "uk.share.private_rented"), soc = val(m, "uk.share.social_rented");
  if (own != null && prv != null && soc != null) {
    const socAvg = val(r.regionMetrics, "uk.share.social_rented");
    const b = insights?.borders;
    lines.push({
      id: "tenure", topic: "people", title: "Tenure",
      verdict: `${pct(own)} owned, ${pct(prv)} private rented, ${pct(soc)} social rented`,
      note: [
        socAvg != null ? `${region} average: ${pct(val(r.regionMetrics, "uk.share.owned") ?? 0)} owned, ${pct(val(r.regionMetrics, "uk.share.private_rented") ?? 0)} private, ${pct(socAvg)} social` : null,
        b?.socialMax != null && socAvg != null && b.socialMax >= socAvg * 1.5 && (soc < socAvg * 1.2) ? "Borders an area with a higher than average share of social housing" : null,
      ].filter(Boolean).join(". ") || undefined,
    });
  }
  // ---- noise, air, flood
  const road = val(m, "uk.noise.road_lden55_share"), rail = val(m, "uk.noise.rail_lden55_share"), air = val(m, "uk.noise.airport_lden50_share");
  if (road != null) {
    const worst = Math.max(road, rail ?? 0, air ?? 0);
    const major = point?.roads.find((x) => x.cls === "Motorway" || x.cls === "A Road");
    const sources = point?.noise.filter((x) => x.kind !== "hospital") ?? [];
    lines.push({ id: "noise", topic: "environment", title: "Noise",
      verdict: worst >= 50 ? "Noisy area" : worst >= 15 || sources.length > 2 ? "Potential noise issues" : "Mostly quiet",
      note: [
        `${pct(road)} of residents exposed to road noise above 55 dB${rail ? `, ${pct(rail)} to rail` : ""}${air ? `, ${pct(air)} to aircraft above 50 dB` : ""}`,
        major && major.dist <= 500 ? `${major.number ?? major.cls} ${Math.round(major.dist)} m away` : null,
        sources.length ? `${sources.length} pub${sources.length > 1 ? "s, clubs or emergency stations" : ", club or emergency station"} close by` : null,
      ].filter(Boolean).join(". ") });
  }
  const no2 = point?.air?.no2 ?? val(m, "uk.pcm.no2"), pm25 = point?.air?.pm25 ?? val(m, "uk.pcm.pm25");
  if (no2 != null) {
    lines.push({ id: "air", topic: "environment", title: "Air quality",
      verdict: no2 > 40 ? "Above the legal NO₂ limit" : no2 > 10 || (pm25 ?? 0) > 5 ? "Within UK limits, above WHO guidelines" : "Clean air",
      note: `NO₂ ${no2.toFixed(1)} µg/m³ (UK limit 40, WHO 10)${pm25 != null ? `, PM2.5 ${pm25.toFixed(1)} µg/m³ (UK limit 20, WHO 5)` : ""}` });
  }
  const rs = val(m, "uk.zone.rs_medium_plus_share"), sw = val(m, "uk.zone.sw_medium_plus_share");
  if (rs != null || sw != null) {
    const worst = Math.max(rs ?? 0, sw ?? 0);
    lines.push({ id: "flood", topic: "risk", title: "Flood risk",
      verdict: worst >= 10 ? "Flood risk is identified" : worst > 0 ? "Some streets at risk" : "No or very low flood risk",
      note: `${pct(rs ?? 0)} of homes at medium or high risk from rivers and sea, ${pct(sw ?? 0)} from surface water` });
  }
  // ---- transport
  const ptai = mv(m, "uk.london.ptai"), tcm = mv(m, "uk.tcm.overall");
  if (point?.ptal) {
    const order = ["0", "1a", "1b", "2", "3", "4", "5", "6a", "6b"];
    const pos = order.indexOf(point.ptal.band) + 1;
    lines.push({ id: "transport", topic: "transport", title: "Transport", badge: <Badge p={pos} of={9} />,
      verdict: pos >= 7 ? "Good connectivity to public transport" : pos >= 4 ? "Average connectivity to public transport" : "Limited public transport",
      note: `PTAL ${point.ptal.band} at this address, on TfL's scale from 0 to 6b` });
  } else if (ptai?.v != null) {
    // TfL PTAL bands from the access index: 0, 1a, 1b, 2, 3, 4, 5, 6a, 6b → 1 to 9
    const cuts: [number, string][] = [[0, "0"], [2.5, "1a"], [5, "1b"], [10, "2"], [15, "3"], [20, "4"], [25, "5"], [40, "6a"], [Infinity, "6b"]];
    const i = cuts.findIndex(([hi]) => ptai.v! <= hi);
    const pos = i + 1;
    lines.push({ id: "transport", topic: "transport", title: "Transport", badge: <Badge p={pos} of={9} />,
      verdict: pos >= 7 ? "Good connectivity to public transport" : pos >= 4 ? "Average connectivity to public transport" : "Limited public transport",
      note: `Public transport accessibility level (PTAL) ${cuts[i][1]}, TfL scale 0 to 6b` });
  } else if (tcm?.p != null) {
    const p = tcm.p;
    lines.push({ id: "transport", topic: "transport", title: "Transport", badge: <Badge p={p} />,
      verdict: decileOf(p) >= 7 ? "Good connectivity" : decileOf(p) >= 4 ? "Average connectivity" : "Limited connectivity",
      note: "DfT connectivity to jobs, schools, health and shops by public transport, walking and cycling" });
  }

  if (lines.length < 3) return null;
  return (
    <section className="rs data-says" id="report-data-says" aria-labelledby="h-data-says">
      <h2 id="h-data-says">Data says</h2>
      <p className="sum">Scores out of 10 rank this area against all {h.peers} in England and Wales: 10 is the tenth with the most.</p>
      <ul className="ds">
        {lines.map((l) => {
          const link = href(l.topic);
          return (
            <li key={l.id}>
              <span className="ds-t">{l.title}</span>
              <span className="ds-v">{l.badge}<strong>{l.verdict}</strong></span>
              {l.note && <span className="ds-n">{l.note}</span>}
              {l.extra && <span className="ds-n">{l.extra}</span>}
              {link && <Link className="ds-l" href={link + (l.id === "deprivation" ? "/deprivation" : l.id === "prof" ? "/occupation" : l.id === "degree" ? "/qualification" : l.id === "tenure" ? "/background" : "")}>Details</Link>}
            </li>
          );
        })}
      </ul>
      {(() => {
        // Who the area suits, from the same category scores as the score panel (no reviews needed)
        const cat = Object.fromEntries(r.categories.map((c) => [c.code, c.score]));
        const scored = uk.personas.map((p) => {
          let s = 0, w = 0;
          for (const [k, wt] of Object.entries(p.weights)) { const v = cat[k]; if (v != null && wt > 0) { s += v * wt; w += wt; } }
          return { code: p.code, score: w ? s / w : null, weights: p.weights };
        }).filter((x): x is { code: string; score: number; weights: Record<string, number> } => x.score != null);
        if (scored.length < 3) return null;
        const best = scored.filter((x) => x.score >= 58).sort((a, b) => b.score - a.score).slice(0, 3);
        const worst = scored.filter((x) => x.score <= 42).sort((a, b) => a.score - b.score).slice(0, 2);
        const why = (w: Record<string, number>, good: boolean) => Object.entries(w).filter(([k, wt]) => wt >= 2 && cat[k] != null)
          .sort((a, b) => (good ? (cat[b[0]]! - cat[a[0]]!) : (cat[a[0]]! - cat[b[0]]!))).slice(0, 2)
          .map(([k]) => h.t.categories[k as keyof typeof h.t.categories].toLowerCase()).join(", ");
        const name = (c: string) => h.t.personasPlural[c as keyof typeof h.t.personasPlural];
        if (!best.length && !worst.length) return null;
        return (
          <div className="ds-who">
            <h3>Who it suits</h3>
            {best.length > 0 && <p><b>Best for:</b> {best.map((x) => `${name(x.code)} (${Math.round(x.score)}/100, strong on ${why(x.weights, true)})`).join("; ")}.</p>}
            {worst.length > 0 && <p><b>Less ideal for:</b> {worst.map((x) => `${name(x.code)} (${Math.round(x.score)}/100, weaker on ${why(x.weights, false)})`).join("; ")}.</p>}
            <p className="m-src">Worked out from official data with the weights each kind of household cares about; see how scores work.</p>
          </div>
        );
      })()}
      {oac && (
        <div className="ds-oac">
          <h3>Classification</h3>
          <p><strong>{oac.group.name}</strong> <span className="m-src">({r.head.level === "postcode_unit" ? "this street's group" : `most common group, ${oac.share}% of postcodes`})</span></p>
          {oac.group.text && <p>{oac.group.text}</p>}
          <p><strong>{oac.supergroup.name}</strong> <span className="m-src">(wider family of neighbourhoods)</span></p>
          {oac.supergroup.text && <p>{oac.supergroup.text}</p>}
          <p className="m-src">UK Output Area Classification 2021/22, Geographic Data Service and ONS (Open Government Licence).</p>
        </div>
      )}
    </section>
  );
}
