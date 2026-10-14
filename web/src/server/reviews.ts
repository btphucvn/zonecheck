import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";
import { ASPECTS } from "@/lib/reviewModel";

// Approved resident reviews for an area: postcode pages use their sector (a single street rarely has enough),
// larger areas every postcode inside them. Averages are plain means of the 1–10 ratings given.

type Row = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface ReviewItem { id: string; title: string; body: string; improve: string | null; author: string; postcode: string; date: string; overall: number; tags: string[] }
export interface AreaReviews {
  n: number; overall: number | null; aspects: { k: string; label: string; avg: number | null; n: number }[];
  tags: { tag: string; n: number }[]; items: ReviewItem[]; scope: string;
}

export async function getAreaReviews(level: string, code: string, scopeLabel: string): Promise<AreaReviews | null> {
  "use cache";
  cacheLife("hours");
  cacheTag("market:uk", "reviews", `reviews:${level}:${code}`);
  const col = { sector: sql`p.sector`, district: sql`p.district`, ward: sql`p.ward_code`, lad: sql`p.lad_code` }[level];
  if (!col) return null;
  return scoped(async () => {
    try {
      const rows = await sql`
        select r.id::text, r.title, r.body, r.improve, r.author, r.postcode, r.created_at::date::text as d, r.overall::float8 as overall,
               r.tags, r.ratings
        from mkt_uk.review r join mkt_uk.postcode p on p.postcode = r.postcode
        where r.status = 'approved' and ${col} = ${code}
        order by r.created_at desc limit 200`;
      if (!rows.length) return { n: 0, overall: null, aspects: [], tags: [], items: [], scope: scopeLabel };
      const aspects = ASPECTS.map(([k, label]) => {
        const v = rows.map((r: Row) => r.ratings?.[k]).filter((x: unknown): x is number => typeof x === "number");
        return { k, label, avg: v.length ? v.reduce((s, x) => s + x, 0) / v.length : null, n: v.length };
      });
      const tagCount = new Map<string, number>();
      for (const r of rows as Row[]) for (const t of r.tags ?? []) tagCount.set(t, (tagCount.get(t) ?? 0) + 1);
      return {
        n: rows.length, overall: rows.reduce((s: number, r: Row) => s + r.overall, 0) / rows.length, aspects,
        tags: [...tagCount].map(([tag, n]) => ({ tag, n })).sort((a, b) => b.n - a.n).slice(0, 8),
        items: rows.slice(0, 8).map((r: Row) => ({ id: r.id, title: r.title, body: r.body, improve: r.improve, author: r.author, postcode: r.postcode, date: r.d, overall: r.overall, tags: r.tags ?? [] })),
        scope: scopeLabel,
      };
    } catch (e) {
      console.error("[reviews] failed:", e instanceof Error ? e.message : e);
      cacheLife("minutes");
      return null;
    }
  });
}
