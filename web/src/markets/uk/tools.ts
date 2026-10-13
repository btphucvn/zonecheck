// UK property tax and lending maths. Pure functions, shared by calculators and report pages.

type Band = [upTo: number, rate: number];

function sliced(price: number, bands: Band[]): { tax: number; rows: { from: number; to: number; rate: number; tax: number }[] } {
  let prev = 0, tax = 0;
  const rows: { from: number; to: number; rate: number; tax: number }[] = [];
  for (const [top, rate] of bands) {
    if (price > prev) {
      const part = Math.min(price, top) - prev;
      const t = part * rate;
      rows.push({ from: prev, to: Math.min(price, top), rate, tax: t });
      tax += t;
    }
    prev = top;
  }
  return { tax: Math.round(tax), rows };
}

export type BuyerKind = "ftb" | "mover" | "additional";
export type Nation = "england" | "wales";

// England SDLT, residential, from 1 April 2025.
const SDLT: Band[] = [[125_000, 0], [250_000, 0.02], [925_000, 0.05], [1_500_000, 0.1], [Infinity, 0.12]];
const SDLT_FTB: Band[] = [[300_000, 0], [500_000, 0.05]];
const SDLT_SURCHARGE = 0.05; // additional dwellings, from 31 Oct 2024
// Wales LTT, from 11 December 2024. No first-time buyer relief.
const LTT: Band[] = [[225_000, 0], [400_000, 0.06], [750_000, 0.075], [1_500_000, 0.1], [Infinity, 0.12]];
const LTT_HIGHER: Band[] = [[180_000, 0.05], [250_000, 0.085], [400_000, 0.1], [750_000, 0.125], [1_500_000, 0.15], [Infinity, 0.17]];

export function propertyTax(price: number, kind: BuyerKind, nation: Nation = "england") {
  if (nation === "wales") {
    const r = sliced(price, kind === "additional" ? LTT_HIGHER : LTT);
    return { ...r, name: "Land Transaction Tax", reliefApplied: false, note: kind === "ftb" ? "Wales has no first-time buyer relief." : kind === "additional" ? "Higher rates for additional homes." : "Main residential rates." };
  }
  if (kind === "ftb" && price <= 500_000) {
    return { ...sliced(price, SDLT_FTB), name: "Stamp Duty Land Tax", reliefApplied: true, note: "Includes first-time buyer relief." };
  }
  const base = sliced(price, SDLT);
  if (kind === "additional" && price >= 40_000) {
    const extra = Math.round(price * SDLT_SURCHARGE);
    return { tax: base.tax + extra, rows: [...base.rows, { from: 0, to: price, rate: SDLT_SURCHARGE, tax: extra }], name: "Stamp Duty Land Tax", reliefApplied: false, note: "Includes the 5% surcharge for additional homes." };
  }
  return { ...base, name: "Stamp Duty Land Tax", reliefApplied: false, note: kind === "ftb" ? "First-time buyer relief does not apply above £500,000." : "Standard rates." };
}

/** Monthly repayment on a capital-and-interest mortgage. */
export function monthlyRepayment(loan: number, annualRatePct: number, years: number): number {
  const r = annualRatePct / 100 / 12;
  const n = years * 12;
  if (n <= 0) return 0;
  if (r === 0) return loan / n;
  return (loan * r) / (1 - Math.pow(1 + r, -n));
}

/** Loan size from a monthly payment (inverse of monthlyRepayment). */
export function loanFromPayment(payment: number, annualRatePct: number, years: number): number {
  const r = annualRatePct / 100 / 12;
  const n = years * 12;
  if (r === 0) return payment * n;
  return (payment * (1 - Math.pow(1 + r, -n))) / r;
}
