import { createHash } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { reviewDb } from "@/lib/dbReview";
import { ASPECTS, validateReview, type ReviewInput } from "@/lib/reviewModel";

// POST /api/reviews: store a resident review as 'pending'. Nothing is published until a moderator approves it.
// Spam checks: hidden honeypot field, at least 20 s on the form, at most 3 reviews a day from one IP (kept as a
// salted hash, never the address itself), no links.

export async function POST(req: NextRequest) {
  const db = reviewDb();
  if (!db) return NextResponse.json({ error: "Reviews are not open yet." }, { status: 503 });
  let x: ReviewInput;
  try {
    x = (await req.json()) as ReviewInput;
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  x.postcode = String(x.postcode ?? "").toUpperCase().replace(/\s+/g, " ").trim();
  if (x.website) return NextResponse.json({ ok: true }); // honeypot: pretend success
  if (!x.startedAt || Date.now() - x.startedAt < 20_000) return NextResponse.json({ error: "Please take a moment to complete the form." }, { status: 400 });
  const err = validateReview(x);
  if (err) return NextResponse.json({ error: err }, { status: 400 });
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  const ipHash = createHash("sha256").update(`${process.env.REVIEW_SALT ?? "zonecheck"}:${ip}`).digest("hex").slice(0, 32);
  try {
    const [n] = await db`select count(*)::int as n from mkt_uk.review where ip_hash = ${ipHash} and created_at > now() - interval '1 day'`;
    if ((n?.n ?? 0) >= 3) return NextResponse.json({ error: "Thanks, you have sent several reviews today. Please try again tomorrow." }, { status: 429 });
    const ratings = Object.fromEntries(ASPECTS.map(([k]) => [k, typeof x.ratings[k] === "number" ? x.ratings[k] : null]));
    const scores = Object.values(ratings).filter((v): v is number => typeof v === "number");
    const overall = Math.round((scores.reduce((s, v) => s + v, 0) / scores.length) * 10) / 10;
    await db`insert into mkt_uk.review (postcode, ratings, overall, tags, title, body, improve, author, relation, years, ip_hash)
             values (${x.postcode}, ${db.json(ratings)}, ${overall}, ${x.tags}, ${x.title.trim()}, ${x.body.trim()},
                     ${x.improve.trim() || null}, ${x.author.trim()}, ${x.relation}, ${x.years || null}, ${ipHash})`;
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("[reviews] insert failed:", e instanceof Error ? e.message : e);
    return NextResponse.json({ error: "Could not save the review. Please try again later." }, { status: 500 });
  }
}
