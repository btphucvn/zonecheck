import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { tpl } from "@/i18n/config";
import { fmtDistance, fmtMoney, fmtNumber } from "@/lib/format";
import { uk } from "@/markets/uk";
import { Strip } from "@/components/report/bits";
import { findPlaces, getScopeOptions, type WhereQuery } from "@/server/wheretolive";

type Props = PageProps<"/[lang]/[market]/where-to-live">;

export const metadata: Metadata = {
  title: "Where should I live? Find areas that fit you",
  description: "Rank every postcode sector in England and Wales for families, buyers, renters, commuters or retirees. Filter by budget, flood risk, crime and station. Free, no sign-up.",
  alternates: { canonical: "/uk/where-to-live" },
};

export async function generateStaticParams() {
  return [{ market: "uk" }];
}

const BUDGETS = [150000, 200000, 250000, 300000, 400000, 500000, 750000, 1000000];

function parse(sp: Record<string, string | string[] | undefined>): WhereQuery {
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const persona = uk.personas.some((p) => p.code === one("who")) ? one("who") : "family";
  const scope = /^(region|lad):[a-z0-9-]+$/.test(one("in")) ? one("in") : "england-and-wales";
  const max = Number(one("max"));
  return {
    persona, scope,
    level: one("level") === "district" ? "district" : "sector",
    maxPrice: BUDGETS.includes(max) ? max : null,
    lowFlood: one("flood") === "1",
    nearStation: one("station") === "1",
    lowCrime: one("crime") === "1",
  };
}

export default async function WhereToLivePage(props: Props) {
  const { t } = await getI18n();
  return (
    <main className="wrap" style={{ paddingBottom: 60 }}>
      <div className="page-head">
        <h1>{t.where.title}</h1>
        <p>{t.where.lede}</p>
      </div>
      <Suspense fallback={<div className="skeleton" style={{ minHeight: 320 }} />}>
        <Body searchParams={props.searchParams} />
      </Suspense>
    </main>
  );
}

async function Body({ searchParams }: { searchParams: Props["searchParams"] }) {
  const q = parse(await searchParams);
  const { t, intl } = await getI18n();
  const tw = t.where;
  const [scopes, rows] = await Promise.all([getScopeOptions(), findPlaces(q)]);
  const scopeLabel = scopes.find((s) => s.value === q.scope)?.label ?? tw.everywhere;
  const persona = t.personasPlural[q.persona as keyof typeof t.personasPlural];
  const seg = q.level === "district" ? "district" : "sector";
  return (
    <>
      <form className="wtl-form" method="get" action="/uk/where-to-live">
        <p className="wtl-sentence">
          <span>{tw.s1}</span>
          <label><span className="sr">{tw.who}</span>
            <select name="who" defaultValue={q.persona}>
              {uk.personas.map((p) => <option key={p.code} value={p.code}>{t.personasPlural[p.code as keyof typeof t.personasPlural]}</option>)}
            </select>
          </label>
          <span>{tw.s2}</span>
          <label><span className="sr">{tw.where}</span>
            <select name="in" defaultValue={q.scope}>
              <option value="england-and-wales">{tw.everywhere}</option>
              <optgroup label={tw.regions}>
                {scopes.filter((s) => s.group === "region").map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </optgroup>
              <optgroup label={tw.lads}>
                {scopes.filter((s) => s.group === "lad").map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </optgroup>
            </select>
          </label>
          <span>{tw.s3}</span>
          <label><span className="sr">{tw.budget}</span>
            <select name="max" defaultValue={q.maxPrice ? String(q.maxPrice) : ""}>
              <option value="">{tw.anyBudget}</option>
              {BUDGETS.map((b) => <option key={b} value={b}>{tpl(tw.upTo, { p: fmtMoney(b, "GBP", intl) })}</option>)}
            </select>
          </label>
        </p>
        <fieldset className="wtl-must">
          <legend>{tw.mustHave}</legend>
          {([["flood", tw.lowFlood, q.lowFlood], ["crime", tw.lowCrime, q.lowCrime], ["station", tw.nearStation, q.nearStation]] as const).map(([n, l, on]) => (
            <label key={n} className="chip-check"><input type="checkbox" name={n} value="1" defaultChecked={on} /><span>{l}</span></label>
          ))}
          <label className="wtl-size">{tw.size}{" "}
            <select name="level" defaultValue={q.level}>
              <option value="sector">{tw.sectors}</option>
              <option value="district">{tw.districts}</option>
            </select>
          </label>
        </fieldset>
        <button type="submit" className="btn primary">{tw.find}</button>
      </form>

      <h2 className="wtl-h">{tpl(tw.resultsTitle, { who: persona, where: scopeLabel })}</h2>
      {rows.length ? (
        <ol className="wtl-list">
          {rows.map((r) => (
            <li key={r.slug}>
              <Link href={`/uk/${seg}/${r.slug}`} className="wtl-row">
                <span className="wtl-plate num">{r.code}</span>
                <span className="wtl-place">
                  <b>{r.place ?? r.code}</b>
                  <span>{r.strengths.length ? tpl(tw.strongOn, { list: r.strengths.slice(0, 3).map((c) => (t.categories[c as keyof typeof t.categories] ?? c).toLowerCase()).join(", ") }) : ""}</span>
                </span>
                <span className="wtl-score">
                  <span className="num">{Math.round(r.score)}</span>
                  <Strip p={r.score} label={tpl(tw.scoreAria, { s: Math.round(r.score) })} />
                </span>
                <span className="wtl-facts">
                  <span><i>{tw.price}</i>{r.price != null ? fmtMoney(r.price, "GBP", intl) : "–"}</span>
                  <span><i>{tw.crime}</i>{r.crime != null ? fmtNumber(r.crime, intl, 0) : "–"}</span>
                  <span><i>{tw.station}</i>{r.stationM != null ? fmtDistance(r.stationM, intl) : "–"}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      ) : <p className="empty-note">{tw.none}</p>}
      <p className="m-src" style={{ marginTop: 14, maxWidth: "72ch" }}>
        {tpl(tw.method, { who: persona })} <Link href="/methodology">{t.score.methodLink}</Link>
      </p>
    </>
  );
}
