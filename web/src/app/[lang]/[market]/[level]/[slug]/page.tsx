import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { tpl } from "@/i18n/config";
import { fmtNumber } from "@/lib/format";
import { getMarket, uk, UK_LEVELS } from "@/markets/uk";
import { SCORE_CATEGORIES } from "@/markets/uk/scoring";
import { getAreaHead, getAreaReport } from "@/server/area";
import { getMetricCatalog } from "@/server/meta";
import type { AreaReport } from "@/server/types";
import { Crumbs, PLATE_LEVELS, breadcrumbs, lv2key } from "@/components/report/nav";
import { Ad } from "@/components/report/bits";
import { AreaMap, type Essential, type MapPoi } from "@/components/report/AreaMap";
import { CompareButton } from "@/components/compare/CompareButton";
import { PrintButton, ShareButton, TocSpy } from "@/components/report/ReportClient";
import { ScorePanel, type ScoreCat } from "@/components/report/ScorePanel";
import type { H } from "@/components/report/helpers";
import * as S from "@/components/report/sections";

type Props = PageProps<"/[lang]/[market]/[level]/[slug]">;

// A few pages are prerendered at build; every other area renders on first
// visit and is then served from cache (ISR with Cache Components).
export async function generateStaticParams() {
  return [
    { market: "uk", level: "sector", slug: "se15-4" },
    { market: "uk", level: "district", slug: "se15" },
    { market: "uk", level: "area", slug: "southwark" },
  ];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { market, level: seg, slug } = await params;
  const lv = getMarket(market)?.levelBySegment(seg);
  if (!lv) return {};
  const head = await getAreaHead(lv.level, slug);
  if (!head) return { title: "Area not found", robots: { index: false } };
  const { t } = await getI18n();
  const name = PLATE_LEVELS.has(head.level) ? head.code : head.name;
  const where = head.displayName && head.displayName !== head.name ? `, ${head.displayName.replace(`${head.name}, `, "")}` : "";
  const path = `/uk/${seg}/${slug}`;
  const isUnit = head.level === "postcode_unit";
  // Index policy (PLAN §3.3): postcode units start noindex with canonical → sector.
  const canonical = isUnit && head.postcode ? `/uk/sector/${head.postcode.sector.toLowerCase().replace(/\s+/g, "-")}` : path;
  return {
    title: tpl(t.meta.areaTitle, { name }),
    description: tpl(t.meta.areaDescription, { name, where }),
    alternates: { canonical },
    robots: isUnit ? { index: false, follow: true } : undefined,
    openGraph: { title: tpl(t.meta.areaTitle, { name }), url: path },
  };
}

export default function AreaPage(props: Props) {
  return (
    <main className="wrap">
      <Suspense fallback={<ReportSkeleton />}>
        <Report params={props.params} />
      </Suspense>
    </main>
  );
}

function ReportSkeleton() {
  return (
    <div aria-busy="true">
      <p className="crumbs">&nbsp;</p>
      <div className="r-head stacked"><div className="skeleton" style={{ minHeight: 200 }} /><div className="skeleton" style={{ minHeight: 320 }} /></div>
      <div className="skeleton" style={{ minHeight: 260 }} />
    </div>
  );
}

async function Report({ params }: { params: Props["params"] }) {
  const { market, level: seg, slug } = await params;
  const m = getMarket(market);
  const lv = m?.levelBySegment(seg);
  if (!m || !lv) notFound();
  const report = await getAreaReport(lv.level, slug);
  if (!report) notFound();
  const { t, intl } = await getI18n();
  const cat = await getMetricCatalog("uk", "en");

  const dataLevel = report.ctx.dataArea.level;
  const peerKey = (dataLevel === "lsoa" ? "neighbourhoods" : UK_LEVELS.find((l) => l.level === dataLevel)?.peerKey ?? "sectors") as keyof typeof t.peers;
  const h: H = { r: report, t, cat, intl, peers: t.peers[peerKey] };
  const { head, ctx } = report;
  const isPlate = PLATE_LEVELS.has(head.level);
  const title = isPlate ? head.code : head.name;

  // Score panel inputs: category scores + ready-made strength/weakness lines.
  const cats: ScoreCat[] = SCORE_CATEGORIES.map((c) => {
    const s = report.categories.find((x) => x.code === c.code)?.score ?? null;
    const p = s == null ? 0 : Math.round(s);
    return {
      code: c.code, section: c.section, score: s, label: t.categories[c.code as keyof typeof t.categories],
      plus: tpl(t.score.plus[c.code as keyof typeof t.score.plus], { p, peers: h.peers }),
      minus: tpl(t.score.minus[c.code as keyof typeof t.score.minus], { q: 100 - p, peers: h.peers }),
    };
  });
  const personas = uk.personas.map((p) => ({
    code: p.code, weights: p.weights,
    label: t.personas[p.code as keyof typeof t.personas], plural: t.personasPlural[p.code as keyof typeof t.personasPlural],
  }));

  const crumbs = breadcrumbs(report);
  const place = ctx.town?.name ?? ctx.lad?.name ?? ctx.region?.name ?? "England and Wales";
  const whereKey = head.level as keyof typeof t.report.where;
  const where = t.report.where[whereKey]
    ? tpl(t.report.where[whereKey], {
        place: head.level === "lad" || head.level === "town" ? (ctx.region?.name ?? ctx.nation?.name ?? "") : head.level === "region" ? (ctx.nation?.name ?? "England") : `${place}${ctx.lad && ctx.lad.name !== place ? `, ${ctx.lad.name}` : ""}`,
        type: String((head.attrs as Record<string, unknown>).local_type ?? t.levels.town),
      })
    : "";
  const facts = [
    head.population ? tpl(t.report.residents, { n: fmtNumber(head.population, intl) }) : null,
    head.households ? tpl(t.report.homes, { n: fmtNumber(head.households, intl) }) : null,
    head.areaKm2 ? tpl(t.report.km2, { n: fmtNumber(head.areaKm2, intl, head.areaKm2 < 10 ? 1 : 0) }) : null,
  ].filter(Boolean).join(", ");

  const withChecklist = isPlate;
  const toc = ["prices", "rent", "safety", "risk", "schools", "transport", "amenities", "environment", "connectivity", "people", "energy", "planning", "checklist", "costs", "nearby"]
    .filter((id) => (id !== "nearby" || report.nearby.length) && (id !== "checklist" || withChecklist))
    .map((id) => ({ id, label: t.report.sections[id as keyof typeof t.report.sections] }));

  const neighbourLevel = head.level === "postcode_unit" ? "sector" : ["sector", "district", "lad"].includes(head.level) ? head.level : null;
  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "Place", name: title, geo: { "@type": "GeoCoordinates", latitude: head.lat, longitude: head.lon }, containedInPlace: ctx.lad ? { "@type": "AdministrativeArea", name: ctx.lad.name } : undefined },
      { "@type": "BreadcrumbList", itemListElement: crumbs.map((c, i) => ({ "@type": "ListItem", position: i + 1, name: c.label, item: c.href })) },
    ],
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }} />
      <Crumbs items={crumbs} />

      <div className="r-head stacked">
        <div className="r-title">
          {isPlate ? (
            <div className="plate" aria-label={`${t.levels[lv2key(head.level)]} ${head.code}`}>
              {head.code}
              <small>{ctx.lad?.name ?? ctx.town?.name ?? ""}</small>
            </div>
          ) : (
            <div className={`plate${title.length > 14 ? " long" : ""}`}>{title}<small>{t.levels[lv2key(head.level)]}</small></div>
          )}
          <h1>{isPlate ? `${head.code}${ctx.town ? `, ${ctx.town.name}` : ""}` : `${head.name}: area report`}</h1>
          <p className="where">{[where, facts].filter(Boolean).join(". ")}</p>
          {head.level === "postcode_unit" && (
            <p className="m-src" style={{ fontSize: 14 }}>
              {head.postcode?.status === "terminated" ? `${t.report.terminated} ` : ""}
              {tpl(t.report.noindexNote, { lsoa: ctx.dataArea.code })}{" "}
              {ctx.sector && <Link href={`/uk/sector/${ctx.sector.slug}`}>{ctx.sector.code}</Link>}
            </p>
          )}
          <div className="r-actions">
            <CompareButton item={{ level: seg, slug, label: isPlate ? head.code : head.name }} labels={{ add: t.report.actions.compare, added: t.report.actions.compared, max: t.compare.max }} />
            <ShareButton label={t.report.actions.share} copied={t.report.actions.copied} />
            <PrintButton label={t.report.actions.print} />
          </div>
        </div>
        <AreaMap
          center={[head.lon, head.lat]}
          bbox={report.bbox}
          geojson={report.geojson}
          label={title}
          levelForNeighbours={neighbourLevel}
          boundaryNote={!report.boundaryApprox ? null : head.level === "postcode_unit"
            ? "Boundary drawn around the addresses in this postcode. Not an official line."
            : "Boundary drawn around the postcodes in this area. Not an official line."}
          pois={mapPois(report)}
          essentials={essentialsOf(report)}
          radiusM={head.level === "postcode_unit" ? 500 : undefined}
        />
      </div>

      {report.scoreSource === "none" ? (
        <div className="score-panel"><p className="empty-note">{t.score.pending}</p></div>
      ) : (
        <ScorePanel
          cats={cats}
          personas={personas}
          t={{
            whoLabel: t.home.whoTitle, outOf: t.score.outOf, bands: t.score.bands, desc: t.score.desc, plusTitle: t.score.plusTitle,
            minusTitle: t.score.minusTitle, nonePlus: t.score.nonePlus, noneMinus: t.score.noneMinus, weight: t.score.weight,
            notCounted: t.score.notCounted, noData: t.score.noData, tweak: t.score.tweak, reset: t.score.reset,
            method: tpl(t.score.method, { peers: h.peers }), methodLink: t.score.methodLink,
          }}
        />
      )}

      <Ad kind="leader" label="728×90 / 320×100" />

      <div className="r-body">
        <TocSpy items={toc} />
        <div>
          <S.Prices h={h} />
          <S.Rent h={h} />
          <S.Safety h={h} />
          <S.Risk h={h} />
          <Ad kind="inline" label="336×280, lazy-loaded" />
          <S.Schools h={h} />
          <S.Transport h={h} />
          <S.Amenities h={h} />
          <Ad kind="inline" label="Responsive in-content, lazy-loaded" />
          <S.Environment h={h} />
          <S.Connectivity h={h} />
          <S.People h={h} />
          <S.Energy h={h} />
          <Ad kind="inline" label="Responsive in-content, lazy-loaded" />
          <S.Planning h={h} />
          {withChecklist && <S.Checklist h={h} />}
          <S.Costs h={h} />
          <S.Nearby h={h} />
          <div className="report-foot">
            <span>
              {report.updatedAt && tpl(t.report.footer.updated, { date: new Date(report.updatedAt).toLocaleDateString(intl, { day: "numeric", month: "long", year: "numeric" }) })}{" "}
              <Link href="/sources">{t.report.footer.allSources}</Link>
            </span>
            <a className="btn" href={`mailto:data@zonecheck.example?subject=${encodeURIComponent(`Data issue: ${title}`)}`}>{t.report.footer.mistake}</a>
          </div>
        </div>
        <aside className="rail" aria-label="Sponsored">
          <Ad kind="side" label="300×600, sticky" />
        </aside>
      </div>
    </>
  );
}

const stationName = (n: string) => n.replace(/ (Rail|Underground) Station$/, "").replace(/ Station$/, "");

function mapPois(r: AreaReport): MapPoi[] {
  return [
    ...r.stations.map((s) => ({ name: stationName(s.name), type: s.type, lon: s.lon, lat: s.lat, href: s.slug ? `/uk/station/${s.slug}` : null })),
    ...r.schools.map((s) => ({
      name: s.name, type: s.type, lon: s.lon, lat: s.lat, href: s.slug ? `/uk/school/${s.slug}` : null,
      ofsted: s.rating?.scheme === "ofsted_oeif" ? (s.rating.rank ?? 0) : 0, ofstedLabel: s.rating?.label ?? "Not rated",
    })),
    ...r.amenities.map((a) => ({ name: a.name, type: a.type, lon: a.lon, lat: a.lat })),
  ];
}

/** Nearest of each essential, in the order a mover asks about them. */
function essentialsOf(r: AreaReport): Essential[] {
  const out: Essential[] = [];
  const st = r.stations[0];
  if (st) out.push({ label: st.type === "station.metro" ? "Tube or tram" : "Station", name: stationName(st.name), dist: st.dist, lon: st.lon, lat: st.lat, icon: st.type === "station.metro" ? "zc|metro" : "zc|rail", href: st.slug ? `/uk/station/${st.slug}` : null });
  for (const [label, types, letter] of [["Primary school", ["school.primary", "school.all_through"], "P"], ["Secondary school", ["school.secondary", "school.all_through"], "S"]] as const) {
    const s = r.schools.find((x) => (types as readonly string[]).includes(x.type));
    if (s) {
      const rank = s.rating?.scheme === "ofsted_oeif" ? (s.rating.rank ?? 0) : 0;
      out.push({ label: `${label}${s.rating ? `, ${s.rating.label}` : ""}`, name: s.name, dist: s.dist, lon: s.lon, lat: s.lat, icon: `zc|school|${rank}|${letter}`, href: s.slug ? `/uk/school/${s.slug}` : null });
    }
  }
  for (const [label, type] of [["GP", "health.gp"], ["Pharmacy", "health.pharmacy"], ["Supermarket", "shop.supermarket"], ["Dentist", "health.dentist"]] as const) {
    const a = r.amenities.find((x) => x.type === type);
    if (a) out.push({ label, name: a.name, dist: a.dist, lon: a.lon, lat: a.lat, icon: `zc|${type}` });
  }
  return out;
}
