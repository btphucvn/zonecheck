import type { Metadata, Viewport } from "next";
import { Overpass, Schibsted_Grotesk } from "next/font/google";
import { Suspense } from "react";
import "../globals.css";
import { LOCALES, INTL_LOCALE, type Locale } from "@/i18n/config";
import { getI18n } from "@/i18n/dictionaries";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { Providers } from "@/components/Providers";
import { CompareTray } from "@/components/compare/CompareTray";

const body = Schibsted_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600", "700", "800"], variable: "--font-body", display: "swap" });
// Overpass descends from Highway Gothic, the lettering of road signs: used for numbers and the postcode plate.
const sign = Overpass({ subsets: ["latin"], weight: ["600", "800"], variable: "--font-sign-face", display: "swap" });

export async function generateStaticParams() {
  return LOCALES.map((lang) => ({ lang }));
}

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return {
    metadataBase: new URL(SITE),
    title: { default: t.meta.homeTitle, template: `%s | ${t.meta.siteName}` },
    description: t.meta.homeDescription,
    applicationName: t.meta.siteName,
    openGraph: { siteName: t.meta.siteName, type: "website", locale: "en_GB" },
  };
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#16212f" },
  ],
};

// Applies a saved light/dark choice before first paint (no flash).
const THEME_SCRIPT = `try{var t=localStorage.getItem('zc:theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}`;

export default async function RootLayout({ children }: LayoutProps<"/[lang]">) {
  const { locale, t } = await getI18n();
  return (
    <html lang={INTL_LOCALE[locale as Locale]} className={`${body.variable} ${sign.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <a href="#main" className="sr">{t.nav.skip}</a>
        <Providers>
          <Header t={t} />
          <div id="main">{children}</div>
          <Footer t={t} />
          <Suspense>
            <CompareTray label={t.compare.now} removeLabel={t.compare.remove} />
          </Suspense>
        </Providers>
      </body>
    </html>
  );
}
