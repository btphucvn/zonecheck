import Link from "next/link";
import { Suspense } from "react";
import { cacheLife } from "next/cache";
import { getI18n } from "@/i18n/dictionaries";
import { fmtMoney, fmtNumber } from "@/lib/format";
import { uk } from "@/markets/uk";
import { getAreaCard } from "@/server/area";
import { RANKINGS } from "@/server/rankings";
import { SearchBox } from "@/components/SearchBox";
import { PersonaChips } from "@/components/report/ScorePanel";
import { PopularAreas, type PopularArea } from "@/components/home/PopularAreas";
import { HomeMap } from "@/components/home/HomeMap";
import { HeroPreview } from "@/components/home/HeroPreview";
import { getSources } from "@/server/meta";

const POPULAR: [string, string][] = [
  ["sector", "se15-4"], ["sector", "se22-9"], ["sector", "m20-2"], ["sector", "bs6-6"],
  ["sector", "ls6-3"], ["sector", "cf11-9"], ["sector", "nw5-1"], ["sector", "b13-9"],
];
const EXAMPLES = [["SE15 4NX", "/uk/postcode/se15-4nx"], ["Peckham", "/uk/town/peckham"], ["Manchester", "/uk/town/manchester"], ["Harris Academy Peckham", "/uk/school/134225-harris-academy-peckham"]];

/** Deterministic contour lines: the OS-map texture behind the hero. */
function Contours() {
  const paths: string[] = [];
  for (let i = 0; i < 14; i++) {
    const cx = 930, cy = 250, rx = 60 + i * 42, ry = 40 + i * 30;
    const pts: string[] = [];
    for (let a = 0; a <= 360; a += 12) {
      const r = (a * Math.PI) / 180, wob = 1 + 0.07 * Math.sin((a * Math.PI) / 45 + i) + 0.04 * Math.cos((a * Math.PI) / 30 - i * 0.7);
      pts.push(`${(cx + Math.cos(r) * rx * wob).toFixed(1)},${(cy + Math.sin(r) * ry * wob).toFixed(1)}`);
    }
    paths.push(`M${pts.join("L")}Z`);
  }
  return (
    <svg className="contours" viewBox="0 0 1200 520" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {paths.map((d, i) => <path key={i} d={d} fill="none" stroke="currentColor" strokeWidth={i % 5 === 4 ? 2.2 : 1} />)}
    </svg>
  );
}

type Dict = Awaited<ReturnType<typeof getI18n>>["t"];
type PersonaW = { code: string; plural: string; weights: Record<string, number> };

/** The hero's right column: a real report card for one sample sector. getAreaCard caches
 *  its own result; failures stay outside the cache so a DB outage isn't remembered. */
async function HeroSample({ t, personas }: { t: Dict; personas: PersonaW[] }) {
  const c = await getAreaCard("sector", "se15-4").catch(() => null);
  if (!c) return null;
  const sample = {
    href: `/uk/sector/${c.head.slug}`,
    plate: c.head.code,
    place: c.ctx.town?.name ?? c.head.code,
    where: c.ctx.lad?.name ?? "",
    cats: c.categories.map((x) => ({ code: x.code, label: t.categories[x.code as keyof typeof t.categories] ?? x.code, score: x.score })),
  };
  return <HeroPreview sample={sample} personas={personas} t={{ kicker: t.home.sampleKicker, outOf: t.score.outOf, bands: t.score.bands, forWho: t.home.sampleFor, open: t.home.sampleOpen }} />;
}

/** Publishers people recognise, shown first; the rest live on /sources. */
const FEATURED_PUBLISHERS = ["HM Land Registry", "Home Office / police forces", "Ofsted", "Environment Agency", "ONS", "Ofcom"];

/** Trust line under the search: the publishers we draw on, straight from the sources table. */
async function SourceLine({ t }: { t: Dict }) {
  const sources = await getSources("uk").catch(() => []);
  if (!sources.length) return null;
  const have = new Set(sources.map((s) => s.publisher));
  const names = FEATURED_PUBLISHERS.filter((p) => have.has(p));
  return (
    <p className="hero-sources">
      <span>{t.home.sourcesLead.replace("{n}", String(sources.length))}</span>{" "}
      {names.join(" · ")}{" · "}<Link href="/sources">{t.home.sourcesAll}</Link>
    </p>
  );
}

async function Popular({ template, personas }: { template: string; personas: PersonaW[] }) {
  "use cache";
  cacheLife("days");
  const cards = (await Promise.all(POPULAR.map(([l, s]) => getAreaCard(l, s).catch(() => null)))).filter((c) => c != null);
  const areas: PopularArea[] = cards.map((c) => ({
    href: `/uk/sector/${c.head.slug}`,
    title: c.ctx.town?.name ?? c.head.code,
    sub: `${c.head.code}, ${c.ctx.lad?.name ?? ""}`,
    meta: [
      c.metrics["uk.price.median"]?.v ? `Median ${fmtMoney(c.metrics["uk.price.median"].v)}` : null,
      c.metrics["uk.crime.total_rate"]?.v != null ? `${fmtNumber(c.metrics["uk.crime.total_rate"].v)} crimes per 1,000` : null,
    ].filter(Boolean).join(", "),
    cats: Object.fromEntries(c.categories.map((x) => [x.code, x.score])),
  }));
  return <PopularAreas areas={areas} personas={personas} template={template} />;
}

export default async function Home() {
  const { t } = await getI18n();
  const personas = uk.personas.map((p) => ({ code: p.code, label: t.personas[p.code as keyof typeof t.personas] }));
  const weighted = uk.personas.map((p) => ({ code: p.code, weights: p.weights, plural: t.personasPlural[p.code as keyof typeof t.personasPlural] }));
  return (
    <main>
      <div className="hero">
        <Contours />
        <div className="wrap hero-grid">
          <div className="hero-copy">
            <h1>{t.home.h1a} {t.home.h1b}</h1>
            <p className="lede">{t.home.lede}</p>
            <SearchBox size="big" labels={{ label: t.nav.searchLabel, placeholder: t.search.placeholder, button: t.search.button, noResults: t.search.noResults, searching: t.search.searching, error: t.search.error }} />
            <p className="examples">{t.home.examples}{" "}{EXAMPLES.map(([l, h]) => <Link key={h} href={h}>{l}</Link>)}</p>
            <p className="hero-alt">{t.home.altLead} <Link href="/uk/where-to-live">{t.home.altLink}</Link></p>
            <div className="hero-who">
              <h2>{t.home.whoTitle}</h2>
              <PersonaChips personas={personas} label={t.home.whoTitle} />
            </div>
            <Suspense fallback={null}><SourceLine t={t} /></Suspense>
          </div>
          <div className="hero-side">
            <Suspense fallback={<div className="hero-card skeleton" />}><HeroSample t={t} personas={weighted} /></Suspense>
          </div>
        </div>
      </div>

      <section className="home-sec">
        <div className="wrap">
          <h2>{t.home.mapTitle}</h2>
          <p className="sub">{t.home.mapSub}</p>
          <HomeMap />
        </div>
      </section>

      <section className="home-sec">
        <div className="wrap">
          <h2>{t.home.popularTitle}</h2>
          <Suspense fallback={<div className="skeleton" />}>
            <Popular template={t.home.popularSub} personas={weighted} />
          </Suspense>
        </div>
      </section>

      <section className="home-sec">
        <div className="wrap">
          <h2>{t.home.freeTitle}</h2>
          <p className="sub">{t.home.freeSub}</p>
          <div className="scroll-x">
            <table className="free-table">
              <thead><tr><th>{t.home.freeCheck}</th><th>{t.home.freeUs}</th><th>{t.home.freeThem}</th></tr></thead>
              <tbody>{t.home.freeRows.map(([a, b]) => <tr key={a}><td>{a}</td><td className="us">{t.home.free}</td><td className="paid">{b}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="home-sec">
        <div className="wrap">
          <h2>{t.home.toolsTitle}</h2>
          <p className="sub">{t.home.toolsSub}</p>
          <div className="tools">
            <Link className="tool" href="/uk/where-to-live"><h3>{t.where.title}</h3><p>{t.home.whereDesc}</p></Link>
            {([["stamp-duty", t.tools.stampDuty], ["mortgage-affordability", t.tools.mortgage], ["moving-costs", t.tools.moving], ["rent-vs-buy", t.tools.rentVsBuy]] as const).map(([slug, x]) => (
              <Link key={slug} className="tool" href={`/uk/tools/${slug}`}><h3>{x.title}</h3><p>{x.desc}</p></Link>
            ))}
          </div>
        </div>
      </section>

      <section className="home-sec">
        <div className="wrap">
          <h2>{t.home.rankingsTitle}</h2>
          <p className="sub">{t.home.rankingsSub}</p>
          <ul className="chips" style={{ listStyle: "none", padding: 0 }}>
            {RANKINGS.map((r) => (
              <li key={r.slug}><Link className="chip" style={{ display: "inline-block", textDecoration: "none", color: "var(--ink)" }} href={`/uk/rankings/${r.slug}/england-and-wales`}>{t.rankings[r.titleKey as keyof typeof t.rankings]}</Link></li>
            ))}
          </ul>
        </div>
      </section>
    </main>
  );
}
