import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { tpl } from "@/i18n/config";
import { fmtMoney, fmtMonth, fmtNumber } from "@/lib/format";
import { uk } from "@/markets/uk";
import { getRanking, RANKINGS } from "@/server/rankings";

type Props = PageProps<"/[lang]/[market]/rankings/[metric]/[scope]">;

export async function generateStaticParams() {
  return RANKINGS.map((r) => ({ market: "uk", metric: r.slug, scope: "england-and-wales" }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { metric, scope } = await params;
  const { t } = await getI18n();
  const def = RANKINGS.find((r) => r.slug === metric);
  if (!def) return {};
  const title = t.rankings[def.titleKey as keyof typeof t.rankings];
  return { title: scope === "england-and-wales" ? `${title} in England and Wales` : `${title.replace("local authorities", "postcode sectors")}: ${scope.replace(/-/g, " ")}` };
}

export default function RankingPage(props: Props) {
  return (
    <main className="wrap">
      <Suspense fallback={<div className="skeleton" />}><Body params={props.params} /></Suspense>
    </main>
  );
}

async function Body({ params }: { params: Props["params"] }) {
  const { metric, scope } = await params;
  const data = await getRanking(metric, scope);
  if (!data) notFound();
  const { t, intl } = await getI18n();
  const id = data.def.metric;
  const fmt = (v: number) => (id === "uk.price.median" || id === "uk.income.net" ? fmtMoney(v, "GBP", intl)
    : id.endsWith("_share") ? `${fmtNumber(v, intl, v < 10 ? 1 : 0)}%` : fmtNumber(v, intl, 1));
  const title = t.rankings[data.def.titleKey as keyof typeof t.rankings];
  const local = scope !== "england-and-wales";
  return (
    <>
      <div className="page-head">
        <h1>{local ? title.replace("local authorities", "postcode sectors") : title} {tpl(t.rankings.inScope, { scope: data.scopeName })}</h1>
        <p>Data period {fmtMonth(data.period, intl)}. {data.def.order === -1 ? "Lowest value first." : "Highest value first."}</p>
        {local && (
          <p>{RANKINGS.map((r) => <Link key={r.slug} href={`/uk/rankings/${r.slug}/${scope}`} style={{ marginInlineEnd: 12 }}>{t.rankings[r.titleKey as keyof typeof t.rankings].replace(" local authorities", "")}</Link>)}</p>
        )}
      </div>
      {data.rows.length ? (
        <div className="cmp-wrap">
          <table className="data" style={{ fontSize: 15 }}>
            <thead><tr><th className="r">{t.rankings.rank}</th><th>{t.rankings.area}</th><th className="r">{t.rankings.value}</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.slug}>
                  <td className="r num">{r.rank}</td>
                  <td><Link href={`/uk/${uk.segmentForLevel(r.level)}/${r.slug}`}>{r.level === "sector" ? r.code : r.name}</Link></td>
                  <td className="r num">{fmt(r.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="empty-note">{t.rankings.none}</p>}
    </>
  );
}
