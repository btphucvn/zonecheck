import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { getLadList, RANKINGS } from "@/server/rankings";

export const metadata: Metadata = { title: "Area rankings for England and Wales", alternates: { canonical: "/uk/rankings" } };

export async function generateStaticParams() {
  return [{ market: "uk" }];
}

async function LadPicker() {
  const lads = await getLadList();
  return (
    <ul className="prose" style={{ columns: "220px", paddingInlineStart: 18 }}>
      {lads.map((l) => <li key={l.slug}><Link href={`/uk/rankings/safest/${l.slug}`}>{l.name}</Link></li>)}
    </ul>
  );
}

export default async function RankingsIndex() {
  const { t } = await getI18n();
  return (
    <main className="wrap">
      <div className="page-head"><h1>{t.rankings.title}</h1><p>{t.home.rankingsSub}</p></div>
      <div className="tools" style={{ marginBottom: 32 }}>
        {RANKINGS.map((r) => (
          <Link key={r.slug} className="tool" href={`/uk/rankings/${r.slug}/england-and-wales`}>
            <h3>{t.rankings[r.titleKey as keyof typeof t.rankings]}</h3>
          </Link>
        ))}
      </div>
      <h2 className="sub-h" style={{ fontSize: 22 }}>{t.rankings.pickLad}</h2>
      <Suspense fallback={<div className="skeleton" />}><LadPicker /></Suspense>
    </main>
  );
}
