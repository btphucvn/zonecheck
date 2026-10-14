"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtDistance, fmtNumber } from "@/lib/format";
import type { SchoolRow } from "@/server/topic";

// Schools within 3 km with filters (phase, Ofsted, religious character, gender, funding, oversubscribed) and pages
// of 20, nearest first. Everything filters in the browser: the list is at most 60 schools.

const PHASE: Record<string, string> = { "school.primary": "Primary", "school.secondary": "Secondary", "school.all_through": "All-through", "school.special": "Special", "school.post16": "16 plus" };
const PAGE = 20;
type F = { phase: string; ofsted: string; religion: string; gender: string; funding: string; over: string };
const ALL: F = { phase: "", ofsted: "", religion: "", gender: "", funding: "", over: "" };

export function SchoolTable({ rows, intl }: { rows: SchoolRow[]; intl: string }) {
  const [f, setF] = useState<F>(ALL);
  const [page, setPage] = useState(0);
  const shown = useMemo(() => rows.filter((s) =>
    (!f.phase || s.type === f.phase || (f.phase === "school.primary" && s.type === "school.all_through") || (f.phase === "school.secondary" && s.type === "school.all_through"))
    && (!f.ofsted || (f.ofsted === "none" ? !s.rating?.rank : String(s.rating?.rank ?? "") === f.ofsted))
    && (!f.religion || (f.religion === "none" ? !s.religion : !!s.religion))
    && (!f.gender || (f.gender === "Mixed" ? !s.gender || s.gender === "Mixed" : s.gender === f.gender))
    && (!f.funding || s.funding === f.funding)
    && (!f.over || (f.over === "yes" ? s.oversubscribed === true : s.oversubscribed === false))), [rows, f]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const cur = Math.min(page, pages - 1);
  const set = (k: keyof F) => (e: React.ChangeEvent<HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(0); };
  const sel = (k: keyof F, label: string, opts: [string, string][]) => (
    <label>{label}<select value={f[k]} onChange={set(k)}><option value="">All</option>{opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
  );
  const ofsted = (x: SchoolRow["rating"]) => !x ? <span className="m-src">Not rated</span> : <span className={`ofsted r${x.rank ?? 0}`}>{x.label}</span>;
  return (
    <>
      <div className="school-filters">
        {sel("phase", "Phase", [["school.primary", "Primary"], ["school.secondary", "Secondary"], ["school.post16", "16 plus"], ["school.special", "Special"]])}
        {sel("ofsted", "Ofsted", [["1", "Outstanding"], ["2", "Good"], ["3", "Requires improvement"], ["4", "Inadequate"], ["none", "Not rated or report card"]])}
        {sel("religion", "Religious character", [["none", "None"], ["faith", "Faith school"]])}
        {sel("gender", "Gender", [["Mixed", "Mixed"], ["Boys", "Boys"], ["Girls", "Girls"]])}
        {sel("funding", "Funding", [["State-funded", "State-funded"], ["Independent", "Independent"]])}
        {sel("over", "Admissions", [["yes", "Oversubscribed"], ["no", "Not oversubscribed"]])}
        {JSON.stringify(f) !== JSON.stringify(ALL) && <button type="button" className="btn" onClick={() => { setF(ALL); setPage(0); }}>Clear</button>}
      </div>
      <p className="tp-note">{shown.length} of {rows.length} schools{pages > 1 ? `, page ${cur + 1} of ${pages}` : ""}.</p>
      <div className="scroll-x">
        <table className="data tp-schools">
          <thead><tr><th>School</th><th>Ofsted</th><th className="r">Results</th><th className="r">Offers</th><th className="r">Pupils</th><th className="r">FSM</th><th className="r">Distance</th></tr></thead>
          <tbody>
            {shown.slice(cur * PAGE, cur * PAGE + PAGE).map((s) => (
              <tr key={s.id}>
                <td>
                  {s.slug ? <Link href={`/uk/school/${s.slug}`}>{s.name}</Link> : s.name}
                  <span className="m-src">{[PHASE[s.type] ?? s.type, s.ages ? `ages ${s.ages}` : null, s.kind, s.gender && s.gender !== "Mixed" ? s.gender : null, s.religion, s.admissions === "Selective" ? "Selective" : null, s.oversubscribed ? "Oversubscribed" : null].filter(Boolean).join(", ")}</span>
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
      {pages > 1 && (
        <nav className="school-pages" aria-label="Pages">
          {Array.from({ length: pages }, (_, i) => <button key={i} type="button" aria-current={i === cur ? "page" : undefined} className={i === cur ? "on" : undefined} onClick={() => setPage(i)}>{i + 1}</button>)}
        </nav>
      )}
    </>
  );
}
