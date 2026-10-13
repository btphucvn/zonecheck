import Link from "next/link";
import type { Dict } from "@/i18n/dictionaries";
import { SearchBox } from "./SearchBox";
import { CompareNavLink } from "./compare/CompareTray";

export function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <rect x="1" y="1" width="24" height="24" rx="5" fill="var(--brand)" />
      <path d="M6 9h14L6 18h14" stroke="var(--brand-ink)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Header({ t }: { t: Dict }) {
  return (
    <header className="top">
      <div className="wrap">
        <Link className="logo" href="/" aria-label={`${t.meta.siteName} home`}>
          <Logo />
          {t.meta.siteName}
        </Link>
        <div className="hide-sm" style={{ flex: 1, display: "flex" }}>
          <SearchBox
            size="small"
            labels={{ label: t.nav.searchLabel, placeholder: t.nav.searchPlaceholder, noResults: t.search.noResults, searching: t.search.searching, error: t.search.error }}
          />
        </div>
        <nav className="nav-main" aria-label="Main">
          <Link href="/uk/where-to-live" className="hide-sm">{t.nav.where}</Link>
          <Link href="/uk/rankings" className="hide-sm">{t.nav.rankings}</Link>
          <Link href="/uk/tools" className="hide-sm">{t.nav.calculators}</Link>
          <CompareNavLink label={t.nav.compare} />
        </nav>
      </div>
    </header>
  );
}
