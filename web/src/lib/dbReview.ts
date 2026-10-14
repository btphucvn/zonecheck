import "server-only";
import postgres from "postgres";

// Separate, minimal write path for resident reviews: the role behind REVIEW_DATABASE_URL may only INSERT into
// mkt_uk.review (and read two columns of it to rate-limit). Everything else in the web stays read-only.

const g = globalThis as unknown as { __zcReview?: postgres.Sql };

export function reviewDb(): postgres.Sql | null {
  const url = process.env.REVIEW_DATABASE_URL;
  if (!url) return null;
  return (g.__zcReview ??= postgres(url, { max: 2, idle_timeout: 60, connect_timeout: 20, connection: { application_name: "zonecheck-review" } }));
}
