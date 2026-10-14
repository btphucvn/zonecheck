import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { getPoiPage, SAMPLE_STATION } from "@/server/poi";
import Link from "next/link";
import { PoiPageView } from "@/components/PoiPageView";
import { DataSays } from "@/components/report/DataSays";
import type { H } from "@/components/report/helpers";
import { getAreaReport } from "@/server/area";
import { getAreaInsights, getClassification } from "@/server/insights";
import { getMetricCatalog } from "@/server/meta";
import { getPointExtras } from "@/server/point";

type Props = PageProps<"/[lang]/[market]/station/[slug]">;

export async function generateStaticParams() {
  return [{ market: "uk", slug: SAMPLE_STATION }];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const p = await getPoiPage("station", slug);
  if (!p) return { title: "Station not found", robots: { index: false } };
  const name = p.name.replace(/ Rail Station$/, "");
  return {
    title: `Living near ${name} station: passengers, schools and area`,
    description: `${name} station: passenger numbers, nearby stations and the area around it.`,
    alternates: { canonical: `/uk/station/${slug}` },
  };
}

export default function StationPage(props: Props) {
  return (
    <main className="wrap">
      <Suspense fallback={<div className="skeleton" />}>
        <Body params={props.params} />
      </Suspense>
    </main>
  );
}

async function Body({ params }: { params: Props["params"] }) {
  const { market, slug } = await params;
  if (market !== "uk") notFound();
  const p = await getPoiPage("station", slug);
  if (!p) notFound();
  const { t, intl } = await getI18n();
  // The neighbourhood around the station: the same "Data says" summary as the area report of its postcode
  const pc = p.postcodeArea;
  const report = pc ? await getAreaReport("postcode_unit", pc.slug) : null;
  let around = null;
  if (report) {
    const cat = await getMetricCatalog("uk", "en");
    const h: H = { r: report, t, cat, intl, peers: t.peers.neighbourhoods };
    const [insights, oac, point] = await Promise.all([
      getAreaInsights("postcode_unit", pc!.slug, { dataId: report.ctx.dataArea.id, dataLevel: report.ctx.dataArea.level,
        scopeId: report.ctx.sector?.id ?? null, scopeName: report.ctx.sector?.code ?? null }),
      getClassification("postcode_unit", pc!.code),
      getPointExtras(p.lon, p.lat, pc!.code),
    ]);
    around = (
      <section className="station-area">
        <h2>Living near {p.name.replace(/ (Rail|Underground) Station$/, "")}</h2>
        <p className="sum">The neighbourhood around the station ({pc!.code}). <Link href={`/uk/postcode/${pc!.slug}`}>Full area report</Link></p>
        <DataSays h={h} insights={insights} oac={oac} point={point} />
      </section>
    );
  }
  return <><PoiPageView p={p} kind="station" intl={intl} />{around}</>;
}
