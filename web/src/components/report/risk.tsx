import { tpl } from "@/i18n/config";
import { fmtDistance, fmtNumber } from "@/lib/format";
import { ChecklistClient, type ChecklistItem } from "./ChecklistClient";
import { MapGlyph, type GlyphKind } from "./glyphs";
import Link from "next/link";
import { val, type H } from "./helpers";
import { topicHref } from "./nav";

type Tone = "g" | "m" | "b";

/** One flood, ground or contamination check, with the question to ask when it is not clear. */
export interface RiskCheck {
  key: string;
  label: string;
  value: string;
  tone: Tone;
  src: string;
  ask?: string;
}

const pctText = (h: H, p: number) => tpl(h.t.report.risk.residents, { p: fmtNumber(p, h.intl, p < 1 ? 1 : 0) });

/**
 * Every check that has data for this page, in the order a buyer worries about them.
 * Postcode units use exact point checks at the postcode centre; larger areas use the
 * share of residents (by postcode) inside each zone.
 */
export function riskChecks(h: H): RiskCheck[] {
  const { r, t } = h;
  const tr = t.report.risk;
  const q = t.report.checklist.ask;
  const rp = r.riskPoint;
  const wales = r.ctx.nation?.code?.startsWith("W");
  const out: RiskCheck[] = [];
  const add = (c: RiskCheck | null) => { if (c) out.push(c); };

  /** Area check from a share-of-residents metric: 0 is clear, `bad` or more is significant. */
  const share = (key: string, id: string, label: string, src: string, bad: number, ask: string, unit = tr.residents): RiskCheck | null => {
    const v = val(r.metrics, id);
    if (v == null) return null;
    const tone: Tone = v === 0 ? "g" : v >= bad ? "b" : "m";
    const value = v === 0 ? tr.none : tpl(unit, { p: fmtNumber(v, h.intl, v < 1 ? 1 : 0) });
    return { key, label, value, tone, src, ask: tone === "g" ? undefined : ask };
  };
  const at = (types: string[]) => types.map((x) => rp?.zones[x]).filter((x) => x !== undefined) as (number | null)[];
  const inZone = (...types: string[]) => at(types).length > 0;
  const maxRank = (...types: string[]) => Math.max(0, ...at(types).map((x) => x ?? 0));

  // ---- flooding: rivers and sea
  if (rp) {
    const z3 = inZone(wales ? "flood.wales_zone3" : "flood.zone3");
    const z2 = z3 || inZone(wales ? "flood.wales_zone2" : "flood.zone2");
    add({
      key: "fz", label: tr.floodZone, tone: z3 ? "b" : z2 ? "m" : "g",
      value: z3 ? tr.zone3 : z2 ? tr.zone2 : tr.zone1, src: wales ? tr.srcNrwZones : tr.srcEaZones, ask: z2 ? q.flood : undefined,
    });
    if (!wales) {
      const f = rp.rofrs;
      const tone: Tone = f && f.high > 0 ? "b" : f && f.medium > 0 ? "m" : "g";
      const value = !f || f.residential === 0 ? tr.rsNone
        : f.high > 0 ? tpl(tr.rsHigh, { n: fmtNumber(f.high, h.intl), total: fmtNumber(f.residential, h.intl) })
        : f.medium > 0 ? tpl(tr.rsMedium, { n: fmtNumber(f.medium, h.intl), total: fmtNumber(f.residential, h.intl) })
        : tpl(tr.rsLow, { total: fmtNumber(f.residential, h.intl) });
      add({ key: "rs", label: tr.riversSea, value, tone, src: tr.srcRofrs, ask: tone === "g" ? undefined : q.flood });
    }
  } else if (wales) {
    add(share("fz", "uk.zone.wales_flood_zone3_share", tr.floodZone3, tr.srcNrwZones, 10, q.flood));
    add(share("rs", "uk.zone.wales_rs_high_share", tr.riversSeaHigh, tr.srcNrw, 10, q.flood));
  } else {
    add(share("fz", "uk.zone.flood_zone3_share", tr.floodZone3, tr.srcEaZones, 10, q.flood));
    add(share("rs", "uk.zone.rs_high_share", tr.riversSeaHigh, tr.srcRofrs, 5, q.flood));
  }

  // ---- surface water (area figure: checked at each home with an EPC)
  add(share("sw", "uk.zone.sw_high_share", tr.surfaceHigh, tr.srcSurface, 5, q.surface, tr.homes));

  // ---- flooded before
  if (rp) {
    const hit = inZone("flood.historic", "flood.wales_historic");
    add({ key: "fh", label: tr.floodHistoric, value: hit ? tr.inside : tr.none, tone: hit ? "m" : "g", src: tr.srcHistoric, ask: hit ? q.floodHistoric : undefined });
  } else add(share("fh", "uk.zone.flood_historic_share", tr.floodHistoric, tr.srcHistoric, 25, q.floodHistoric));

  // ---- radon
  if (rp && rp.zones["radon.atlas"] !== undefined) {
    const c = maxRank("radon.atlas");
    const tone: Tone = c <= 1 ? "g" : c <= 3 ? "m" : "b";
    add({ key: "radon", label: tr.radon, value: tr.radonClass[Math.max(0, c - 1)] ?? tr.none, tone, src: tr.srcRadon, ask: tone === "g" ? undefined : q.radon });
  } else if (!rp) {
    const hi = val(r.metrics, "uk.zone.radon_5pct_share");
    const c = share("radon", "uk.zone.radon_1pct_share", tr.radonArea, tr.srcRadon, 50, q.radon);
    if (c && hi != null && hi > 0) { c.tone = "b"; c.value = `${c.value}. ${tpl(tr.radonHigh, { p: fmtNumber(hi, h.intl, hi < 1 ? 1 : 0) })}`; }
    add(c);
  }

  // ---- coal mining
  if (rp) {
    // Coal Authority areas cover every coalfield in England and Wales, so "not inside" is a real answer.
    const high = inZone("coal.high_risk");
    const low = inZone("coal.low_risk");
    add({ key: "coal", label: tr.coal, value: high ? tr.coalHigh : low ? tr.coalLow : tr.none, tone: high ? "b" : low ? "m" : "g", src: tr.srcCoal, ask: high || low ? q.coal : undefined });
  } else if (!rp) {
    const c = share("coal", "uk.zone.coal_reporting_share", tr.coalArea, tr.srcCoal, 50, q.coal);
    const hi = val(r.metrics, "uk.zone.coal_high_risk_share");
    if (c && hi != null && hi > 0) { c.tone = "b"; c.value = `${c.value}. ${tpl(tr.coalHighArea, { p: fmtNumber(hi, h.intl, hi < 1 ? 1 : 0) })}`; }
    add(c);
  }

  // ---- ground stability (BGS GeoSure, 5 km hexagons: indicative only)
  if (rp && rp.zones["geo.shrink_swell"] !== undefined) {
    const s = maxRank("geo.shrink_swell");
    add({ key: "clay", label: tr.shrinkSwell, value: tr.level[s] ?? tr.none, tone: s >= 3 ? "b" : s === 2 ? "m" : "g", src: tr.srcGeoSure, ask: s >= 2 ? q.subsidence : undefined });
    const others = ([["geo.landslides", tr.landslides], ["geo.soluble_rocks", tr.solubleRocks], ["geo.compressible_ground", tr.compressible],
      ["geo.collapsible_deposits", tr.collapsible], ["geo.running_sand", tr.runningSand], ["geo.mining_non_coal", tr.nonCoalMining]] as const)
      .map(([z, l]) => [l, maxRank(z)] as const).filter(([, n]) => n >= 2);
    const worst = Math.max(0, ...others.map(([, n]) => n));
    add({
      key: "ground", label: tr.otherGround, tone: worst >= 3 ? "b" : worst === 2 ? "m" : "g", src: tr.srcGeoSure,
      value: others.length ? others.map(([l, n]) => `${l} (${tr.level[n].toLowerCase()})`).join(", ") : tr.lowOnly,
      ask: others.length ? q.ground : undefined,
    });
  } else if (!rp) {
    add(share("clay", "uk.zone.shrink_swell_sig_share", tr.shrinkSwellArea, tr.srcGeoSure, 50, q.subsidence));
    const ids: [string, string][] = [["uk.zone.landslide_mod_share", tr.landslides], ["uk.zone.soluble_rocks_mod_share", tr.solubleRocks],
      ["uk.zone.compressible_mod_share", tr.compressible], ["uk.zone.mining_non_coal_mod_share", tr.nonCoalMining]];
    const found = ids.map(([id, l]) => [l, val(r.metrics, id)] as const).filter(([, v]) => v != null) as [string, number][];
    if (found.length) {
      const hits = found.filter(([, v]) => v > 0);
      const worst = Math.max(0, ...hits.map(([, v]) => v));
      add({
        key: "ground", label: tr.otherGroundArea, tone: !hits.length ? "g" : worst >= 50 ? "b" : "m", src: tr.srcGeoSure,
        value: hits.length ? hits.map(([l, v]) => `${l} ${fmtNumber(v, h.intl, v < 1 ? 1 : 0)}%`).join(", ") : tr.none,
        ask: hits.length ? q.ground : undefined,
      });
    }
  }

  // ---- landfill
  if (rp) {
    const d = rp.landfillHistoricM;
    const near = d != null && d <= 250;
    add({ key: "landfill", label: tr.landfill, value: d == null ? tpl(tr.noneWithin, { d: "500 m" }) : tpl(tr.distance, { d: fmtDistance(d, h.intl) }), tone: near ? "m" : "g", src: tr.srcLandfill, ask: near ? q.landfill : undefined });
    const a = rp.landfillAuthorisedM;
    if (a != null && a <= 1000) add({ key: "landfillOp", label: tr.landfillOperating, value: tpl(tr.distance, { d: fmtDistance(a, h.intl) }), tone: a <= 500 ? "m" : "g", src: tr.srcLandfill, ask: a <= 500 ? q.landfill : undefined });
  } else {
    add(share("landfill", "uk.zone.landfill_historic_250m_share", tr.landfillArea, tr.srcLandfill, 25, q.landfill));
  }

  // ---- coast
  if (rp) {
    const e = inZone("coast.erosion_2055") ? "2055" : inZone("coast.erosion_2105", "coast.ground_instability") ? "2105" : null;
    if (e) add({ key: "coast", label: tr.coast, value: tpl(tr.coastBy, { y: e }), tone: e === "2055" ? "b" : "m", src: tr.srcCoast, ask: q.coast });
  } else {
    const v = val(r.metrics, "uk.zone.coastal_erosion_2105_share");
    if (v != null && v > 0) add({ key: "coast", label: tr.coast, value: pctText(h, v), tone: "m", src: tr.srcCoast, ask: q.coast });
  }

  // ---- pollution incidents recorded nearby
  if (r.incidents && r.incidents.total > 0) {
    const s = r.incidents.serious;
    add({
      key: "incidents", label: tr.incidents, tone: s > 0 ? "m" : "g", src: tr.srcIncidents, ask: s > 0 ? q.landfill : undefined,
      value: tpl(s > 0 ? tr.incidentsSerious : tr.incidentsMinor, { n: fmtNumber(r.incidents.total, h.intl), s: fmtNumber(s, h.intl) }),
    });
  }
  return out;
}

type Group = "water" | "ground" | "land";

/** Where each check sits in the map key, and the symbol it is drawn with. */
const KEY: Record<string, { group: Group; glyph: GlyphKind }> = {
  fz: { group: "water", glyph: "water" }, rs: { group: "water", glyph: "water" }, sw: { group: "water", glyph: "surface" },
  fh: { group: "water", glyph: "history" }, radon: { group: "ground", glyph: "radon" }, coal: { group: "ground", glyph: "coal" },
  clay: { group: "ground", glyph: "clay" }, ground: { group: "ground", glyph: "ground" }, landfill: { group: "land", glyph: "landfill" },
  landfillOp: { group: "land", glyph: "landfill" }, incidents: { group: "land", glyph: "pollution" }, coast: { group: "land", glyph: "coast" },
};
const glyphOf = (key: string): GlyphKind => KEY[key]?.glyph ?? "general";

export function Risk({ h }: { h: H }) {
  const { r, t } = h;
  const tr = t.report.risk;
  const checks = riskChecks(h);
  const clear = checks.filter((c) => c.tone === "g").length;
  const bad = checks.filter((c) => c.tone === "b").length;
  const summary = checks.length
    ? tpl(clear === checks.length ? tr.summaryClear : tr.summary, { clear, n: checks.length, look: checks.length - clear, bad: bad ? tpl(tr.summaryBad, { b: bad }) : "" })
    : tr.summaryNone;
  const groups = (["water", "ground", "land"] as const)
    .map((g) => [g, checks.filter((c) => (KEY[c.key]?.group ?? "land") === g)] as const)
    .filter(([, cs]) => cs.length);
  return (
    <section className="rs" id="report-risk" aria-labelledby="h-risk">
      <div className="rs-head">
        <h2 id="h-risk">{t.report.sections.risk}</h2>
        {topicHref(r.head, "risk") && <Link className="rs-more" href={topicHref(r.head, "risk")!}>{t.report.more.risk} <span aria-hidden="true">→</span></Link>}
      </div>
      <p className="sum">{summary}</p>
      {checks.length > 0 && (
        <>
          <div className="risk-tally" role="img" aria-label={summary}>
            {checks.map((c) => <span key={c.key} className={`t-${c.tone}`} title={`${c.label}: ${tr.verdict[c.tone]}`} />)}
          </div>
          <div className="map-key">
            {groups.map(([g, cs]) => (
              <div key={g} className="key-group">
                <h3>{tr.groups[g]}</h3>
                <ul>
                  {cs.map((c) => (
                    <li key={c.key}>
                      <details className={`key-row tone-${c.tone}`}>
                        <summary>
                          <MapGlyph kind={glyphOf(c.key)} />
                          <span className="k-label">{c.label}</span>
                          <span className="k-value">{c.value}</span>
                          <span className="verdict">{tr.verdict[c.tone]}</span>
                        </summary>
                        <div className="k-more">
                          {c.ask && <p className="k-ask">{c.ask}</p>}
                          <p className="m-src">{c.src}</p>
                        </div>
                      </details>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}
      <p className="m-src" style={{ marginTop: 12 }}>{r.riskPoint ? tr.pointNote : tr.areaNote} {tr.note}</p>
    </section>
  );
}

/** "Before you make an offer": questions generated from the checks that are not clear. */
export function Checklist({ h }: { h: H }) {
  const { r, t } = h;
  const tc = t.report.checklist;
  const seen = new Set<string>();
  const items: ChecklistItem[] = [];
  const push = (text: string, glyph: GlyphKind) => { if (!seen.has(text)) { seen.add(text); items.push({ text, glyph }); } };
  for (const c of riskChecks(h)) if (c.ask) push(c.ask, glyphOf(c.key));
  const planning = r.zones.some((z) => ["planning.conservation_area", "planning.article4"].includes(z.type) && (z.intersects || (z.shareAddresses ?? 0) > 0))
    || (val(r.metrics, "uk.zone.conservation_area_share") ?? 0) > 0 || (val(r.metrics, "uk.zone.article4_share") ?? 0) > 0;
  if (planning) push(tc.ask.planning, "planning");
  if (r.listedCount) push(tc.ask.listed, "listed");
  if (r.tribunals && r.tribunals.total > 0) push(tc.ask.leasehold, "lease");
  const always: ChecklistItem[] = [tc.always.searches, tc.always.survey, tc.always.insurance].map((text) => ({ text }));
  return (
    <section className="rs" id="report-checklist" aria-labelledby="h-checklist">
      <h2 id="h-checklist">{t.report.sections.checklist}</h2>
      <p className="sum">{items.length ? tpl(tc.summary, { n: items.length }) : tc.summaryNone}</p>
      <ChecklistClient
        storageKey={`zc:offer:${r.head.level}:${r.head.slug}`}
        groups={[
          ...(items.length ? [{ title: tc.forHere, items }] : []),
          { title: tc.everywhere, items: always },
        ]}
        doneLabel={tc.done}
      />
      <p className="m-src" style={{ marginTop: 12 }}>{tc.note}</p>
    </section>
  );
}
