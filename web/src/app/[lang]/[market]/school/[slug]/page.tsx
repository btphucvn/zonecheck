import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { getPoiPage, SAMPLE_SCHOOL } from "@/server/poi";
import { PoiPageView } from "@/components/PoiPageView";

type Props = PageProps<"/[lang]/[market]/school/[slug]">;

export async function generateStaticParams() {
  return [{ market: "uk", slug: SAMPLE_SCHOOL }];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const p = await getPoiPage("school", slug);
  if (!p) return { title: "School not found", robots: { index: false } };
  const rating = p.ratings.find((r) => r.current && r.aspect === "overall")?.label;
  return {
    title: `${p.name}: Ofsted${rating ? ` ${rating}` : ""}, results and catchment area`,
    description: `${p.name}, ${p.typeName.toLowerCase()} in ${p.postcode ?? "England"}. Ofsted grades, exam results, pupil numbers and the area around the school.`,
    alternates: { canonical: `/uk/school/${slug}` },
  };
}

export default function SchoolPage(props: Props) {
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
  const p = await getPoiPage("school", slug);
  if (!p) notFound();
  const { intl } = await getI18n();
  const jsonLd = { "@context": "https://schema.org", "@type": "School", name: p.name, address: p.address ?? undefined, geo: { "@type": "GeoCoordinates", latitude: p.lat, longitude: p.lon } };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />
      <PoiPageView p={p} kind="school" intl={intl} />
    </>
  );
}
