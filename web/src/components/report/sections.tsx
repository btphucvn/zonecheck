import Link from "next/link";
import type { ReactNode } from "react";
import { tpl } from "@/i18n/config";
import { fmtDistance, fmtMoney, fmtMoneyShort, fmtMonth, fmtNumber, fmtPct, walkMinutes } from "@/lib/format";
import { uk } from "@/markets/uk";
import { StampDutyCalc } from "../tools/Calculators";
import { Bars, Flag, LineChart, Metric } from "./bits";
import { topicHref } from "./nav";
import { ageGroups, distribution, goodness, medianAge, mv, srcLine, val, type H } from "./helpers";
import { M } from "./MetricTile";
export { Checklist, Risk } from "./risk";

function Section({ id, title, summary, more, children }: { id: string; title: string; summary?: ReactNode; more?: { href: string | null; label: string }; children: ReactNode }) {
  return (
    <section className="rs" id={`report-${id}`} aria-labelledby={`h-${id}`}>
      <div className="rs-head">
        <h2 id={`h-${id}`}>{title}</h2>
        {more?.href && <Link className="rs-more" href={more.href}>{more.label} <span aria-hidden="true">→</span></Link>}
      </div>
      {summary && <p className="sum">{summary}</p>}
      {children}
    </section>
  );
}

/** "View …" link from a report section to its detail page. */
const moreOf = (h: H, id: string) => ({ href: topicHref(h.r.head, id), label: h.t.report.more[id as keyof typeof h.t.report.more] });

const pctDiff = (a: number, b: number) => Math.round(((a - b) / b) * 1000) / 10;

/* ---------------------------------------------------------------- prices */
export function Prices({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tp = t.report.prices;
  const median = val(r.metrics, "uk.price.median");
  const ladMedian = val(r.ladMetrics, "uk.price.median");
  const change = val(r.metrics, "uk.price.change_5y_pct");
  const series = (j: unknown) => Object.entries((j ?? {}) as Record<string, { median: number; n: number }>)
    .filter(([, v]) => v && v.median && v.n >= 5).map(([x, v]) => ({ x, y: v.median }));
  const own = series(mv(r.metrics, "uk.price.median_by_year")?.j);
  const lad = r.ctx.lad && r.ctx.lad.id !== r.ctx.dataArea.id ? series(mv(r.ladMetrics, "uk.price.median_by_year")?.j) : [];
  const summary = median
    ? tpl(tp.summaryUp, { median: fmtMoney(median, "GBP", intl), dir: (change ?? 0) >= 0 ? tp.up : tp.down, pct: fmtPct(Math.abs(change ?? 0), intl, 1) }).replace(/, (up|down) 0%.*/, ".")
    : tp.summaryNone;
  return (
    <Section id="prices" title={t.report.sections.prices} more={moreOf(h, "prices")} summary={summary}>
      <div className="metrics">
        <M h={h} id="uk.price.median" name={tp.median}
          note={median && ladMedian && r.ctx.lad && r.ctx.lad.id !== r.ctx.dataArea.id
            ? tpl(tp.vsLad, { diff: fmtPct(Math.abs(pctDiff(median, ladMedian)), intl, 1), dir: median >= ladMedian ? tp.above : tp.below, lad: r.ctx.lad.name })
            : undefined} />
        <M h={h} id="uk.price.change_5y_pct" name={tp.change5y} />
        <M h={h} id="uk.price.sales" name={tp.sales} />
        <M h={h} id="uk.price.per_sqm" />
        <M h={h} id="uk.price.floor_area" />
        {r.ladMetrics["uk.hpi.change_12m"] && <M h={h} id="uk.hpi.change_12m" name={tp.hpi} map={r.ladMetrics} />}
        {r.ctx.lad && val(r.ladMetrics, "uk.afford.median_ratio") != null && (
          <Metric name={tp.afford} value={tpl(tp.affordValue, { x: fmtNumber(val(r.ladMetrics, "uk.afford.median_ratio")!, intl, 1) })}
            note={tpl(tp.affordNote, { lad: r.ctx.lad.name })} src={srcLine(h, "uk.afford.median_ratio", r.ladMetrics)} />
        )}
      </div>
      {(["flat", "terraced", "semi", "detached"] as const).some((k) => val(r.metrics, `uk.price.median_${k}`)) && (
        <>
          <h3 className="sub-h">{tp.byType}</h3>
          <div className="metrics">
            {(["flat", "terraced", "semi", "detached"] as const).map((k) => <M key={k} h={h} id={`uk.price.median_${k}`} />)}
          </div>
        </>
      )}
      {own.length >= 3 && (
        <>
          <h3 className="sub-h">{tp.trend}</h3>
          <LineChart
            series={[{ label: r.head.level === "postcode_unit" ? `Neighbourhood ${r.ctx.dataArea.code}` : r.head.name, points: own }, ...(lad.length ? [{ label: r.ctx.lad!.name, points: lad, dashed: true }] : [])]}
            format={(v) => fmtMoneyShort(v, "GBP", intl)}
            ariaLabel={`Median sale price by year: ${own.map((p) => `${p.x} ${fmtMoney(p.y)}`).join(", ")}`}
          />
          <p className="m-src">HM Land Registry Price Paid Data, standard sales, years with at least 5 sales.</p>
        </>
      )}
      <h3 className="sub-h">{tp.recent}</h3>
      {r.sales.length ? (
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th>{tp.street}</th><th>{tp.type}</th><th>{tp.date}</th><th className="r">{tp.price}</th></tr></thead>
            <tbody>
              {r.sales.map((s, i) => (
                <tr key={i}>
                  <td>{[s.street, s.postcode].filter(Boolean).join(", ") || "–"}</td>
                  <td>{tp.types[s.type as keyof typeof tp.types] ?? s.type}{tp.tenures[s.tenure as keyof typeof tp.tenures] ? `, ${tp.tenures[s.tenure as keyof typeof tp.tenures]}` : ""}{s.newBuild ? `, ${tp.newBuild}` : ""}</td>
                  <td>{fmtMonth(s.date, intl)}</td>
                  <td className="r num">{fmtMoney(s.price, "GBP", intl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="empty-note">{tp.noSales}</p>}
    </Section>
  );
}

/* ---------------------------------------------------------------- rent */
export function Rent({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tr = t.report.rent;
  const L = r.ladMetrics;
  const rent = val(L, "uk.pipr.rental_price");
  const two = val(L, "uk.pipr.rental_price_two_bed");
  const income = val(r.metrics, "uk.income.net");
  const change = val(L, "uk.pipr.annual_change");
  const beds: [string, number][] = ([["1 bedroom", "one_bed"], ["2 bedrooms", "two_bed"], ["3 bedrooms", "three_bed"], ["4 or more", "four_or_more_bed"]] as const)
    .map(([l, k]) => [l, val(L, `uk.pipr.rental_price_${k}`) ?? 0] as [string, number]).filter(([, v]) => v > 0);
  if (!rent || !r.ctx.lad) return <Section id="rent" title={t.report.sections.rent} more={moreOf(h, "rent")} summary={tr.noData}>{null}</Section>;
  const ratio = two && income ? ((two * 12) / income) * 100 : null;
  const price = val(r.metrics, "uk.price.median") ?? val(L, "uk.price.median");
  const yieldPct = price ? ((rent * 12) / price) * 100 : null;
  return (
    <Section id="rent" title={t.report.sections.rent} more={moreOf(h, "rent")}
      summary={tpl(tr.summary, { lad: r.ctx.lad.name, rent: fmtMoney(rent, "GBP", intl), dir: (change ?? 0) >= 0 ? t.report.prices.up : t.report.prices.down, pct: fmtPct(Math.abs(change ?? 0), intl, 1) })}>
      <div className="metrics">
        <M h={h} id="uk.pipr.rental_price_two_bed" map={L} name="Two-bed rent, monthly" />
        {ratio != null && (
          <Metric name={tr.rentToIncome} value={fmtPct(ratio, intl)} p={Math.max(0, Math.min(100, 100 - (ratio - 15) * 2))} note={tr.rentToIncomeNote} src="ONS Price Index of Private Rents; ONS small area income" />
        )}
        {yieldPct != null && yieldPct > 0.5 && yieldPct < 20 && (
          <Metric name={tr.yield} value={fmtPct(yieldPct, intl, 1)} note={tpl(tr.yieldNote, { lad: r.ctx.lad.name })} src="ONS Price Index of Private Rents; HM Land Registry Price Paid Data" />
        )}
      </div>
      {beds.length > 0 && (
        <>
          <h3 className="sub-h">{tr.byBeds}</h3>
          <Bars rows={beds} format={(v) => fmtMoney(v, "GBP", intl)} />
        </>
      )}
      {r.rentHistory.length > 12 && (
        <>
          <h3 className="sub-h">{tr.trend}</h3>
          <LineChart series={[{ label: r.ctx.lad.name, points: r.rentHistory.map((p) => ({ x: p.period, y: p.v })) }]} format={(v) => fmtMoney(v, "GBP", intl)} ariaLabel={`Average monthly rent in ${r.ctx.lad.name} over ten years`} height={190} />
        </>
      )}
      <p className="m-src">{srcLine(h, "uk.pipr.rental_price", L)}</p>
    </Section>
  );
}

/* ---------------------------------------------------------------- safety */
export function Safety({ h }: { h: H }) {
  const { r, t, intl } = h;
  const ts = t.report.safety;
  const rate = val(r.metrics, "uk.crime.total_rate");
  const nat = val(r.nationMetrics, "uk.crime.total_rate");
  if (rate == null) return <Section id="safety" title={t.report.sections.safety} summary={ts.noData}>{null}</Section>;
  const more = moreOf(h, "safety");
  const types: [string, string][] = [["Violence and robbery", "violent"], ["Theft", "theft"], ["Anti-social behaviour", "asb"], ["Criminal damage", "damage"], ["Vehicle crime", "vehicle"], ["Burglary", "burglary"]];
  const rows = types.map(([l, k]) => [l, val(r.metrics, `uk.crime.${k}_rate`) ?? 0] as [string, number]);
  return (
    <Section id="safety" title={t.report.sections.safety} more={more}
      summary={tpl(ts.summary, { rate: fmtNumber(rate, intl, 0), cmp: nat != null && r.ctx.nation ? tpl(ts.cmpNation, { nation: r.ctx.nation.name, n: fmtNumber(nat, intl, 0) }) : "" })}>
      <div className="metrics">
        <M h={h} id="uk.crime.total_rate" name="All crime per 1,000 residents" />
        <M h={h} id="uk.crime.violent_rate" name="Violent crime per 1,000" />
        <M h={h} id="uk.crime.burglary_rate" name="Burglary per 1,000" />
        <M h={h} id="uk.crime.total_change_pct" name={ts.change} />
      </div>
      <h3 className="sub-h">{ts.byType}</h3>
      <Bars rows={rows} format={(v) => fmtNumber(v, intl, 1)} />
      <p className="m-src">{ts.note} data.police.uk.</p>
      {more.href && <p className="rs-more-foot"><Link className="rs-more" href={more.href}>{t.report.more.safetyFoot} <span aria-hidden="true">→</span></Link></p>}
      {(val(r.metrics, "uk.road.collisions_per_1k") != null || val(r.ladMetrics, "uk.flytip.per_1k") != null) && (
        <>
          <h3 className="sub-h">{ts.roads}</h3>
          <div className="metrics">
            <M h={h} id="uk.road.collisions_per_1k" />
            <M h={h} id="uk.road.ksi_per_1k" />
            {r.ctx.lad && <M h={h} id="uk.flytip.per_1k" map={r.ladMetrics} note={tpl(ts.ladNote, { lad: r.ctx.lad.name })} />}
          </div>
        </>
      )}
    </Section>
  );
}

/* ---------------------------------------------------------------- schools */
function OfstedBadge({ label, rank }: { label: string; rank: number | null }) {
  const c = label === "Report card" ? "var(--ink-2)" : rank === 1 ? "var(--good)" : rank === 2 ? "var(--water)" : rank === 3 ? "var(--mid)" : rank === 4 ? "var(--bad)" : "var(--ink-2)";
  return <span className="ofsted" style={{ color: c }}>{label}</span>;
}

export function Schools({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tsc = t.report.schools;
  const rated = r.schools.filter((s) => s.rating && s.rating.scheme === "ofsted_oeif");
  const good = rated.filter((s) => (s.rating!.rank ?? 9) <= 2).length;
  const far = r.schools.length ? r.schools[r.schools.length - 1].dist : 0;
  const phase = (type: string) => type.replace("school.", "").replace("_", "-").replace(/^./, (c) => c.toUpperCase());
  return (
    <Section id="schools" title={t.report.sections.schools} more={moreOf(h, "schools")}
      summary={r.schools.length ? tpl(tsc.summary, { n: r.schools.length, d: fmtDistance(far, intl), good: rated.length ? `${good} of ${rated.length}` : "None" }) : tsc.summaryNone}>
      {r.schools.length > 0 && (
        <div className="scroll-x">
          <table className="data">
            <thead><tr><th>{tsc.school}</th><th>{tsc.phase}</th><th>{tsc.ofsted}</th><th>{tsc.result}</th><th className="r">{tsc.distance}</th></tr></thead>
            <tbody>
              {r.schools.map((s) => (
                <tr key={s.id}>
                  <td>{s.slug ? <Link href={`/uk/school/${s.slug}`}>{s.name}</Link> : s.name}</td>
                  <td>{phase(s.type)}</td>
                  <td>{s.rating ? <OfstedBadge label={s.rating.label} rank={s.rating.rank} /> : <span className="m-src">{tsc.notRated}</span>}</td>
                  <td className="num">{s.keyMetric ? (s.keyMetric.id.includes("ks2") ? `${fmtNumber(s.keyMetric.v, intl)}% KS2` : `A8 ${fmtNumber(s.keyMetric.v, intl, 1)}`) : "–"}</td>
                  <td className="r num">{fmtDistance(s.dist, intl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r.nurseries.length > 0 && (
        <>
          <h3 className="sub-h">{tsc.nurseries}</h3>
          <div className="scroll-x">
            <table className="data">
              <thead><tr><th>{tsc.nursery}</th><th>{tsc.nurseryType}</th><th>{tsc.ofsted}</th><th className="r">{tsc.places}</th><th className="r">{tsc.distance}</th></tr></thead>
              <tbody>
                {r.nurseries.map((n) => (
                  <tr key={n.id}>
                    <td>{n.name}</td>
                    <td>{n.attrs.subtype ?? "–"}</td>
                    <td>{n.rating ? <OfstedBadge label={n.rating.label} rank={n.rating.rank} /> : <span className="m-src">{tsc.notRated}</span>}</td>
                    <td className="r num">{Number(n.attrs.places) > 0 ? fmtNumber(Number(n.attrs.places), intl) : "–"}</td>
                    <td className="r num">{fmtDistance(n.dist, intl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="m-src">{tsc.nurseryNote}</p>
        </>
      )}
      <div className="metrics" style={{ marginTop: 18 }}>
        <M h={h} id="uk.schools.primary_quality" name="Nearby primaries, % meeting KS2 standard" />
        <M h={h} id="uk.schools.secondary_quality" name="Nearby secondaries, Attainment 8" />
      </div>
      <p className="m-src">{tsc.note} DfE GIAS, Ofsted, DfE school performance tables.</p>
    </Section>
  );
}

/* ---------------------------------------------------------------- transport */
export function Transport({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tt = t.report.transport;
  const first = r.stations[0];
  const work = distribution(mv(r.metrics, "uk.census21.ts061")?.j, { exclude: /not in employment/i, top: 7 });
  const zones = r.stations.some((s) => s.attrs.tfl_zone);
  const ptai = mv(r.metrics, "uk.london.ptai");
  const ptal = (ptai?.j as { ptal?: string } | null)?.ptal ?? null;
  return (
    <Section id="transport" title={t.report.sections.transport} more={moreOf(h, "transport")}
      summary={first ? tpl(tt.summary, { station: first.name.replace(/ Rail Station$/, ""), min: walkMinutes(first.dist) }) : tt.summaryNone}>
      {r.stations.length > 0 && (
        <div className="scroll-x" style={{ marginBottom: 18 }}>
          <table className="data">
            <thead><tr><th>{tt.station}</th>{zones && <th>{tt.zone}</th>}<th className="r">{tt.usage}</th><th className="r">{t.report.schools.distance}</th><th className="r">{tt.walk}</th></tr></thead>
            <tbody>
              {r.stations.map((s) => (
                <tr key={s.id}>
                  <td>{s.slug ? <Link href={`/uk/station/${s.slug}`}>{s.name}</Link> : s.name}</td>
                  {zones && <td>{s.attrs.tfl_zone ?? "–"}</td>}
                  <td className="r num">{s.keyMetric ? fmtNumber(s.keyMetric.v, intl) : "–"}</td>
                  <td className="r num">{fmtDistance(s.dist, intl)}</td>
                  <td className="r num">{s.dist < 4000 ? `${walkMinutes(s.dist)} min` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="metrics">
        {ptai?.v != null && (
          <Metric name={tt.ptal} value={ptal ?? fmtNumber(ptai.v, intl, 1)} p={goodness(h, "uk.london.ptai")} note={tt.ptalNote} src={srcLine(h, "uk.london.ptai")} />
        )}
        <M h={h} id="uk.tcm.overall" name="Transport connectivity score" />
        <M h={h} id="uk.access.rail_dist_m" />
        <M h={h} id="uk.access.bus_stops_500m" />
        <M h={h} id="uk.tcm.public_transport_overall" />
      </div>
      {work.length > 0 && (
        <>
          <h3 className="sub-h">{tt.toWork}</h3>
          <Bars rows={work} format={(v) => fmtPct(v, intl)} max={100} />
          <p className="m-src">{tt.toWorkNote}</p>
        </>
      )}
    </Section>
  );
}

/* ---------------------------------------------------------------- amenities */
export function Amenities({ h }: { h: H }) {
  const { r, t, intl } = h;
  const gp = r.amenities.find((a) => a.type === "health.gp");
  const shop = r.amenities.find((a) => a.type === "shop.supermarket");
  const label: Record<string, string> = { "health.gp": "GP practice", "health.pharmacy": "Pharmacy", "health.dentist": "Dentist", "shop.supermarket": "Supermarket" };
  return (
    <Section id="amenities" title={t.report.sections.amenities} more={moreOf(h, "amenities")}
      summary={gp && shop ? tpl(t.report.amenities.summary, { gp: `${gp.name}, ${fmtDistance(gp.dist, intl)}`, shop: `${shop.name}, ${fmtDistance(shop.dist, intl)}` }) : undefined}>
      <div className="metrics">
        <M h={h} id="uk.access.gp_dist_m" />
        <M h={h} id="uk.access.supermarket_dist_m" />
        <M h={h} id="uk.access.pharmacy_dist_m" />
        <M h={h} id="uk.access.park_dist_m" />
        <M h={h} id="uk.access.food_1km" />
      </div>
      {r.amenities.length > 0 && (
        <>
          <h3 className="sub-h">{t.report.amenities.nearest}</h3>
          <div className="scroll-x">
            <table className="data">
              <tbody>
                {r.amenities.map((a) => (
                  <tr key={a.id}>
                    <td>{label[a.type] ?? a.type}</td>
                    <td>{a.name}{a.rating ? <span className="m-src">, CQC {a.rating.label}</span> : null}</td>
                    <td className="r num">{fmtDistance(a.dist, intl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="m-src">NHS ODS, OpenStreetMap and Geolytix retail points. Straight-line distance.</p>
        </>
      )}
    </Section>
  );
}

/* ---------------------------------------------------------------- environment */
const WHO: Record<string, number> = { "uk.pcm.no2": 10, "uk.pcm.pm25": 5, "uk.pcm.pm10": 15 };

export function Environment({ h }: { h: H }) {
  const { r, t, intl } = h;
  const te = t.report.environment;
  const rp = r.riskPoint;
  const aqma = rp ? (rp.zones["env.aqma"] !== undefined ? 100 : 0) : val(r.metrics, "uk.zone.aqma_share");
  const noise = rp?.noise;
  const noiseShares = ([["uk.noise.road_lden65_share", 10], ["uk.noise.any_lden55_share", 50], ["uk.noise.night50_share", 30], ["uk.noise.airport_lden50_share", 10]] as const)
    .filter(([id]) => val(r.metrics, id) != null);
  const climate = ["uk.climate.tas", "uk.climate.rainfall", "uk.climate.summer_days", "uk.climate.airfrost_days"].filter((id) => val(r.metrics, id) != null);
  const top = r.overflows[0];
  const db = (v: number | null) => (v == null ? null : v < 55 ? te.noiseQuiet : tpl(te.noiseAt, { db: v }));
  return (
    <Section id="environment" title={t.report.sections.environment} more={moreOf(h, "environment")} summary={te.summary}>
      <div className="flags">
        {(["uk.pcm.no2", "uk.pcm.pm25", "uk.pcm.pm10"] as const).map((id) => {
          const v = val(r.metrics, id);
          if (v == null) return null;
          const who = WHO[id];
          return <Flag key={id} k={h.cat[id]?.shortName ?? h.cat[id]?.name ?? id} v={`${fmtNumber(v, intl, 1)} µg/m³`} tone={v <= who ? "g" : v <= who * 2 ? "m" : "b"} s={`${tpl(te.who, { v: `${who} µg/m³` })}. ${srcLine(h, id)}`} />;
        })}
        {aqma != null && (
          <Flag k={te.aqma} v={aqma === 0 ? te.none : rp ? t.report.planning.yes : tpl(te.inZone, { p: fmtNumber(aqma, intl, aqma < 1 ? 1 : 0) })} tone={aqma === 0 ? "g" : "m"} s={te.aqmaSrc} />
        )}
        {noise && (
          <>
            <Flag k={`${te.noise}: ${te.noiseRoad.toLowerCase()}`} v={db(noise.roadLden) ?? te.none} tone={(noise.roadLden ?? 0) >= 65 ? "b" : (noise.roadLden ?? 0) >= 55 ? "m" : "g"} s={te.noiseSrc} />
            {(noise.railLden ?? 0) >= 55 && <Flag k={`${te.noise}: ${te.noiseRail.toLowerCase()}`} v={db(noise.railLden)!} tone={(noise.railLden ?? 0) >= 65 ? "b" : "m"} s={te.noiseSrc} />}
            {(noise.airportLden ?? 0) >= 50 && <Flag k={`${te.noise}: ${te.noiseAir.toLowerCase()}`} v={tpl(te.noiseAt, { db: noise.airportLden! })} tone={(noise.airportLden ?? 0) >= 60 ? "b" : "m"} s={te.noiseSrc} />}
          </>
        )}
      </div>
      <div className="metrics" style={{ marginTop: 18 }}>
        <M h={h} id="uk.pcm.no2" />
        <M h={h} id="uk.pcm.pm25" />
      </div>
      {!noise && noiseShares.length > 0 && (
        <>
          <h3 className="sub-h">{te.noiseShares}</h3>
          <div className="metrics">{noiseShares.map(([id]) => <M key={id} h={h} id={id} />)}</div>
        </>
      )}
      {climate.length > 0 && (
        <>
          <h3 className="sub-h">{te.climate}</h3>
          <div className="metrics">{climate.map((id) => <M key={id} h={h} id={id} />)}</div>
          <p className="m-src">{te.climateSrc}</p>
        </>
      )}
      {["postcode_unit", "sector", "district"].includes(r.head.level) && (
        <>
          <h3 className="sub-h">{te.overflows}</h3>
          {top ? (
            <>
              <p>{tpl(te.overflowsSummary, { n: r.overflows.length, h: fmtNumber(top.hours ?? 0, intl), y: top.year ?? "" })}</p>
              <div className="scroll-x">
                <table className="data">
                  <thead><tr><th>{te.overflow}</th><th>{te.water}</th><th className="r">{te.spills}</th><th className="r">{te.hours}</th><th className="r">{t.report.schools.distance}</th></tr></thead>
                  <tbody>
                    {r.overflows.slice(0, 5).map((o, i) => (
                      <tr key={i}>
                        <td>{o.name}{o.company ? <span className="m-src">, {o.company}</span> : null}</td>
                        <td>{o.water ?? "–"}</td>
                        <td className="r num">{o.spills != null ? fmtNumber(o.spills, intl) : "–"}</td>
                        <td className="r num">{o.hours != null ? fmtNumber(o.hours, intl) : "–"}</td>
                        <td className="r num">{fmtDistance(o.dist, intl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="m-src">{te.overflowsSrc}</p>
            </>
          ) : <p className="empty-note">{te.overflowsNone}</p>}
        </>
      )}
      <p className="m-src" style={{ marginTop: 12 }}>{te.note}</p>
    </Section>
  );
}

export function Connectivity({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tc = t.report.connectivity;
  const giga = val(r.metrics, "uk.bb.gigabit_pct");
  const mobile = ["uk.mobile.4g_indoor_all", "uk.mobile.5g_outdoor_any", "uk.mobile.voice_indoor_all"].filter((id) => val(r.ladMetrics, id) != null);
  return (
    <Section id="connectivity" title={t.report.sections.connectivity} more={moreOf(h, "connectivity")}
      summary={giga != null ? tpl(tc.summaryGigabit, { p: fmtNumber(giga, intl, 0) }) : tc.summaryNone}>
      <div className="metrics">
        <M h={h} id="uk.bb.gigabit_pct" />
        <M h={h} id="uk.bb.ufbb_pct" />
        <M h={h} id="uk.bb.sfbb_pct" />
        <M h={h} id="uk.bb.no_decent_pct" />
      </div>
      {mobile.length > 0 && r.ctx.lad && (
        <>
          <h3 className="sub-h">{tpl(tc.mobileIn, { lad: r.ctx.lad.name })}</h3>
          <div className="metrics">
            {mobile.map((id) => <M key={id} h={h} id={id} map={r.ladMetrics} />)}
          </div>
        </>
      )}
      <p className="m-src">{tc.note} <a href="https://www.ofcom.org.uk/mobile-coverage-checker" rel="noopener">{tc.link}</a></p>
    </Section>
  );
}

/* ---------------------------------------------------------------- people */
export function People({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tp = t.report.people;
  const age = mv(r.metrics, "uk.census21.ts007a")?.j;
  const tenure = mv(r.metrics, "uk.census21.ts054")?.j as Record<string, number> | undefined;
  const pop = val(r.metrics, "uk.census21.ts001") ?? r.head.population;
  const med = medianAge(age);
  const tenureRows = distribution(tenure, { exclude: /lives rent free/i });
  const owned = tenureRows.find(([k]) => /^owned/i.test(k))?.[1];
  const england = r.ctx.nation?.code?.startsWith("E");
  const decileId = england ? "uk.iod25.imd_decile" : "uk.wimd25.overall_decile";
  const decile = val(r.metrics, decileId);
  return (
    <Section id="people" title={t.report.sections.people} more={moreOf(h, "people")}
      summary={pop && med && owned != null ? tpl(tp.summary, { pop: fmtNumber(pop, intl), age: med, own: Math.round(owned) }) : undefined}>
      <div className="metrics">
        {med != null && <Metric name={tp.medianAge} value={String(med)} src="Census 2021" />}
        <M h={h} id="uk.income.net" name={tp.income} note={tp.incomeNote} />
        {decile != null && (
          <Metric name={tp.deprivation} value={tpl(tp.decile, { d: Math.round(decile) })} p={decile * 10 - 5}
            note={tpl(tp.decileNote, { nation: r.ctx.nation?.name ?? "England" })} src={england ? "English Indices of Deprivation 2025" : "Welsh Index of Multiple Deprivation 2025"} />
        )}
        <M h={h} id={england ? "uk.iod25.imd_score" : "uk.wimd25.overall_score"} />
      </div>
      {age != null && <><h3 className="sub-h">{tp.age}</h3><Bars rows={ageGroups(age)} format={(v) => fmtPct(v, intl)} max={60} /></>}
      {tenureRows.length > 0 && <><h3 className="sub-h">{tp.tenure}</h3><Bars rows={tenureRows} format={(v) => fmtPct(v, intl)} max={100} /></>}
      {(() => {
        const q = distribution(mv(r.metrics, "uk.census21.ts067")?.j, { top: 6 });
        return q.length ? <><h3 className="sub-h">{tp.qualifications}</h3><Bars rows={q} format={(v) => fmtPct(v, intl)} max={100} /></> : null;
      })()}
      {(() => {
        const q = distribution(mv(r.metrics, "uk.census21.ts045")?.j);
        return q.length ? <><h3 className="sub-h">{tp.cars}</h3><Bars rows={q} format={(v) => fmtPct(v, intl)} max={100} /></> : null;
      })()}
      <p className="m-src">Census 2021, ONS. Ethnicity and religion are published by ONS but not used in any score.</p>
      {r.mp && (
        <p style={{ marginTop: 14 }}>
          {tpl(tp.mp, { name: r.mp.name, party: r.mp.party ?? "", constituency: r.mp.constituency })}
          <span className="m-src"> {tp.mpSrc}</span>
        </p>
      )}
    </Section>
  );
}

/* ---------------------------------------------------------------- energy */
export function Energy({ h }: { h: H }) {
  const { r, t, intl } = h;
  const te = t.report.energy;
  const e = r.epc;
  const heat = distribution(mv(r.metrics, "uk.census21.ts046")?.j, { top: 5 });
  const acc = distribution(mv(r.metrics, "uk.census21.ts044")?.j, { top: 5 });
  const good = e ? (["A", "B", "C"].reduce((s, k) => s + (e.ratings[k] ?? 0), 0) / e.total) * 100 : null;
  const potTotal = e ? Object.values(e.potential).reduce((s, n) => s + n, 0) : 0;
  const potGood = e && potTotal ? (["A", "B", "C"].reduce((s, k) => s + (e.potential[k] ?? 0), 0) / potTotal) * 100 : null;
  const ageTotal = e ? Object.values(e.ages).reduce((s, n) => s + n, 0) : 0;
  const ages: [string, number][] = e && ageTotal
    ? ["Before 1900", "1900 to 1929", "1930 to 1949", "1950 to 1975", "1976 to 1999", "2000 onwards"].map((k) => [k, ((e.ages[k] ?? 0) / ageTotal) * 100] as [string, number])
    : [];
  return (
    <Section id="energy" title={t.report.sections.energy} more={moreOf(h, "energy")}
      summary={e && good != null ? tpl(te.summary, { share: Math.round(good), area: e.medianFloorArea ? Math.round(e.medianFloorArea) : "–" }) : undefined}>
      {e && (
        <>
          <h3 className="sub-h" style={{ marginTop: 0 }}>{te.ratings}</h3>
          <Bars rows={["A", "B", "C", "D", "E", "F", "G"].map((k) => [`EPC ${k}`, ((e.ratings[k] ?? 0) / e.total) * 100] as [string, number])} format={(v) => fmtPct(v, intl)} />
          <p className="m-src">{tpl(te.note, { n: fmtNumber(e.total, intl) })} MHCLG EPC register.</p>
          {potGood != null && good != null && (
            <p>{tpl(te.potential, { now: Math.round(good), could: Math.round(potGood) })}</p>
          )}
          {ages.length > 0 && <><h3 className="sub-h">{te.age}</h3><Bars rows={ages} format={(v) => fmtPct(v, intl)} /></>}
        </>
      )}
      {acc.length > 0 && <><h3 className="sub-h">{te.accommodation}</h3><Bars rows={acc} format={(v) => fmtPct(v, intl)} max={100} /></>}
      {heat.length > 0 && <><h3 className="sub-h">{te.heating}</h3><Bars rows={heat} format={(v) => fmtPct(v, intl)} max={100} /><p className="m-src">Census 2021</p></>}
    </Section>
  );
}

/* ---------------------------------------------------------------- planning */
export function Planning({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tp = t.report.planning;
  const zones: [string, string, string][] = [
    ["Conservation area", "planning.conservation_area", "uk.zone.conservation_area_share"],
    ["Article 4 direction", "planning.article4", "uk.zone.article4_share"],
    ["Green belt", "planning.green_belt", "uk.zone.green_belt_share"],
    ["National Park", "nature.national_park", "uk.zone.national_park_share"],
    ["National Landscape (AONB)", "nature.national_landscape", "uk.zone.national_landscape_share"],
    ["Site of Special Scientific Interest", "nature.sssi", ""],
  ];
  return (
    <Section id="planning" title={t.report.sections.planning} more={moreOf(h, "planning")} summary={tp.summary}>
      <div className="flags">
        {zones.map(([label, type, metric]) => {
          const zone = r.zones.find((z) => z.type === type);
          const share = metric ? val(r.metrics, metric) : null;
          const inside = (share ?? 0) > 0 || !!zone?.intersects;
          const v = !inside ? tp.none : share != null && share < 99.5 ? tpl(tp.partial, { p: fmtNumber(share, intl, share < 1 ? 1 : 0) }) : tp.yes;
          return <Flag key={type} k={label} v={v} tone={inside ? "m" : "g"} s={zone?.names ? zone.names.slice(0, 120) : "planning.data.gov.uk, Natural England"} />;
        })}
        {r.listedCount != null && (
          <Flag k={tp.listed} v={r.listedCount ? tpl(r.head.level === "postcode_unit" ? tp.listedNear : tp.listedWithin, { n: fmtNumber(r.listedCount, intl) }) : tp.none} tone={r.listedCount ? "n" : "g"} s="Historic England" />
        )}
      </div>
      <p className="m-src" style={{ marginTop: 12 }}>{tp.note}</p>
      {r.tribunals && r.tribunals.total > 0 && (
        <>
          <h3 className="sub-h">{tp.tribunals}</h3>
          <p>{tpl(tp.tribunalsSummary, { n: fmtNumber(r.tribunals.total, intl) })}</p>
          <ul className="plain-list">
            {r.tribunals.recent.map((c) => (
              <li key={c.link}>
                <a href={c.link} rel="noopener nofollow">{tribunalAddress(c.title, c.caseRef)}</a>
                <span className="m-src"> {[c.caseRef, c.date ? fmtMonth(c.date, intl) : null].filter(Boolean).join(", ")}</span>
              </li>
            ))}
          </ul>
          <p className="m-src">{tp.tribunalsNote}</p>
        </>
      )}
    </Section>
  );
}

/** Titles are "address: case ref" or "case ref: address"; keep the address. */
function tribunalAddress(title: string, ref: string | null): string {
  if (!ref) return title;
  return title.replace(`${ref}:`, "").replace(`: ${ref}`, "").trim();
}

/* ---------------------------------------------------------------- costs */
export function Costs({ h }: { h: H }) {
  const { r, t, intl } = h;
  const tc = t.report.costs;
  const bandD = val(r.ladMetrics, "uk.ctax.band_d");
  const stock = distribution(mv(r.metrics, "uk.ctax.stock")?.j, { order: ["A", "B", "C", "D", "E", "F", "G", "H", "I"] });
  const year = r.ctaxBands[0]?.year ?? "";
  const median = val(r.metrics, "uk.price.median") ?? val(r.ladMetrics, "uk.price.median") ?? 300000;
  const wales = r.ctx.nation?.code?.startsWith("W");
  return (
    <Section id="costs" title={t.report.sections.costs} more={moreOf(h, "costs")}
      summary={bandD && r.ctx.lad ? tpl(tc.summary, { lad: r.ctx.lad.name, bandD: fmtMoney(bandD, "GBP", intl), year }) : undefined}>
      {r.ctaxBands.length > 0 && (
        <>
          <h3 className="sub-h" style={{ marginTop: 0 }}>{tpl(tc.bands, { year })}</h3>
          <div className="scroll-x">
            <table className="data">
              <thead><tr>{r.ctaxBands.map((b) => <th key={b.band} className="r">{b.band}</th>)}</tr></thead>
              <tbody><tr>{r.ctaxBands.map((b) => <td key={b.band} className="r num">{fmtMoney(b.amount, "GBP", intl)}</td>)}</tr></tbody>
            </table>
          </div>
          <p className="m-src">Council tax per year before discounts. {r.ctx.lad?.name}, MHCLG / Welsh Government.</p>
        </>
      )}
      {stock.length > 0 && (
        <>
          <h3 className="sub-h">{tc.stock}</h3>
          <Bars rows={stock.map(([k, v]) => [`Band ${k}`, v])} format={(v) => fmtPct(v, intl)} />
          <p className="m-src">{srcLine(h, "uk.ctax.stock")}</p>
        </>
      )}
      <h3 className="sub-h">{tc.stampDuty}</h3>
      <StampDutyCalc initialPrice={Math.round(median / 1000) * 1000} nation={wales ? "wales" : "england"} />
    </Section>
  );
}

/* ---------------------------------------------------------------- nearby */
export function Nearby({ h }: { h: H }) {
  const { r, t, intl } = h;
  if (!r.nearby.length) return null;
  return (
    <Section id="nearby" title={t.report.sections.nearby} summary={t.report.nearby.summary}>
      <div className="nearby">
        {r.nearby.map((n) => (
          <Link key={n.id} href={`/uk/${uk.segmentForLevel(n.level)}/${n.slug}`}>
            <b>{n.level === "town" || n.level === "lad" || n.level === "region" ? n.name : n.code}</b>
            <span>{n.price ? tpl(t.report.nearby.median, { p: fmtMoneyShort(n.price, "GBP", intl) }) : n.displayName ?? ""}</span>
            {n.crime != null && <><br /><span>{fmtNumber(n.crime, intl)} crimes / 1,000</span></>}
          </Link>
        ))}
      </div>
    </Section>
  );
}
