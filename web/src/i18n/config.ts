// Locales the UI ships with. MVP is English only (PLAN §4.4); adding a language
// = add it here + messages/<code>.json + core.market_locale rows.
export const LOCALES = ["en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
/** BCP 47 tag used for Intl formatting and <html lang> */
export const INTL_LOCALE: Record<Locale, string> = { en: "en-GB" };

export function isLocale(v: string): v is Locale {
  return (LOCALES as readonly string[]).includes(v);
}

/** Path for a locale with `as-needed` prefixing: the default locale has no prefix. */
export function localePath(locale: string, path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return locale === DEFAULT_LOCALE ? p : `/${locale}${p === "/" ? "" : p}`;
}

/** Tiny ICU-ish interpolation: "Hello {name}" + {name: "x"}. Usable on server and client. */
export function tpl(s: string, vars: Record<string, string | number>): string {
  return s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}
