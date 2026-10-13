import Link from "next/link";
import type { Dict } from "@/i18n/dictionaries";
import { uk } from "@/markets/uk";
import { ThemeToggle } from "./ThemeToggle";

export function Footer({ t }: { t: Dict }) {
  return (
    <footer className="site">
      <div className="wrap">
        <div className="cols">
          <div>
            <h3>{t.footer.reports}</h3>
            <ul>
              <li><Link href="/uk/area/southwark">Southwark</Link></li>
              <li><Link href="/uk/town/manchester">Manchester</Link></li>
              <li><Link href="/uk/district/se15">SE15</Link></li>
              <li><Link href="/uk/rankings">{t.nav.rankings}</Link></li>
            </ul>
          </div>
          <div>
            <h3>{t.footer.tools}</h3>
            <ul>
              <li><Link href="/uk/compare">{t.compare.title}</Link></li>
              <li><Link href="/uk/tools/stamp-duty">{t.tools.stampDuty.title}</Link></li>
              <li><Link href="/uk/tools/mortgage-affordability">{t.tools.mortgage.title}</Link></li>
              <li><Link href="/uk/tools/moving-costs">{t.tools.moving.title}</Link></li>
              <li><Link href="/uk/tools/rent-vs-buy">{t.tools.rentVsBuy.title}</Link></li>
            </ul>
          </div>
          <div>
            <h3>{t.footer.about}</h3>
            <ul>
              <li><Link href="/sources">{t.footer.sources}</Link></li>
              <li><Link href="/methodology">{t.footer.methodology}</Link></li>
              <li><Link href="/glossary">{t.footer.glossary}</Link></li>
            </ul>
          </div>
        </div>
        <p>{t.footer.disclaimer}</p>
        <p>{uk.attribution}</p>
        <ThemeToggle label={t.footer.theme} />
      </div>
    </footer>
  );
}
