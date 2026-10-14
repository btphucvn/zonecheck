import Link from "next/link";
import type { AreaReviews } from "@/server/reviews";

// "Locals say": resident reviews next to the official figures, with the eight aspect scores, the words people use
// and the latest reviews. Shows an invitation when there are none yet.

export function LocalsSay({ reviews, postcode }: { reviews: AreaReviews | null; postcode: string | null }) {
  if (!reviews) return null;
  const href = `/uk/review/new${postcode ? `?postcode=${encodeURIComponent(postcode)}` : ""}`;
  return (
    <section className="rs locals" id="report-reviews" aria-labelledby="h-locals">
      <h2 id="h-locals">Locals say</h2>
      {reviews.n === 0 ? (
        <p className="sum">No resident reviews for {reviews.scope} yet. <Link href={href}>Be the first to review your neighbourhood</Link>: it takes about five minutes.</p>
      ) : (
        <>
          <p className="sum"><b>{reviews.overall!.toFixed(1)}</b> out of 10 from {reviews.n} review{reviews.n > 1 ? "s" : ""} in {reviews.scope}. <Link href={href}>Add yours</Link></p>
          <ul className="locals-aspects">
            {reviews.aspects.filter((a) => a.avg != null).map((a) => (
              <li key={a.k}><span>{a.label}</span><span className="bar" aria-hidden="true"><i style={{ width: `${a.avg! * 10}%` }} /></span><b>{a.avg!.toFixed(1)}</b></li>
            ))}
          </ul>
          {reviews.tags.length > 0 && <p className="locals-tags">{reviews.tags.map((t) => <span key={t.tag}>{t.tag}</span>)}</p>}
          <ul className="locals-items">
            {reviews.items.map((r) => (
              <li key={r.id}>
                <p><b>{r.overall.toFixed(1)}</b> · <strong>{r.title}</strong></p>
                <p>{r.body.length > 400 ? `${r.body.slice(0, 400)}…` : r.body}</p>
                {r.improve && <p className="m-src">To improve: {r.improve}</p>}
                <p className="m-src">{r.author}, {r.postcode}, {r.date}</p>
              </li>
            ))}
          </ul>
          <p className="m-src">Reviews are personal opinions from residents, checked by ZoneCheck before they appear. They are not used in any score.</p>
        </>
      )}
    </section>
  );
}
