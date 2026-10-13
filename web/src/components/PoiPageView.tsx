import Link from "next/link";
import { fmtDate, fmtDistance, fmtNumber } from "@/lib/format";
import type { PoiPage } from "@/server/poi";
import { AreaMap } from "./report/AreaMap";
import { Ad, LineChart, Metric } from "./report/bits";

const ASPECT: Record<string, string> = {
  overall: "Overall effectiveness", quality_of_education: "Quality of education", behaviour_attitudes: "Behaviour and attitudes",
  personal_development: "Personal development", leadership: "Leadership and management", early_years: "Early years", sixth_form: "Sixth form",
  safeguarding: "Safeguarding", achievement: "Achievement", attendance_behaviour: "Attendance and behaviour", curriculum_teaching: "Curriculum and teaching",
  inclusion: "Inclusion", post16: "16 to 19 study",
};

function tone(label: string): string {
  if (/outstanding|exceptional|strong|effective|^yes|met/i.test(label)) return "var(--good)";
  if (/good|secure|expected/i.test(label)) return "var(--water)";
  if (/requires|needs|attention/i.test(label)) return "var(--mid)";
  if (/inadequate|urgent|not met|ineffective/i.test(label)) return "var(--bad)";
  return "var(--ink-2)";
}

export function PoiPageView({ p, kind, intl }: { p: PoiPage; kind: "school" | "station"; intl: string }) {
  const a = p.attrs;
  const current = p.ratings.filter((r) => r.current);
  const latestDate = current[0]?.ratedOn;
  const latest = current.filter((r) => r.ratedOn === latestDate);
  const byMetric = new Map<string, { name: string; pts: { x: string; y: number }[] }>();
  for (const m of p.metrics) {
    const e = byMetric.get(m.id) ?? { name: m.name, pts: [] };
    e.pts.push({ x: m.period, y: m.v });
    byMetric.set(m.id, e);
  }
  const facts: [string, string | undefined][] = kind === "school"
    ? [
        ["Type", a["TypeOfEstablishment (name)"]], ["Phase", a["PhaseOfEducation (name)"]], ["Ages", a.StatutoryLowAge && `${a.StatutoryLowAge} to ${a.StatutoryHighAge}`],
        ["Pupils", a.NumberOfPupils && `${fmtNumber(Number(a.NumberOfPupils), intl)}${a.SchoolCapacity ? ` of ${fmtNumber(Number(a.SchoolCapacity), intl)} places` : ""}`],
        ["Gender", a["Gender (name)"]], ["Religious character", a["ReligiousCharacter (name)"]], ["Admissions", a["AdmissionsPolicy (name)"]],
        ["Free school meals", a.PercentageFSM && `${a.PercentageFSM}%`], ["Trust", a["Trusts (name)"]], ["Local authority", a["LA (name)"]], ["URN", p.externalId],
      ]
    : [["Station code", a.crs], ["Operator region", a.orr_region], ["Locality", a.locality], ["Busiest-station rank", a.usage_rank && `${a.usage_rank} in Great Britain`]];

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link href="/">Home</Link>
        {p.lad && <> › <Link href={`/uk/area/${p.lad.slug}`}>{p.lad.name}</Link></>}
        {p.sectorArea && <> › <Link href={`/uk/sector/${p.sectorArea.slug}`}>{p.sectorArea.code}</Link></>}
        {" › "}{p.name}
      </nav>
      <div className="r-head">
        <div className="r-title">
          <div className={`plate${p.name.length > 14 ? " long" : ""}`}>{p.name}<small>{p.typeName}</small></div>
          <p className="where">{[p.address, p.postcode].filter((x) => x && x !== "-").join(", ")}{p.status !== "open" ? ` (${p.status.replace("_", " ")})` : ""}</p>
          {a.SchoolWebsite && <p><a href={a.SchoolWebsite.startsWith("http") ? a.SchoolWebsite : `https://${a.SchoolWebsite}`} rel="noopener nofollow">School website</a></p>}
          <div className="r-actions">
            {p.postcodeArea && <Link className="btn" href={`/uk/postcode/${p.postcodeArea.slug}`}>Area report for {p.postcodeArea.code}</Link>}
            {p.sectorArea && <Link className="btn" href={`/uk/sector/${p.sectorArea.slug}`}>{p.sectorArea.code} sector</Link>}
          </div>
        </div>
        <AreaMap center={[p.lon, p.lat]} bbox={null} geojson={null} label={p.name} levelForNeighbours="sector" pois={[{ name: p.name, type: p.type, lon: p.lon, lat: p.lat, ofsted: 0 }]} />
      </div>

      <div className="r-body" style={{ gridTemplateColumns: "minmax(0,1fr) 300px" }}>
        <div>
          {kind === "school" && (
            <section className="rs" id="report-ofsted">
              <h2>Ofsted</h2>
              {latest.length ? (
                <>
                  <p className="sum">Latest inspection {fmtDate(latestDate, intl)}{latest[0].scheme === "ofsted_report_card" ? ", under the new report card framework." : "."}</p>
                  <div className="flags">
                    {latest.map((r) => (
                      <div className="flag" key={r.aspect}>
                        <span className="f-k">{ASPECT[r.aspect] ?? r.aspect}</span>
                        <span className="f-v"><span className="dot" style={{ background: tone(r.label) }} />{r.label}</span>
                      </div>
                    ))}
                  </div>
                  {latest[0].url && <p className="m-src" style={{ marginTop: 10 }}><a href={latest[0].url} rel="noopener">Read the Ofsted report</a></p>}
                </>
              ) : <p className="empty-note">No Ofsted inspection on record.</p>}
              {p.ratings.some((r) => !r.current && r.aspect === "overall") && (
                <>
                  <h3 className="sub-h">Earlier inspections</h3>
                  <table className="data"><tbody>
                    {p.ratings.filter((r) => !r.current && r.aspect === "overall").map((r) => <tr key={r.ratedOn}><td>{fmtDate(r.ratedOn, intl)}</td><td>{r.label}</td></tr>)}
                  </tbody></table>
                </>
              )}
            </section>
          )}

          {byMetric.size > 0 && (
            <section className="rs" id="report-results">
              <h2>{kind === "school" ? "Exam results" : "Passenger numbers"}</h2>
              <div className="metrics">
                {[...byMetric.entries()].map(([id, e]) => {
                  const last = e.pts[e.pts.length - 1];
                  return <Metric key={id} name={e.name} value={fmtNumber(last.y, intl, Math.abs(last.y) < 10 ? 2 : 0)} note={e.pts.length > 1 ? `${e.pts.map((x) => `${x.x.slice(0, 4)}: ${fmtNumber(x.y, intl, Math.abs(x.y) < 10 ? 2 : 0)}`).join(" · ")}` : undefined} src={`${kind === "school" ? "DfE school performance tables" : "ORR estimates of station usage"}, ${last.x.slice(0, 4)}`} />;
                })}
              </div>
              {kind === "station" && [...byMetric.values()][0]?.pts.length > 2 && (
                <LineChart series={[{ label: p.name, points: [...byMetric.values()][0].pts }]} format={(v) => fmtNumber(v / 1e6, intl, 1) + "m"} ariaLabel="Station entries and exits per year" height={180} />
              )}
            </section>
          )}

          <section className="rs" id="report-facts">
            <h2>Key facts</h2>
            <table className="data"><tbody>
              {facts.filter(([, v]) => v).map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}
            </tbody></table>
          </section>

          {p.nearby.length > 0 && (
            <section className="rs" id="report-nearby">
              <h2>Nearby {kind === "school" ? "schools" : "stations"}</h2>
              <div className="nearby">
                {p.nearby.map((n) => (
                  <Link key={n.slug} href={`/uk/${kind}/${n.slug}`} style={{ textDecoration: "none" }}>
                    <span style={{ fontWeight: 700, display: "block" }}>{n.name}</span>
                    <span>{fmtDistance(n.dist, intl)}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}
          <p className="m-src">{kind === "school" ? "DfE Get Information about Schools, Ofsted management information, DfE school performance tables. Contains public sector information licensed under the Open Government Licence v3.0." : "DfT NaPTAN, ORR estimates of station usage. Contains public sector information licensed under the Open Government Licence v3.0."}</p>
        </div>
        <aside className="rail" aria-label="Sponsored"><Ad kind="side" label="300×600, sticky" /></aside>
      </div>
    </>
  );
}
