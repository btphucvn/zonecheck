import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { getPoiPage, SAMPLE_STATION } from "@/server/poi";
import { PoiPageView } from "@/components/PoiPageView";

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
  const { intl } = await getI18n();
  return <PoiPageView p={p} kind="station" intl={intl} />;
}
