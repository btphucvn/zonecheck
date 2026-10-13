import type { Metadata } from "next";
import Link from "next/link";
import { getI18n } from "@/i18n/dictionaries";
import { TOOLS } from "./tools";

export const metadata: Metadata = { title: "Property calculators", alternates: { canonical: "/uk/tools" } };

export async function generateStaticParams() {
  return [{ market: "uk" }];
}

export default async function ToolsIndex() {
  const { t } = await getI18n();
  return (
    <main className="wrap">
      <div className="page-head"><h1>{t.tools.title}</h1><p>{t.home.toolsSub}</p></div>
      <div className="tools" style={{ paddingBottom: 60 }}>
        {TOOLS.map((x) => {
          const s = t.tools[x.key];
          return <Link key={x.slug} className="tool" href={`/uk/tools/${x.slug}`}><h3>{s.title}</h3><p>{s.desc}</p></Link>;
        })}
      </div>
    </main>
  );
}
