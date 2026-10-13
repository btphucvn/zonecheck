"use client";

import Link from "next/link";
import { useApp } from "../Providers";
import { Strip } from "../report/bits";

export interface PopularArea {
  href: string;
  title: string;
  sub: string;
  meta: string;
  cats: Record<string, number | null>;
}

function score(cats: Record<string, number | null>, w: Record<string, number>) {
  let s = 0, t = 0;
  for (const [k, v] of Object.entries(cats)) if (v != null && w[k]) { s += v * w[k]; t += w[k]; }
  return t ? Math.round(s / t) : null;
}

export function PopularAreas({ areas, personas, template }: {
  areas: PopularArea[];
  personas: { code: string; plural: string; weights: Record<string, number> }[];
  template: string;
}) {
  const { persona } = useApp();
  const p = personas.find((x) => x.code === persona) ?? personas[0];
  const list = areas.map((a) => ({ a, s: score(a.cats, p.weights) })).sort((x, y) => (y.s ?? -1) - (x.s ?? -1));
  return (
    <>
      <p className="sub">{template.replace("{persona}", p.plural)}</p>
      <div className="areas">
        {list.map(({ a, s }) => (
          <Link key={a.href} className="area-card" href={a.href}>
            <span style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
              <span><span className="name">{a.title}</span><br /><span className="meta">{a.sub}</span></span>
              <span className="num" style={{ fontSize: 30, fontWeight: 800 }}>{s ?? "–"}</span>
            </span>
            <Strip p={s} />
            <span className="meta">{a.meta}</span>
          </Link>
        ))}
      </div>
    </>
  );
}
