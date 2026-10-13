import type { MetadataRoute } from "next";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/uk/compare"] }],
    sitemap: [0, 1, 2, 3, 4, 5].map((i) => `${SITE}/sitemap/${i}.xml`),
  };
}
