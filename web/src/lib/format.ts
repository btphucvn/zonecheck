// Number, money and date formatting through Intl, keyed by locale + market currency.

export function fmtNumber(v: number | null | undefined, locale = "en-GB", decimals = 0): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return v.toLocaleString(locale, { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

export function fmtMoney(v: number | null | undefined, currency = "GBP", locale = "en-GB"): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 0 }).format(v);
}

export function fmtMoneyShort(v: number, currency = "GBP", locale = "en-GB"): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency, notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function fmtPct(v: number | null | undefined, locale = "en-GB", decimals = 0): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return `${fmtNumber(v, locale, decimals)}%`;
}

/** Straight-line metres to a walking-friendly label: "350 m", "1.2 km". */
export function fmtDistance(m: number | null | undefined, locale = "en-GB"): string {
  if (m == null || !Number.isFinite(m)) return "–";
  if (m < 1000) return `${fmtNumber(Math.round(m / 10) * 10, locale)} m`;
  return `${fmtNumber(m / 1000, locale, m < 10000 ? 1 : 0)} km`;
}

/** ~80 m/min walking pace on straight-line distance x1.25 for street detours. */
export function walkMinutes(m: number): number {
  return Math.max(1, Math.round((m * 1.25) / 80));
}

export function fmtMonth(iso: string | null | undefined, locale = "en-GB"): string {
  if (!iso) return "–";
  const d = new Date(iso.length === 7 ? `${iso}-01` : iso);
  return d.toLocaleDateString(locale, { month: "short", year: "numeric", timeZone: "UTC" });
}

export function fmtDate(iso: string | null | undefined, locale = "en-GB"): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

export function ordinalWord(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}
