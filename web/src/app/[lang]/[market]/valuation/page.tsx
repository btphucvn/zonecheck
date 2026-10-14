import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { fmtDate, fmtMoney, fmtNumber } from "@/lib/format";
import { parseUkQuery } from "@/markets/uk";
import { getValuation, listAddresses } from "@/server/valuation";

type Props = PageProps<"/[lang]/[market]/valuation">;

export async function generateMetadata({ searchParams }: Props): Promise<Metadata> {
  const sp = await searchParams;
  return {
    title: "How much is my house worth? Free instant valuation",
    description: "Free instant estimate of a home's value in England and Wales from Land Registry sales, energy certificates and the House Price Index, with the workings shown.",
    alternates: { canonical: "/uk/valuation" },
    // result pages (one per address) are not indexed
    robots: sp.postcode || sp.a ? { index: false, follow: true } : undefined,
  };
}

export async function generateStaticParams() {
  return [{ market: "uk" }];
}

export default function ValuationPage(props: Props) {
  return (
    <main className="wrap valuation">
      <div className="page-head">
        <h1>How much is my house worth?</h1>
        <p>A free instant estimate from open data: the home&rsquo;s floor area on its energy certificate, recent sales of similar homes nearby and the local House Price Index. Every figure is shown so you can check it.</p>
      </div>
      <Suspense fallback={<div className="skeleton" style={{ minHeight: 200 }} />}>
        <Body {...props} />
      </Suspense>
    </main>
  );
}

async function Body({ params, searchParams }: Props) {
  const { market } = await params;
  if (market !== "uk") notFound();
  const sp = await searchParams;
  const { intl } = await getI18n();
  const raw = typeof sp.postcode === "string" ? sp.postcode : "";
  const parsed = raw ? parseUkQuery(raw) : null;
  const postcode = parsed?.kind === "postcode_unit" ? parsed.code : null;
  const key = typeof sp.a === "string" ? sp.a : null;
  const money = (x: number) => fmtMoney(x, "GBP", intl);

  const form = (
    <form className="val-form" method="get" action="/uk/valuation">
      <label htmlFor="val-pc">Postcode</label>
      <input id="val-pc" name="postcode" defaultValue={postcode ?? raw} placeholder="e.g. SE15 4DX" autoComplete="postal-code" required />
      <button className="btn" type="submit">Find addresses</button>
    </form>
  );
  if (!postcode) {
    return <>{form}{raw && <p className="empty-note">Enter a full postcode, for example SE15 4DX.</p>}</>;
  }
  if (!key) {
    const list = await listAddresses(postcode);
    return (
      <>
        {form}
        <section className="rs">
          <h2>Choose the address in {postcode}</h2>
          {list.length ? (
            <ul className="val-list">
              {list.map((x) => (
                <li key={x.key}>
                  <Link href={`/uk/valuation?postcode=${encodeURIComponent(postcode)}&a=${encodeURIComponent(x.key)}`}>{x.label}</Link>
                  <span className="m-src">{[x.type, x.floorArea && `${fmtNumber(x.floorArea, intl)} m²`].filter(Boolean).join(", ")}</span>
                </li>
              ))}
            </ul>
          ) : <p className="empty-note">No home in {postcode} has an energy certificate, which this estimate needs for the floor area.</p>}
        </section>
      </>
    );
  }
  const v = await getValuation(key);
  if (!v) {
    return <>{form}<p className="empty-note">Not enough comparable sales nearby to estimate this home.</p></>;
  }
  return (
    <>
      {form}
      <section className="rs val-result" aria-labelledby="val-h">
        <h2 id="val-h">{v.address}, {v.postcode}</h2>
        <p className="val-mid">{money(v.mid)}</p>
        <p className="sum">Likely range {money(v.low)} to {money(v.high)}. Confidence: <b>{v.confidence}</b> ({v.comps} comparable sales in {v.scope}).</p>
        <table className="data">
          <tbody>
            <tr><th scope="row">Home</th><td>{[v.type, v.builtForm, v.rooms ? `${v.rooms} habitable rooms` : null].filter(Boolean).join(", ")}</td></tr>
            <tr><th scope="row">Floor area</th><td>{fmtNumber(v.floorArea, intl)} m² (energy certificate, {fmtDate(v.epcDate, intl)}{v.rating ? `, rated ${v.rating}` : ""})</td></tr>
            <tr><th scope="row">Price per m² nearby</th><td>{money(v.perSqm.q1)} – {money(v.perSqm.q3)}, middle {money(v.perSqm.q2)}</td></tr>
            {v.lastSale && <tr><th scope="row">Last sold</th><td>{money(v.lastSale.price)} on {fmtDate(v.lastSale.date, intl)}{v.lastSale.adjusted ? `; ${money(v.lastSale.adjusted)} in today's prices` : ""}</td></tr>}
          </tbody>
        </table>
        <h3 className="sub-h">How this is worked out</h3>
        <p>We take sales of {/flat|maisonette/i.test(v.type ?? "") ? "flats and maisonettes" : "houses"} in {v.scope} over the last 24 months that we could match to an energy certificate, move each price to {v.hpiMonth ?? "today"} with the UK House Price Index for the local authority, and divide by floor area. The estimate is this home&rsquo;s floor area times the middle price per m²; the range uses the middle half of sales. Condition, garden, parking, extensions and views are not known, so a surveyor or estate agent may value it differently.</p>
        <p className="m-src">Sources: HM Land Registry Price Paid Data, MHCLG Energy Performance Certificates, UK House Price Index. This is an automated estimate, not a valuation for lending.</p>
      </section>
    </>
  );
}
