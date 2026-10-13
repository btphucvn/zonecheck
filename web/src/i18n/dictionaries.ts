import "server-only";
import { lang } from "next/root-params";
import { notFound } from "next/navigation";
import { DEFAULT_LOCALE, INTL_LOCALE, isLocale, type Locale } from "./config";
import type en from "../../messages/en.json";

export type Dict = typeof en;

const dictionaries: Record<Locale, () => Promise<Dict>> = {
  en: () => import("../../messages/en.json").then((m) => m.default),
};

/** Current locale from the [lang] root segment. */
export async function getLocale(): Promise<Locale> {
  const l = (await lang()) ?? DEFAULT_LOCALE;
  if (!isLocale(l)) notFound();
  return l;
}

export async function getDictionary(locale?: Locale): Promise<Dict> {
  return dictionaries[locale ?? (await getLocale())]();
}

export async function getI18n() {
  const locale = await getLocale();
  return { locale, intl: INTL_LOCALE[locale], t: await getDictionary(locale) };
}

export { tpl } from "./config";
