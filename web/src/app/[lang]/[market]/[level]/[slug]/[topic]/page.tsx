import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { getMarket, UK_LEVELS } from "@/markets/uk";
import { getAreaReport } from "@/server/area";
import { getCrimeDetail } from "@/server/crime";
import { getMetricCatalog } from "@/server/meta";
import { getAmenityDetail, getHpiHistory, getNeighbourValues, getPlanningDetail, getSchoolsDetail } from "@/server/topic";
import type { H } from "@/components/report/helpers";
import { Crumbs, PLATE_LEVELS, TOPIC_SECTION, TopicTabs, areaPath, breadcrumbs, topicHref } from "@/components/report/nav";
import { TopicShell } from "@/components/report/topic/Shell";
import { NEIGHBOUR_METRIC, TOPICS, type TopicData } from "@/components/report/topic/topics";

type Props = PageProps<"/[lang]/[market]/[level]/[slug]/[topic]">;

// Detail page for one report section, e.g. /uk/postcode/se15-4dx/crime. Rendered on first
// visit and cached like the report itself.
export async function generateStaticParams() {
  return [{ market: "uk", level: "sector", slug: "se15-4", topic: "crime" }];
}

/** The report, the topic's extra data and its rendered parts, or null when there is no such page. */
async function load(params: Props["params"]) {
  const { market, level: seg, slug, topic } = await params;
  const section = TOPIC_SECTION[topic];
  const lv = getMarket(market)?.levelBySegment(seg);
  const build = TOPICS[topic];
  if (!section || !lv || !build) return null;
  const report = await getAreaReport(lv.level, slug);
  if (!report || !topicHref(report.head, section)) return null;
  const { t, intl } = await getI18n();
  const cat = await getMetricCatalog("uk", "en");
  const { head, ctx } = report;
  const dataLevel = ctx.dataArea.level;
  const peerKey = (dataLevel === "lsoa" ? "neighbourhoods" : UK_LEVELS.find((l) => l.level === dataLevel)?.peerKey ?? "sectors") as keyof typeof t.peers;
  const h: H = { r: report, t, cat, intl, peers: t.peers[peerKey] };
  const name = PLATE_LEVELS.has(head.level) ? head.code : head.name;
  const nb = NEIGHBOUR_METRIC[topic];
  const [crime, neighbours, hpi, schools, amenities, planning] = await Promise.all([
    topic === "crime" ? getCrimeDetail(ctx.dataArea.id, ctx.lad?.id ?? null, head.level === "postcode_unit" ? [head.lon, head.lat] : null) : null,
    nb ? getNeighbourValues(head.lon, head.lat, nb) : undefined,
    topic === "prices" && ctx.lad ? getHpiHistory(ctx.lad.id) : undefined,
    topic === "schools" ? getSchoolsDetail(head.lon, head.lat) : undefined,
    topic === "amenities" ? getAmenityDetail(head.lon, head.lat) : undefined,
    topic === "planning" ? getPlanningDetail(head.lon, head.lat) : undefined,
  ]);
  const data: TopicData = { h, name, base: areaPath(head), crime, neighbours, hpi, schools, amenities, planning };
  const view = build(data);
  if (!view) return null;
  return { topic, section, report, h, name, view };
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const x = await load(params);
  if (!x) return { title: "Page not found", robots: { index: false } };
  const { head, ctx } = x.report;
  const path = `${areaPath(head)}/${x.topic}`;
  const isUnit = head.level === "postcode_unit";
  // Same index policy as the report: postcode units are noindex, canonical to their sector.
  const canonical = isUnit && ctx.sector ? `/uk/sector/${ctx.sector.slug}/${x.topic}` : path;
  return {
    title: x.view.title,
    description: x.view.description,
    alternates: { canonical },
    robots: isUnit ? { index: false, follow: true } : undefined,
    openGraph: { title: x.view.title, url: path },
  };
}

export default function TopicPage(props: Props) {
  return (
    <main className="wrap">
      <Suspense fallback={<TopicSkeleton />}>
        <Topic params={props.params} />
      </Suspense>
    </main>
  );
}

function TopicSkeleton() {
  return (
    <div aria-busy="true">
      <p className="crumbs">&nbsp;</p>
      <div className="skeleton" style={{ minHeight: 460, marginTop: 44 }} />
      <div className="skeleton" style={{ minHeight: 200 }} />
    </div>
  );
}

async function Topic({ params }: { params: Props["params"] }) {
  const x = await load(params);
  if (!x) notFound();
  const { report, section, h, name, view, topic } = x;
  const { head, ctx } = report;
  const { t } = h;
  const base = areaPath(head);
  const crumbs = [...breadcrumbs(report), { label: t.report.topic.tabs[section as keyof typeof t.report.topic.tabs], href: `${base}/${topic}` }];
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({ "@type": "ListItem", position: i + 1, name: c.label, item: c.href })),
  };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />
      <Crumbs items={crumbs} />
      <TopicTabs head={head} t={t} active={section} />
      <TopicShell
        plate={name}
        plateSub={[ctx.town?.name, ctx.lad?.name].filter((s, i, a) => s && a.indexOf(s) === i).join(", ")}
        map={view.map}
        title={view.title}
        verdict={view.verdict}
        dek={view.dek}
        ruler={view.ruler}
        main={view.main}
        side={view.side}
        after={view.after}
        source={view.source}
        back={{ href: `${base}#report-${section}`, label: `Back to the full report for ${name}` }}
      />
    </>
  );
}
