import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { getMarket, UK_LEVELS } from "@/markets/uk";
import { getAreaReport } from "@/server/area";
import { getCrimeDetail, getCrimeHistory, getWardCrime } from "@/server/crime";
import { getPointExtras } from "@/server/point";
import { getMetricCatalog } from "@/server/meta";
import { getAmenityDetail, getHpiHistory, getNeighbourValues, getPlanningApps, getPlanningDetail, getSchoolsDetail } from "@/server/topic";
import type { H } from "@/components/report/helpers";
import { Crumbs, PLATE_LEVELS, TOPIC_SECTION, TopicTabs, areaPath, breadcrumbs, topicHref } from "@/components/report/nav";
import { TopicShell } from "@/components/report/topic/Shell";
import { NEIGHBOUR_METRIC, SUBTABS, TOPICS, type TopicData } from "@/components/report/topic/topics";
import Link from "next/link";

export type TopicParams = Promise<{ lang: string; market: string; level: string; slug: string; topic: string; tab?: string }>;

/** The report, the topic's extra data and its rendered parts, or null when there is no such page. */
async function load(params: TopicParams) {
  const { market, level: seg, slug, topic, tab: rawTab } = await params;
  const tabs = SUBTABS[topic];
  // the first sub-tab lives at the topic URL itself; /<topic>/<first tab> is not a page
  if (rawTab && (!tabs || !tabs.some((x, i) => i > 0 && x.id === rawTab))) return null;
  const tab = rawTab ?? null;
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
  const [crime, neighbours, hpi, schools, amenities, planning, wards, point, history, apps] = await Promise.all([
    topic === "crime" ? getCrimeDetail(ctx.dataArea.id, ctx.lad?.id ?? null, head.level === "postcode_unit" ? [head.lon, head.lat] : null) : null,
    nb ? getNeighbourValues(head.lon, head.lat, nb) : undefined,
    topic === "prices" && ctx.lad ? getHpiHistory(ctx.lad.id) : undefined,
    topic === "schools" ? getSchoolsDetail(head.lon, head.lat) : undefined,
    topic === "amenities" ? getAmenityDetail(head.lon, head.lat) : undefined,
    topic === "planning" ? getPlanningDetail(head.lon, head.lat) : undefined,
    topic === "crime" && head.level === "lad" ? getWardCrime(head.id) : undefined,
    (topic === "environment" || topic === "transport") && ["postcode_unit", "sector"].includes(head.level)
      ? getPointExtras(head.lon, head.lat, head.level === "postcode_unit" ? head.code : null) : undefined,
    topic === "crime" ? getCrimeHistory(ctx.dataArea.id, ctx.lad ? { id: ctx.lad.id, name: ctx.lad.name } : null,
      ctx.region ? { id: ctx.region.id, name: ctx.region.name } : null, name) : undefined,
    topic === "planning" && ["postcode_unit", "sector"].includes(head.level) ? getPlanningApps(head.lon, head.lat) : undefined,
  ]);
  const data: TopicData = { h, name, base: areaPath(head), tab, crime, history, wards, point, apps, neighbours, hpi, schools, amenities, planning };
  const view = build(data);
  if (!view) return null;
  return { topic, tab, tabs, section, report, h, name, view };
}

export async function topicMetadata(params: TopicParams): Promise<Metadata> {
  const x = await load(params);
  if (!x) return { title: "Page not found", robots: { index: false } };
  const { head, ctx } = x.report;
  const sub = x.tab ? `/${x.topic}/${x.tab}` : `/${x.topic}`;
  const path = `${areaPath(head)}${sub}`;
  const isUnit = head.level === "postcode_unit";
  // Same index policy as the report: postcode units are noindex, canonical to their sector.
  const canonical = isUnit && ctx.sector ? `/uk/sector/${ctx.sector.slug}${sub}` : path;
  return {
    title: x.view.title,
    description: x.view.description,
    alternates: { canonical },
    robots: isUnit ? { index: false, follow: true } : undefined,
    openGraph: { title: x.view.title, url: path },
  };
}

export function TopicPage({ params }: { params: TopicParams }) {
  return (
    <main className="wrap">
      <Suspense fallback={<TopicSkeleton />}>
        <Topic params={params} />
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

async function Topic({ params }: { params: TopicParams }) {
  const x = await load(params);
  if (!x) notFound();
  const { report, section, h, name, view, topic, tab, tabs } = x;
  const { head, ctx } = report;
  const { t } = h;
  const base = areaPath(head);
  const crumbs = [...breadcrumbs(report), { label: t.report.topic.tabs[section as keyof typeof t.report.topic.tabs], href: `${base}/${topic}` }];
  if (tab && tabs) crumbs.push({ label: tabs.find((x) => x.id === tab)!.label, href: `${base}/${topic}/${tab}` });
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
      {tabs && <SubTabs base={`${base}/${topic}`} tabs={tabs} active={tab ?? tabs[0].id} label={t.report.topic.tabs[section as keyof typeof t.report.topic.tabs]} />}
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
      {report.nearby.length > 0 && (
        <nav className="tp-nearby" aria-label="Nearby areas">
          <h2>{view.title.replace(/ in .*$/, "")} in nearby areas</h2>
          <ul>
            {report.nearby.slice(0, 8).map((n) => {
              const label = PLATE_LEVELS.has(n.level) ? n.code : n.name;
              return <li key={n.id}><Link href={`${areaPath(n)}/${topic}${tab ? `/${tab}` : ""}`}>{view.title.replace(/ in .*$/, "")} in {label}</Link></li>;
            })}
          </ul>
        </nav>
      )}
    </>
  );
}

function SubTabs({ base, tabs, active, label }: { base: string; tabs: { id: string; label: string }[]; active: string; label: string }) {
  return (
    <nav className="tp-subtabs" aria-label={`${label} sections`}>
      {tabs.map((x, i) => (
        <Link key={x.id} href={i === 0 ? base : `${base}/${x.id}`} className={x.id === active ? "on" : undefined} aria-current={x.id === active ? "page" : undefined}>{x.label}</Link>
      ))}
    </nav>
  );
}
