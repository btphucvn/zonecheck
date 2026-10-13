import type { Metadata } from "next";
import { Suspense } from "react";
import { getI18n } from "@/i18n/dictionaries";
import { fmtDate } from "@/lib/format";
import { uk } from "@/markets/uk";
import { getSources } from "@/server/meta";

export const metadata: Metadata = {
  title: "Data sources and update dates",
  description: "Every dataset ZoneCheck uses, who publishes it, its licence and when we last updated it.",
  alternates: { canonical: "/sources" },
};

async function SourceList({ intl }: { intl: string }) {
  const sources = await getSources("uk");
  return (
    <>
      {sources.map((s) => (
        <section key={s.id} className="rs">
          <h2>{s.homepage ? <a href={s.homepage} rel="noopener">{s.name}</a> : s.name}</h2>
          <p className="sum">{s.publisher}. Licence: {s.licenceUrl ? <a href={s.licenceUrl} rel="noopener">{s.licence}</a> : s.licence}.</p>
          {s.attribution && <p className="m-src">{s.attribution}</p>}
          {s.datasets.length > 0 && (
            <div className="scroll-x">
              <table className="data">
                <thead><tr><th>Dataset</th><th>Updated</th><th>Version</th><th>Last fetched</th></tr></thead>
                <tbody>
                  {s.datasets.map((d) => (
                    <tr key={d.id}><td>{d.name}</td><td>{d.frequency}</td><td>{d.version ?? "–"}</td><td>{d.fetchedAt ? fmtDate(d.fetchedAt, intl) : "Not yet loaded"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </>
  );
}

export default async function SourcesPage() {
  const { t, intl } = await getI18n();
  return (
    <main className="wrap" style={{ paddingBottom: 60 }}>
      <div className="page-head">
        <h1>{t.footer.sources}</h1>
        <p>Every figure on ZoneCheck comes from an open dataset. Each one is listed here with its publisher, licence and the date we last fetched it.</p>
      </div>
      <p className="m-src" style={{ maxWidth: "72ch", marginBottom: 20 }}>{uk.attribution}</p>
      <Suspense fallback={<div className="skeleton" />}><SourceList intl={intl} /></Suspense>
    </main>
  );
}
