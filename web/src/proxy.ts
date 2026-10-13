import { NextResponse, type NextRequest } from "next/server";
import { DEFAULT_LOCALE, LOCALES } from "./i18n/config";

// `as-needed` locale prefixes (PLAN §4.4): English lives at /uk/..., other
// languages at /<locale>/uk/.... Internally every page sits under app/[lang].
export function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const first = pathname.split("/")[1];

  if (first === DEFAULT_LOCALE) {
    const url = req.nextUrl.clone();
    url.pathname = pathname.slice(DEFAULT_LOCALE.length + 1) || "/";
    return NextResponse.redirect(url, 308);
  }
  if ((LOCALES as readonly string[]).includes(first)) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = `/${DEFAULT_LOCALE}${pathname === "/" ? "" : pathname}`;
  url.search = search;
  return NextResponse.rewrite(url);
}

export const config = {
  // Skip API, Next internals and any file with an extension (robots.txt, sitemap.xml, images).
  matcher: ["/((?!api|_next|.*\\..*).*)"],
};
