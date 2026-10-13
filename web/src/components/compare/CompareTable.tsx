"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { compareHref } from "./CompareTray";
import { useApp } from "../Providers";
import { PersonaChips } from "../report/ScorePanel";

export interface CmpCol { key: string; title: string; sub: string; href: string; cats: Record<string, number | null> }
export interface CmpRow { label: string; values: (number | null)[]; display: string[]; better?: "hi" | "lo" }

function score(cats: Record<string, number | null>, w: Record<string, number>) {
  let s = 0, t = 0;
  for (const [k, v] of Object.entries(cats)) if (v != null && w[k]) { s += v * w[k]; t += w[k]; }
  return t ? Math.round(s / t) : null;
}

export function CompareTable({ cols, rows, catLabels, personas, sub, scoreLabel, whoLabel, removeLabel }: {
  cols: CmpCol[];
  rows: CmpRow[];
  catLabels: Record<string, string>;
  personas: { code: string; label: string; plural: string; weights: Record<string, number> }[];
  sub: string;
  scoreLabel: string;
  whoLabel: string;
  removeLabel: string;
}) {
  const { persona, removeCompare } = useApp();
  const router = useRouter();
  const remove = (key: string) => {
    removeCompare(key);
    router.push(compareHref(cols.filter((c) => c.key !== key).map((c) => ({ level: c.key.split(":")[0], slug: c.key.split(":")[1] }))));
  };
  const p = personas.find((x) => x.code === persona) ?? personas[0];
  const scoreRow: CmpRow = { label: scoreLabel, values: cols.map((c) => score(c.cats, p.weights)), display: [], better: "hi" };
  scoreRow.display = scoreRow.values.map((v) => (v == null ? "–" : String(v)));
  const catRows: CmpRow[] = Object.keys(catLabels).map((k) => {
    const values = cols.map((c) => (c.cats[k] == null ? null : Math.round(c.cats[k]!)));
    return { label: catLabels[k], values, display: values.map((v) => (v == null ? "–" : String(v))), better: "hi" };
  });
  const best = (r: CmpRow) => {
    const vs = r.values.filter((v): v is number => v != null);
    if (!r.better || vs.length < 2) return -1;
    const target = r.better === "hi" ? Math.max(...vs) : Math.min(...vs);
    return r.values.indexOf(target);
  };
  const row = (r: CmpRow, cls?: string) => {
    const b = best(r);
    return (
      <tr key={r.label} className={cls}>
        <th scope="row">{r.label}</th>
        {r.display.map((d, i) => <td key={i} className={i === b ? "best" : undefined}>{d}</td>)}
      </tr>
    );
  };
  return (
    <>
      <p className="m-src" style={{ fontSize: 15, marginBottom: 12 }}>{sub.replace("{persona}", p.plural)}</p>
      <PersonaChips personas={personas} label={whoLabel} />
      <div className="cmp-wrap">
        <table className="cmp">
          <thead>
            <tr>
              <th />
              {cols.map((c) => (
                <th key={c.key} scope="col">
                  <Link href={c.href} style={{ color: "inherit" }}>{c.title}</Link>
                  <small>{c.sub}</small>
                  <small><button type="button" className="theme-btn" style={{ marginTop: 6 }} onClick={() => remove(c.key)}>{removeLabel.replace("{name}", c.title)}</button></small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {row(scoreRow, "score")}
            {rows.map((r) => row(r))}
            {catRows.map((r) => row(r))}
          </tbody>
        </table>
      </div>
    </>
  );
}
