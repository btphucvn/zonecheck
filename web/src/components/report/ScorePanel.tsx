"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../Providers";
import { Strip } from "./bits";

export interface ScoreCat { code: string; label: string; section: string; score: number | null; plus: string; minus: string }
export interface ScorePersona { code: string; label: string; plural: string; weights: Record<string, number> }

export function PersonaChips({ personas, label }: { personas: { code: string; label: string }[]; label: string }) {
  const { persona, setPersona } = useApp();
  return (
    <div className="persona-tabs chips" role="group" aria-label={label}>
      {personas.map((p) => (
        <button key={p.code} type="button" className="chip" aria-pressed={p.code === persona} onClick={() => setPersona(p.code)}>{p.label}</button>
      ))}
    </div>
  );
}

function overall(cats: ScoreCat[], w: Record<string, number>): number | null {
  let s = 0, t = 0;
  for (const c of cats) {
    const wt = w[c.code] ?? 0;
    if (c.score == null || !wt) continue;
    s += c.score * wt;
    t += wt;
  }
  return t ? Math.round(s / t) : null;
}

export function ScorePanel({ cats, personas, t }: {
  cats: ScoreCat[];
  personas: ScorePersona[];
  t: {
    whoLabel: string; outOf: string; bands: string[]; desc: string; plusTitle: string; minusTitle: string; nonePlus: string;
    noneMinus: string; weight: string; notCounted: string; noData: string; tweak: string; reset: string; method: string; methodLink: string;
  };
}) {
  const { persona } = useApp();
  const p = personas.find((x) => x.code === persona) ?? personas[0];
  const [weights, setWeights] = useState<Record<string, number>>(p.weights);
  const [shown, setShown] = useState<number | null>(null);
  const shownRef = useRef<number | null>(null);

  // A persona switch resets the sliders to that persona's defaults.
  useEffect(() => { setWeights(p.weights); }, [p]); // eslint-disable-line react-hooks/set-state-in-effect

  const score = useMemo(() => overall(cats, weights), [cats, weights]);

  // The one orchestrated motion: the score counts to its new value.
  useEffect(() => {
    if (score == null) return;
    const from = shownRef.current ?? 0;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || from === score) {
      shownRef.current = score;
      setShown(score);  
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 500);
      const v = Math.round(from + (score - from) * (1 - Math.pow(1 - k, 3)));
      shownRef.current = v;
      setShown(v);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [score]);

  const active = cats.filter((c) => c.score != null && (weights[c.code] ?? 0) > 0);
  const plus = [...active].filter((c) => c.score! >= 60).sort((a, b) => (b.score! - 50) * weights[b.code] - (a.score! - 50) * weights[a.code]).slice(0, 3);
  const minus = [...active].filter((c) => c.score! <= 40).sort((a, b) => (50 - b.score!) * weights[b.code] - (50 - a.score!) * weights[a.code]).slice(0, 3);
  const band = score == null ? "" : t.bands[score >= 75 ? 3 : score >= 60 ? 2 : score >= 45 ? 1 : 0];
  const withData = cats.filter((c) => c.score != null).length;

  return (
    <div className="score-panel" id="score">
      <h2 className="sr">Area score</h2>
      <PersonaChips personas={personas} label={t.whoLabel} />
      <div className="score-top">
        <div>
          <div className="score-num" aria-live="polite">{shown ?? "–"}<span>{t.outOf}</span></div>
          <p className="score-desc">{t.desc.replace("{band}", band).replace("{persona}", p.plural).replace("{n}", String(withData))}</p>
        </div>
        <div className="verdict">
          <div className="plus">
            <h3>{t.plusTitle}</h3>
            <ul>{plus.length ? plus.map((c) => <li key={c.code}><a href={`#report-${c.section}`}>{c.plus}</a></li>) : <li className="none">{t.nonePlus}</li>}</ul>
          </div>
          <div className="minus">
            <h3>{t.minusTitle}</h3>
            <ul>{minus.length ? minus.map((c) => <li key={c.code}><a href={`#report-${c.section}`}>{c.minus}</a></li>) : <li className="none">{t.noneMinus}</li>}</ul>
          </div>
        </div>
      </div>
      <div className="groups">
        {cats.map((c) => {
          const w = weights[c.code] ?? 0;
          return (
            <div key={c.code} className={`grp${w && c.score != null ? "" : " zero"}`}>
              <span className="g-name">{c.label}</span>
              <span className="g-w">{c.score == null ? t.noData : w ? t.weight.replace("{w}", String(w)) : t.notCounted}</span>
              <Strip p={c.score} label={c.score == null ? undefined : `${c.label}: ${Math.round(c.score)} out of 100`} />
            </div>
          );
        })}
      </div>
      <details className="weights">
        <summary>{t.tweak}</summary>
        <div className="sliders">
          {cats.map((c) => (
            <label key={c.code}>
              <span>{c.label}</span>
              <input
                type="range" min={0} max={5} step={0.5} value={weights[c.code] ?? 0} disabled={c.score == null}
                onChange={(e) => setWeights({ ...weights, [c.code]: Number(e.target.value) })}
                aria-label={`${c.label} weight`}
              />
              <b className="num">{weights[c.code] ?? 0}</b>
            </label>
          ))}
        </div>
        <p className="missing">
          <button type="button" className="theme-btn" onClick={() => setWeights(p.weights)}>{t.reset.replace("{persona}", p.label)}</button>{" "}
          {t.method} <Link href="/methodology">{t.methodLink}</Link>
        </p>
      </details>
    </div>
  );
}
