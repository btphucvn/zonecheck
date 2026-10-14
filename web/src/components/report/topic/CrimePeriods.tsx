"use client";

import { useState } from "react";

// Crime by type over the last 1, 3, 6 or 12 months. Counts are what police recorded in the window;
// rates are scaled to a year per 1,000 residents so every window reads on the same scale as the
// 12-month figures elsewhere on the page.

type Counts = Record<string, number>;
export interface PeriodData { m1: Counts; m3: Counts; m6: Counts; m12: Counts; pop: number; ladM: Record<"m1" | "m3" | "m6" | "m12", Counts> | null; ladPop: number | null }

const WINDOWS = [["m1", "1 month", 1], ["m3", "3 months", 3], ["m6", "6 months", 6], ["m12", "1 year", 12]] as const;

export function CrimePeriods({ data, lastLabel, ladName }: { data: PeriodData; lastLabel: string; ladName: string | null }) {
  const [w, setW] = useState<(typeof WINDOWS)[number][0]>("m12");
  const months = WINDOWS.find((x) => x[0] === w)![2];
  const here = data[w];
  const lad = data.ladM?.[w] ?? null;
  const types = Object.keys(data.m12).sort((a, b) => (here[b] ?? 0) - (here[a] ?? 0));
  const rate = (n: number, pop: number) => ((n * 12) / months / pop) * 1000;
  const f1 = (x: number) => x.toLocaleString("en-GB", { maximumFractionDigits: x < 10 ? 1 : 0 });
  const total = types.filter((t) => t !== "Anti-social behaviour").reduce((s, t) => s + (here[t] ?? 0), 0);
  return (
    <div className="crime-periods">
      <div className="seg" role="radiogroup" aria-label="Time period">
        {WINDOWS.map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={w === k} className={w === k ? "on" : undefined} onClick={() => setW(k)}>{label}</button>
        ))}
      </div>
      <p className="tp-note">{Math.round(total).toLocaleString("en-GB")} crimes (excluding anti-social behaviour) in the {months === 1 ? "month" : `${months} months`} to {lastLabel}. Rates are per 1,000 residents a year.</p>
      <table className="data cmp">
        <thead><tr><th scope="col">Crime type</th><th scope="col">Crimes</th><th scope="col">Rate</th>{lad && data.ladPop ? <th scope="col">{ladName ?? "Borough"} rate</th> : null}</tr></thead>
        <tbody>
          {types.map((t) => (
            <tr key={t}>
              <th scope="row">{t}</th>
              <td>{f1(here[t] ?? 0)}</td>
              <td><b>{f1(rate(here[t] ?? 0, data.pop))}</b></td>
              {lad && data.ladPop ? <td>{f1(rate(lad[t] ?? 0, data.ladPop))}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
