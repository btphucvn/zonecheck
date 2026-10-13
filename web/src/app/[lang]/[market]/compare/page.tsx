import type { Metadata } from "next";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { fmtDistance, fmtMoney, fmtNumber, fmtPct, walkMinutes } from "@/lib/format";
import { uk } from "@/markets/uk";
import { getAreaCard } from "@/server/area";
import { CompareTable, type CmpCol, type CmpRow } from "@/components/compare/CompareTable";

export const metadata: Metadata = {
  title: "Compare areas side by side",
  description: "Compare up to four postcodes, towns or local authorities on prices, crime, schools, transport and more. Free.",
  alternates: { canonical: "/uk/compare" },
};

export async function generateStaticParams() {
  return [{ market: "uk" }];
}

export default async function ComparePage(props: PageProps<"/[lang]/[market]/compare">) {
  const { t } = await getI18n();
  return (
    <main className="wrap">
      <div className="page-head">
        <h1>{t.compare.title}</h1>
      </div>
      <Suspense fallback={<div className="skeleton" />}>
        <Body searchParams={props.searchParams} />
      </Suspense>
    </main>
  );
}

async function Body({ searchParams }: { searchParams: PageProps<"/[lang]/[market]/compare">["searchParams"] }) {
  const sp = await searchParams;
  const { t, intl } = await getI18n();
  const keys = ["a", "b", "c", "d"]
    .map((k) => sp[k])
    .filter((v): v is string => typeof v === "string" && /^[a-z]+:[a-z0-9-]+$/.test(v))
    .slice(0, 4);
  const cards = (await Promise.all(keys.map(async (k) => {
    const [seg, slug] = k.split(":");
    const lv = uk.levelBySegment(seg);
    if (!lv) return null;
    const c = await getAreaCard(lv.level, slug).catch(() => null);
    return c ? { key: k, seg, c } : null;
  }))).filter((x) => x != null);

  if (!cards.length) return <p className="empty-note" style={{ fontSize: 16, paddingBottom: 60 }}>{t.compare.empty}</p>;

  const plate = (l: string) => ["postcode_unit", "sector", "district"].includes(l);
  const cols: CmpCol[] = cards.map(({ key, seg, c }) => ({
    key, href: `/uk/${seg}/${c.head.slug}`,
    title: plate(c.head.level) ? c.head.code : c.head.name,
    sub: [c.ctx.town?.name, c.ctx.lad?.name].filter((x, i, a) => x && a.indexOf(x) === i).join(", "),
    cats: Object.fromEntries(c.categories.map((x) => [x.code, x.score])),
  }));
  const v = (id: string) => cards.map(({ c }) => (c.metrics[id] && !c.metrics[id].suppressed ? c.metrics[id].v : null));
  const mk = (label: string, values: (number | null)[], f: (x: number) => string, better?: "hi" | "lo"): CmpRow => ({ label, values, display: values.map((x) => (x == null ? "–" : f(x))), better });
  const r = t.compare.rows;
  const rows: CmpRow[] = [
    mk(r.price, v("uk.price.median"), (x) => fmtMoney(x, "GBP", intl), "lo"),
    mk(r.rent, cards.map(({ c }) => c.twoBedRent), (x) => fmtMoney(x, "GBP", intl), "lo"),
    mk(r.crime, v("uk.crime.total_rate"), (x) => fmtNumber(x, intl, 0), "lo"),
    mk(r.station, cards.map(({ c }) => c.nearestStation?.dist ?? null), (x) => `${fmtDistance(x, intl)}, ${walkMinutes(x)} min`, "lo"),
    mk(r.gp, v("uk.access.gp_dist_m"), (x) => fmtDistance(x, intl), "lo"),
    mk(r.flood, v("uk.zone.flood_zone3_share"), (x) => fmtPct(x, intl, 1), "lo"),
    mk(r.surface, v("uk.zone.sw_high_share"), (x) => fmtPct(x, intl, 1), "lo"),
    mk(r.radon, v("uk.zone.radon_1pct_share"), (x) => fmtPct(x, intl, 1), "lo"),
    mk(r.coal, v("uk.zone.coal_reporting_share"), (x) => fmtPct(x, intl, 1), "lo"),
    mk(r.clay, v("uk.zone.shrink_swell_sig_share"), (x) => fmtPct(x, intl, 1), "lo"),
    mk(r.no2, v("uk.pcm.no2"), (x) => fmtNumber(x, intl, 1), "lo"),
    mk(r.income, v("uk.income.net"), (x) => fmtMoney(x, "GBP", intl), "hi"),
  ];
  rows[3].display = rows[3].display.map((d, i) => (cards[i].c.nearestStation ? `${cards[i].c.nearestStation!.name.replace(/ Rail Station$/, "")}, ${d}` : d));
  const personas = uk.personas.map((p) => ({ code: p.code, weights: p.weights, label: t.personas[p.code as keyof typeof t.personas], plural: t.personasPlural[p.code as keyof typeof t.personasPlural] }));
  return (
    <CompareTable
      cols={cols} rows={rows.filter((x) => x.values.some((y) => y != null))} personas={personas} sub={t.compare.sub} scoreLabel={r.score} whoLabel={t.home.whoTitle} removeLabel={t.compare.remove}
      catLabels={t.categories as unknown as Record<string, string>}
    />
  );
}
