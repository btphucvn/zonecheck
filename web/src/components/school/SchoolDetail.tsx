import { fmtNumber } from "@/lib/format";
import type { PoiPage } from "@/server/poi";
import { LineChart } from "../report/bits";

// School page sections beyond Ofsted: pupils, exams, subjects, admissions, class sizes and destinations,
// each figure next to the local authority and England averages (DfE, same year).

type Num = { v: number; period: string } | null;

const ETHNIC_LABEL: Record<string, string> = {
  white_british: "White British", irish: "Irish", traveller_irish: "Traveller of Irish heritage", other_white: "Other White",
  gypsy_roma: "Gypsy or Roma", white_black_caribbean: "White and Black Caribbean", white_black_african: "White and Black African",
  white_asian: "White and Asian", other_mixed: "Other mixed", indian: "Indian", pakistani: "Pakistani", bangladeshi: "Bangladeshi",
  other_asian: "Other Asian", caribbean: "Caribbean", african: "African", other_black: "Other Black", chinese: "Chinese",
  other: "Other ethnic group", unclassified: "Unclassified",
};
const KS4_DEST: [string, string][] = [
  ["overall", "Staying in education or employment"], ["education", "Education (any)"], ["school_sixth_form", "School sixth form"],
  ["sixth_form_college", "Sixth form college"], ["fe", "Further education college"], ["other_education", "Other education"],
  ["apprenticeship", "Apprenticeship"], ["employment", "Employment"], ["not_sustained", "Not sustained"], ["unknown", "Destination unknown"],
];
const KS5_DEST: [string, string][] = [
  ["overall", "Staying in education or employment"], ["higher_education", "Higher education (degree level)"], ["fe", "Further education"],
  ["other_education", "Other education"], ["apprenticeship", "Apprenticeship"], ["employment", "Employment"],
  ["not_sustained", "Not sustained"], ["unknown", "Destination unknown"],
];
const HE: [string, string][] = [
  ["progressed", "Progressed to degree-level study or training"], ["higher_education", "Degree-level study"],
  ["top_third_he", "Top third of universities"], ["apprenticeship", "Higher or degree apprenticeship"], ["higher_technical", "Higher technical (level 4/5)"],
];
const YEAR_ORDER = ["N1", "N2", "R", ...Array.from({ length: 14 }, (_, i) => `Y${i + 1}`)];
const YEAR_LABEL = (k: string) => (k === "R" ? "Reception" : k.startsWith("N") ? `Nursery ${k.slice(1)}` : `Year ${k.slice(1)}`);
const yearOf = (period: string) => { const y = Number(period.slice(0, 4)); return `${y - 1}/${String(y).slice(2)}`; };

export function SchoolDetail({ p, intl }: { p: PoiPage; intl: string }) {
  const latest = (id: string): Num => {
    const pts = p.metrics.filter((m) => m.id === id);
    return pts.length ? { v: pts[pts.length - 1].v, period: pts[pts.length - 1].period } : null;
  };
  const series = (id: string) => p.metrics.filter((m) => m.id === id).map((m) => ({ x: m.period, y: m.v }));
  const b = (id: string) => p.bench[id];
  const fmt = (v: number | null | undefined, kind: "pct" | "num" | "num1" | "num2") =>
    v == null ? "–" : kind === "pct" ? `${fmtNumber(v, intl, v < 10 ? 1 : 0)}%` : fmtNumber(v, intl, kind === "num" ? 0 : kind === "num1" ? 1 : 2);
  const la = p.attrs["LA (name)"] ?? "Local authority";

  /** Table of measures: school against LA and England. Rows without a school value are dropped. */
  const compare = ({ rows, caption }: { rows: { id: string; label: string; kind: "pct" | "num" | "num1" | "num2"; grade?: string }[]; caption: string }) => {
    const shown = rows.map((r) => ({ ...r, here: latest(r.id) })).filter((r) => r.here);
    if (!shown.length) return null;
    const period = shown[0].here!.period;
    const grade = (id: string | undefined, who: "here" | "la" | "eng") => {
      if (!id) return "";
      const g = who === "here" ? (p.json[id]?.j as { grade?: string } | undefined)?.grade : ((who === "la" ? b(id)?.laJ : b(id)?.engJ) as { grade?: string } | undefined)?.grade;
      return g ? `, ${g}` : "";
    };
    return (
      <table className="data cmp">
        <caption>{caption}, {yearOf(period)}</caption>
        <thead><tr><th scope="col">Measure</th><th scope="col">This school</th><th scope="col">{la}</th><th scope="col">England</th></tr></thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id}>
              <th scope="row">{r.label}</th>
              <td><b>{fmt(r.here!.v, r.kind)}{grade(r.grade, "here")}</b></td>
              <td>{fmt(b(r.id)?.la, r.kind)}{grade(r.grade, "la")}</td>
              <td>{fmt(b(r.id)?.eng, r.kind)}{grade(r.grade, "eng")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const head = latest("uk.pupils.headcount");
  const cap = Number(p.attrs.SchoolCapacity) || null;
  const eth = p.json["uk.pupils.ethnicity"]?.j as Record<string, number | null> | undefined;
  const years = p.json["uk.pupils.year_groups"]?.j as Record<string, { f: number; m: number }> | undefined;
  const subjects = p.json["uk.ks4.subject_entries"]?.j as { q: string; s: string; n: number; g: Record<string, number> }[] | undefined;
  const dest = (id: string) => ({ here: p.json[id]?.j as Record<string, number | null> | undefined, period: p.json[id]?.period, laJ: b(id)?.laJ as Record<string, number | null> | undefined, engJ: b(id)?.engJ as Record<string, number | null> | undefined });
  const k4 = dest("uk.dest.ks4"), k5 = dest("uk.dest.ks5"), he = dest("uk.dest.ks5_he");
  const places = latest("uk.school.places_offered");
  const first = latest("uk.school.first_pref_apps");
  const has = { ks2: !!latest("uk.ks2.rwm_expected_pct"), ks4: !!latest("uk.ks4.attainment8"), ks5: !!latest("uk.ks5.alevel_aps") };
  const sections = [
    ["pupils", "Pupils", !!head || !!latest("uk.pupils.sen_pct")],
    ["exams", "Exams", has.ks2 || has.ks4 || has.ks5],
    ["subjects", "Subjects", !!subjects?.length],
    ["admissions", "Admissions", !!places],
    ["classes", "Class sizes", !!latest("uk.school.class_size_avg") || !!years],
    ["destinations", "Destinations", !!k4.here || !!k5.here],
  ].filter((x) => x[2]) as [string, string, boolean][];
  if (!sections.length) return null;

  const destTable = ({ d, rows, caption }: { d: ReturnType<typeof dest>; rows: [string, string][]; caption: string }) => d.here ? (
    <table className="data cmp">
      <caption>{caption}{d.period ? `, ${yearOf(d.period)} release` : ""}{d.here.cohort ? ` (${fmtNumber(d.here.cohort, intl)} pupils)` : ""}</caption>
      <thead><tr><th scope="col">Destination</th><th scope="col">School</th><th scope="col">{la}</th><th scope="col">England</th></tr></thead>
      <tbody>
        {rows.filter(([k]) => d.here![k] != null).map(([k, label]) => (
          <tr key={k}><th scope="row">{label}</th><td><b>{fmt(d.here![k], "pct")}</b></td><td>{fmt(d.laJ?.[k], "pct")}</td><td>{fmt(d.engJ?.[k], "pct")}</td></tr>
        ))}
      </tbody>
    </table>
  ) : null;

  return (
    <>
      <nav className="tp-subtabs school-nav" aria-label="School sections">
        <a href="#report-ofsted">General</a>
        {sections.map(([id, label]) => <a key={id} href={`#school-${id}`}>{label}</a>)}
      </nav>

      {sections.some((s) => s[0] === "pupils") && (
        <section className="rs" id="school-pupils">
          <h2>Pupils</h2>
          {head && <p className="sum">{fmtNumber(head.v, intl)} pupils{cap ? ` (${Math.round((head.v / cap) * 100)}% of ${fmtNumber(cap, intl)} places)` : ""} in the {yearOf(head.period)} school census.</p>}
          {compare({ caption: "Pupil characteristics", rows: [
            { id: "uk.pupils.girls_pct", label: "Girls", kind: "pct" },
            { id: "uk.pupils.eal_pct", label: "First language not English", kind: "pct" },
            { id: "uk.pupils.fsm_pct", label: "Eligible for free school meals", kind: "pct" },
            { id: "uk.pupils.sen_pct", label: "Special educational needs (all)", kind: "pct" },
            { id: "uk.pupils.sen_ehcp_pct", label: "With an EHC plan", kind: "pct" },
            { id: "uk.pupils.persistent_absence_pct", label: "Persistently absent (10%+ of sessions)", kind: "pct" },
            { id: "uk.pupils.absence_pct", label: "Overall absence (% of sessions)", kind: "pct" },
            { id: "uk.pupils.young_carer_pct", label: "Young carers", kind: "pct" },
          ] })}
          {eth && (
            <>
              <h3 className="sub-h">Pupil ethnicity</h3>
              <table className="data"><tbody>
                {Object.entries(eth).filter(([, v]) => v != null && v > 0).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0)).map(([k, v]) => (
                  <tr key={k}><th scope="row">{ETHNIC_LABEL[k] ?? k}</th><td>{fmt(v, "pct")}</td></tr>
                ))}
              </tbody></table>
            </>
          )}
          <p className="m-src">DfE Schools, pupils and their characteristics; Special educational needs in England; Pupil absence in schools.</p>
        </section>
      )}

      {sections.some((s) => s[0] === "exams") && (
        <section className="rs" id="school-exams">
          <h2>Exam results</h2>
          {has.ks2 && compare({ caption: "Key stage 2 (end of primary)", rows: [
            { id: "uk.ks2.rwm_expected_pct", label: "Expected standard in reading, writing and maths", kind: "pct" },
            { id: "uk.ks2.rwm_higher_pct", label: "Higher standard in reading, writing and maths", kind: "pct" },
            { id: "uk.ks2.reading_score", label: "Average scaled score, reading", kind: "num" },
            { id: "uk.ks2.maths_score", label: "Average scaled score, maths", kind: "num" },
          ] })}
          {has.ks4 && compare({ caption: "GCSE (key stage 4)", rows: [
            { id: "uk.ks4.attainment8", label: "Attainment 8 score", kind: "num1" },
            { id: "uk.ks4.progress8", label: "Progress 8 score", kind: "num2" },
            { id: "uk.ks4.eng_maths_5plus_pct", label: "Grade 5+ in English and maths", kind: "pct" },
            { id: "uk.ks4.eng_maths_4plus_pct", label: "Grade 4+ in English and maths", kind: "pct" },
            { id: "uk.ks4.ebacc_entry_pct", label: "Entering the EBacc", kind: "pct" },
            { id: "uk.ks4.ebacc_aps", label: "EBacc average point score", kind: "num2" },
          ] })}
          {has.ks5 && compare({ caption: "A levels (16 to 18)", rows: [
            { id: "uk.ks5.alevel_aps", label: "Average point score per A level entry", kind: "num2", grade: "uk.ks5.alevel_grade" },
            { id: "uk.ks5.best3_aps", label: "Best 3 A levels, average points", kind: "num2", grade: "uk.ks5.best3_grade" },
            { id: "uk.ks5.aab_pct", label: "AAB or better (2+ facilitating subjects)", kind: "pct" },
          ] })}
          {has.ks4 && series("uk.ks4.attainment8").length > 1 && (
            <LineChart series={[{ label: "Attainment 8", points: series("uk.ks4.attainment8") }]} format={(v) => fmtNumber(v, intl, 1)} ariaLabel="Attainment 8 by year" height={160} />
          )}
          {!has.ks4 && has.ks2 && series("uk.ks2.rwm_expected_pct").length > 1 && (
            <LineChart series={[{ label: "Expected standard (%)", points: series("uk.ks2.rwm_expected_pct") }]} format={(v) => `${Math.round(v)}%`} ariaLabel="Key stage 2 expected standard by year" height={160} />
          )}
          <p className="m-src">DfE school and college performance tables. Averages are for state-funded schools.</p>
        </section>
      )}

      {subjects?.length ? (
        <section className="rs" id="school-subjects">
          <h2>GCSE and other key stage 4 subjects</h2>
          <p className="sum">{subjects.length} subjects and qualifications taken by pupils at the end of key stage 4.</p>
          <table className="data">
            <thead><tr><th scope="col">Subject</th><th scope="col">Qualification</th><th scope="col">Entries</th></tr></thead>
            <tbody>{subjects.slice(0, 12).map((x) => <tr key={x.q + x.s}><th scope="row">{x.s}</th><td>{x.q}</td><td>{fmtNumber(x.n, intl)}</td></tr>)}</tbody>
          </table>
          {subjects.length > 12 && (
            <details className="more"><summary>Show {subjects.length - 12} more</summary>
              <table className="data"><tbody>{subjects.slice(12).map((x) => <tr key={x.q + x.s}><th scope="row">{x.s}</th><td>{x.q}</td><td>{fmtNumber(x.n, intl)}</td></tr>)}</tbody></table>
            </details>
          )}
          <p className="m-src">DfE key stage 4 subject entries and grades.</p>
        </section>
      ) : null}

      {places && (
        <section className="rs" id="school-admissions">
          <h2>Admissions</h2>
          <p className="sum">
            {fmtNumber(places.v, intl)} places offered for entry in September {places.period.slice(0, 4)}.{" "}
            {first ? (first.v > places.v
              ? <>Oversubscribed: {fmtNumber(first.v, intl)} families put it first, more than the places available.</>
              : <>Not oversubscribed: fewer first-preference applications ({fmtNumber(first.v, intl)}) than places.</>) : null}
          </p>
          <table className="data cmp">
            <thead><tr><th scope="col">Preference</th><th scope="col">Applications</th><th scope="col">Offers</th></tr></thead>
            <tbody>
              {([["1st preference", "first"], ["2nd preference", "second"], ["3rd preference", "third"]] as const).map(([label, k]) => (
                <tr key={k}><th scope="row">{label}</th><td>{fmt(latest(`uk.school.${k}_pref_apps`)?.v, "num")}</td><td>{fmt(latest(`uk.school.${k}_pref_offers`)?.v, "num")}</td></tr>
              ))}
              <tr><th scope="row">From another local authority</th><td>{fmt(latest("uk.school.other_la_apps")?.v, "num")}</td><td>{fmt(latest("uk.school.other_la_offers")?.v, "num")}</td></tr>
            </tbody>
          </table>
          <p className="m-src">DfE primary and secondary school applications and offers (national offer day; in-year applications excluded).</p>
        </section>
      )}

      {sections.some((s) => s[0] === "classes") && (
        <section className="rs" id="school-classes">
          <h2>Class sizes</h2>
          {compare({ caption: "Average class size (one teacher)", rows: [
            { id: "uk.school.class_size_avg", label: "All one-teacher classes", kind: "num1" },
            { id: "uk.school.class_size_ks1", label: "Key stage 1 (years 1–2)", kind: "num1" },
            { id: "uk.school.class_size_ks2", label: "Key stage 2 (years 3–6)", kind: "num1" },
          ] })}
          {years && (
            <table className="data cmp">
              <caption>Pupils by year group</caption>
              <thead><tr><th scope="col">Year</th><th scope="col">Total</th><th scope="col">Boys</th><th scope="col">Girls</th></tr></thead>
              <tbody>
                {YEAR_ORDER.filter((k) => years[k]).map((k) => (
                  <tr key={k}><th scope="row">{YEAR_LABEL(k)}</th><td>{fmtNumber(years[k].f + years[k].m, intl)}</td><td>{fmtNumber(years[k].m, intl)}</td><td>{fmtNumber(years[k].f, intl)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="m-src">DfE Schools, pupils and their characteristics (school census).</p>
        </section>
      )}

      {sections.some((s) => s[0] === "destinations") && (
        <section className="rs" id="school-destinations">
          <h2>Where pupils go next</h2>
          <p className="sum">Share of pupils in a sustained destination for at least two terms after leaving. The latest release covers pupils who left two years earlier.</p>
          {destTable({ d: k4, rows: KS4_DEST, caption: "After GCSEs" })}
          {destTable({ d: k5, rows: KS5_DEST, caption: "After 16 to 18 study" })}
          {destTable({ d: he, rows: HE, caption: "Progression to higher education or training" })}
          <p className="m-src">DfE key stage 4 and 16 to 18 destination measures.</p>
        </section>
      )}
    </>
  );
}
