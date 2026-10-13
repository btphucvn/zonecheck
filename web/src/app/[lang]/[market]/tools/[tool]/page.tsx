import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getI18n } from "@/i18n/dictionaries";
import { MortgageCalc, MovingCostsCalc, RentVsBuyCalc, StampDutyCalc } from "@/components/tools/Calculators";
import { Ad } from "@/components/report/bits";
import { TOOLS } from "../tools";

type Props = PageProps<"/[lang]/[market]/tools/[tool]">;

export async function generateStaticParams() {
  return TOOLS.map((x) => ({ market: "uk", tool: x.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { tool } = await params;
  const x = TOOLS.find((y) => y.slug === tool);
  if (!x) return {};
  const { t } = await getI18n();
  return { title: t.tools[x.key].title, description: t.tools[x.key].desc, alternates: { canonical: `/uk/tools/${tool}` } };
}

export default async function ToolPage({ params }: Props) {
  const { tool } = await params;
  const x = TOOLS.find((y) => y.slug === tool);
  if (!x) notFound();
  const { t } = await getI18n();
  const s = t.tools[x.key];
  return (
    <main className="wrap">
      <nav className="crumbs" aria-label="Breadcrumb"><Link href="/uk/tools">{t.tools.title}</Link> › {s.title}</nav>
      <div className="page-head"><h1>{s.title}</h1><p>{s.desc}</p></div>
      <div className="r-body" style={{ gridTemplateColumns: "minmax(0,1fr) 300px" }}>
        <div>
          <section className="rs">
            {x.slug === "stamp-duty" && <StampDutyCalc detailed />}
            {x.slug === "mortgage-affordability" && <MortgageCalc />}
            {x.slug === "moving-costs" && <MovingCostsCalc />}
            {x.slug === "rent-vs-buy" && <RentVsBuyCalc />}
            <p className="m-src" style={{ marginTop: 14 }}>{t.tools.disclaimer}</p>
          </section>
          <Ad kind="inline" label="Responsive in-content" />
          <section className="rs">
            <h2>Other calculators</h2>
            <ul>{TOOLS.filter((y) => y.slug !== x.slug).map((y) => <li key={y.slug}><Link href={`/uk/tools/${y.slug}`}>{t.tools[y.key].title}</Link></li>)}</ul>
          </section>
        </div>
        <aside className="rail" aria-label="Sponsored"><Ad kind="side" label="300×600, sticky" /></aside>
      </div>
    </main>
  );
}
