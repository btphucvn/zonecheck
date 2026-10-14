import Link from "next/link";
import { uk } from "@/markets/uk";
import type { Dict } from "@/i18n/dictionaries";
import type { AreaHead, AreaReport } from "@/server/types";

export const PLATE_LEVELS = new Set(["postcode_unit", "sector", "district"]);

/** Report sections that have their own detail page: section id → URL segment. */
export const TOPIC_PAGES: Record<string, string> = {
  prices: "prices", rent: "rent", safety: "crime", risk: "flood-risk", schools: "schools", transport: "transport", amenities: "amenities",
  environment: "environment", connectivity: "broadband", affluence: "affluence", people: "people", energy: "energy", planning: "planning", costs: "costs",
};
/** Levels each detail page supports (crime aggregates LSOAs per request; a region is ~5,000). */
const LOCAL_LEVELS = new Set(["postcode_unit", "sector", "district", "town", "ward", "lad"]);
const TOPIC_LEVELS: Record<string, Set<string>> = Object.fromEntries(Object.values(TOPIC_PAGES).map((t) => [t, LOCAL_LEVELS]));

/** Detail page path for a report section, or null when the area has none. */
export function topicHref(head: Pick<AreaHead, "level" | "slug">, section: string): string | null {
  const topic = TOPIC_PAGES[section];
  return topic && TOPIC_LEVELS[topic]?.has(head.level) ? `${areaPath(head)}/${topic}` : null;
}

/** URL segment → report section id. */
export const TOPIC_SECTION: Record<string, string> = Object.fromEntries(Object.entries(TOPIC_PAGES).map(([s, t]) => [t, s]));

export const areaPath = (head: Pick<AreaHead, "level" | "slug">) => `/uk/${uk.segmentForLevel(head.level)}/${head.slug}`;

export function lv2key(level: string): "postcode" | "sector" | "district" | "town" | "ward" | "lad" | "region" {
  return level === "postcode_unit" ? "postcode" : (level as "sector");
}

export function breadcrumbs(r: AreaReport): { label: string; href: string }[] {
  const out: { label: string; href: string }[] = [];
  const { ctx, head } = r;
  if (ctx.nation) out.push({ label: ctx.nation.name, href: "/" });
  if (ctx.region && head.level !== "region") out.push({ label: ctx.region.name, href: `/uk/region/${ctx.region.slug}` });
  if (ctx.lad && head.level !== "lad" && head.level !== "region") out.push({ label: ctx.lad.name, href: `/uk/area/${ctx.lad.slug}` });
  if (ctx.district && head.level !== "district") out.push({ label: ctx.district.code, href: `/uk/district/${ctx.district.slug}` });
  if (ctx.sector && head.level === "postcode_unit") out.push({ label: ctx.sector.code, href: `/uk/sector/${ctx.sector.slug}` });
  out.push({ label: PLATE_LEVELS.has(head.level) ? head.code : head.name, href: areaPath(head) });
  return out;
}

export function Crumbs({ items }: { items: { label: string; href: string }[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map((c, i) => (
        <span key={c.href}>{i > 0 && " › "}{i === items.length - 1 ? c.label : <Link href={c.href}>{c.label}</Link>}</span>
      ))}
    </nav>
  );
}

const TAB_SECTIONS = ["prices", "rent", "affluence", "safety", "people", "risk", "schools", "transport", "amenities", "environment", "connectivity", "energy", "planning", "costs"] as const;

/** Overview + one tab per report section; sections without a detail page jump to the report. */
export function TopicTabs({ head, t, active }: { head: Pick<AreaHead, "level" | "slug">; t: Dict; active: string }) {
  const base = areaPath(head);
  const items = [
    { id: "overview", label: t.report.topic.overview, href: base },
    ...TAB_SECTIONS.map((id) => ({
      id,
      label: t.report.topic.tabs[id],
      href: topicHref(head, id) ?? `${base}#report-${id}`,
    })),
  ];
  return (
    <nav className="topic-tabs" aria-label={t.report.topic.tabsLabel}>
      <ol>
        {items.map((i) => (
          <li key={i.id}>
            <Link href={i.href} className={i.id === active ? "on" : undefined} aria-current={i.id === active ? "page" : undefined}>
              {i.label}
            </Link>
          </li>
        ))}
      </ol>
    </nav>
  );
}
