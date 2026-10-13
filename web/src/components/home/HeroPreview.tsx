"use client";

import Link from "next/link";
import { useApp } from "../Providers";
import { Strip } from "../report/bits";

export interface HeroSample {
  href: string;
  plate: string;
  place: string;
  where: string;
  cats: { code: string; label: string; score: number | null }[];
}

/** A real area card in the hero: the score re-weights as the visitor picks who's moving. */
export function HeroPreview({ sample, personas, t }: {
  sample: HeroSample;
  personas: { code: string; plural: string; weights: Record<string, number> }[];
  t: { kicker: string; outOf: string; bands: string[]; forWho: string; open: string };
}) {
  const { persona } = useApp();
  const p = personas.find((x) => x.code === persona) ?? personas[0];
  let s = 0, w = 0;
  for (const c of sample.cats) if (c.score != null && p.weights[c.code]) { s += c.score * p.weights[c.code]; w += p.weights[c.code]; }
  const score = w ? Math.round(s / w) : null;
  const band = score == null ? "" : t.bands[score >= 75 ? 3 : score >= 60 ? 2 : score >= 45 ? 1 : 0];
  const cats = [...sample.cats].sort((a, b) => (p.weights[b.code] ?? 0) - (p.weights[a.code] ?? 0));
  return (
    <Link href={sample.href} className="hero-card" aria-label={`${sample.plate}, ${sample.place}: ${t.open}`}>
      <div className="hc-kicker">{t.kicker}</div>
      <div className="hc-head">
        <div>
          <div className="hc-plate">{sample.plate}</div>
          <div className="hc-place">{sample.place}<small>{sample.where}</small></div>
        </div>
        <div className="hc-score">
          <span className="num" aria-live="polite">{score ?? "–"}</span><small>{t.outOf}</small>
        </div>
      </div>
      <div className="hc-band">{band} {t.forWho.replace("{persona}", p.plural)}</div>
      <div className="hc-cats">
        {cats.map((c) => (
          <div key={c.code} className="hc-cat" data-weight={p.weights[c.code] ? "on" : "off"}>
            <span className="hc-name">{c.label}</span>
            <Strip p={c.score} />
            <span className="num">{c.score == null ? "–" : Math.round(c.score)}</span>
          </div>
        ))}
      </div>
      <div className="hc-open">{t.open} <span aria-hidden="true">→</span></div>
    </Link>
  );
}
