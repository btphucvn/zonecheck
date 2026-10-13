"use client";

import { useId, useState } from "react";
import { loanFromPayment, monthlyRepayment, propertyTax, type BuyerKind, type Nation } from "@/markets/uk/tools";

const gbp = (v: number) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 }).format(Math.round(v));
const parse = (s: string) => Number(s.replace(/[^\d.]/g, "")) || 0;

function MoneyInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <label htmlFor={id}>
      {label}
      <input id={id} inputMode="numeric" value={value} onChange={(e) => onChange(e.target.value)}
        onBlur={() => onChange(parse(value) ? parse(value).toLocaleString("en-GB") : "")} />
    </label>
  );
}

function NumInput({ label, value, onChange, step = 0.1 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  const id = useId();
  return (
    <label htmlFor={id}>
      {label}
      <input id={id} type="number" step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export function StampDutyCalc({ initialPrice = 300000, nation: initialNation = "england", detailed = false }: { initialPrice?: number; nation?: Nation; detailed?: boolean }) {
  const [price, setPrice] = useState(Math.round(initialPrice).toLocaleString("en-GB"));
  const [kind, setKind] = useState<BuyerKind>("ftb");
  const [nation, setNation] = useState<Nation>(initialNation);
  const p = parse(price);
  const r = propertyTax(p, kind, nation);
  return (
    <form className="calc" onSubmit={(e) => e.preventDefault()}>
      <MoneyInput label="Purchase price" value={price} onChange={setPrice} />
      <label>
        You are
        <select value={kind} onChange={(e) => setKind(e.target.value as BuyerKind)}>
          <option value="ftb">A first-time buyer</option>
          <option value="mover">Moving home</option>
          <option value="additional">Buying an additional home</option>
        </select>
      </label>
      <label>
        The home is in
        <select value={nation} onChange={(e) => setNation(e.target.value as Nation)}>
          <option value="england">England</option>
          <option value="wales">Wales</option>
        </select>
      </label>
      <div className="calc-out" aria-live="polite">
        <b>{gbp(r.tax)}</b>
        {r.name} on {gbp(p)}. {r.note} Effective rate {(p ? (r.tax / p) * 100 : 0).toFixed(1)}%.
        {detailed && r.rows.length > 0 && (
          <table className="data">
            <thead><tr><th>Band</th><th className="r">Rate</th><th className="r">Tax</th></tr></thead>
            <tbody>
              {r.rows.map((row, i) => (
                <tr key={i}>
                  <td>{row.from === 0 && row.rate === 0.05 && kind === "additional" && i === r.rows.length - 1 ? "Surcharge on whole price" : `${gbp(row.from)} to ${gbp(row.to)}`}</td>
                  <td className="r num">{(row.rate * 100).toFixed(1).replace(".0", "")}%</td>
                  <td className="r num">{gbp(row.tax)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </form>
  );
}

export function MortgageCalc() {
  const [income, setIncome] = useState("45,000");
  const [income2, setIncome2] = useState("");
  const [deposit, setDeposit] = useState("30,000");
  const [multiple, setMultiple] = useState(4.5);
  const [rate, setRate] = useState(4.5);
  const [years, setYears] = useState(30);
  const loan = (parse(income) + parse(income2)) * multiple;
  const budget = loan + parse(deposit);
  const pay = monthlyRepayment(loan, rate, years);
  const stress = monthlyRepayment(loan, rate + 3, years);
  return (
    <form className="calc" onSubmit={(e) => e.preventDefault()}>
      <MoneyInput label="Your annual income" value={income} onChange={setIncome} />
      <MoneyInput label="Second applicant's income" value={income2} onChange={setIncome2} />
      <MoneyInput label="Deposit" value={deposit} onChange={setDeposit} />
      <NumInput label="Income multiple" value={multiple} onChange={setMultiple} step={0.25} />
      <NumInput label="Interest rate, %" value={rate} onChange={setRate} />
      <NumInput label="Term, years" value={years} onChange={setYears} step={1} />
      <div className="calc-out" aria-live="polite">
        <b>{gbp(loan)}</b>
        Most lenders cap borrowing at 4 to 4.5 times income. With your deposit you could look at homes up to {gbp(budget)}.
        Monthly repayment about {gbp(pay)}; if rates rose by 3 points, {gbp(stress)}.
      </div>
    </form>
  );
}

export function MovingCostsCalc() {
  const [price, setPrice] = useState("300,000");
  const [kind, setKind] = useState<BuyerKind>("ftb");
  const [selling, setSelling] = useState(false);
  const p = parse(price);
  const tax = propertyTax(p, kind, "england").tax;
  const rows: [string, number][] = [
    ["Stamp duty (England)", tax],
    ["Conveyancing solicitor", 1500 + p * 0.001],
    ["Searches and Land Registry fee", 450 + (p > 500000 ? 150 : 100)],
    ["Survey (Level 2)", 450 + p * 0.0008],
    ["Mortgage arrangement fee", 999],
    ["Removals", 900 + p * 0.0012],
  ];
  if (selling) rows.push(["Estate agent (1.2% + VAT on sale)", p * 0.012 * 1.2], ["Energy certificate", 80]);
  const total = rows.reduce((s, r) => s + r[1], 0);
  return (
    <form className="calc" onSubmit={(e) => e.preventDefault()}>
      <MoneyInput label="Price of the home you're buying" value={price} onChange={setPrice} />
      <label>
        You are
        <select value={kind} onChange={(e) => setKind(e.target.value as BuyerKind)}>
          <option value="ftb">A first-time buyer</option>
          <option value="mover">Moving home</option>
          <option value="additional">Buying an additional home</option>
        </select>
      </label>
      <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input type="checkbox" checked={selling} onChange={(e) => setSelling(e.target.checked)} style={{ width: "auto" }} />
        Also selling a similar home
      </label>
      <div className="calc-out" aria-live="polite">
        <b>{gbp(total)}</b>
        Typical total. Fees vary by firm and region; get quotes.
        <table className="data">
          <tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td className="r num">{gbp(v)}</td></tr>)}</tbody>
        </table>
      </div>
    </form>
  );
}

export function RentVsBuyCalc({ initialPrice = 300000, initialRent = 1300 }: { initialPrice?: number; initialRent?: number }) {
  const [price, setPrice] = useState(initialPrice.toLocaleString("en-GB"));
  const [rent, setRent] = useState(initialRent.toLocaleString("en-GB"));
  const [depositPct, setDepositPct] = useState(10);
  const [rate, setRate] = useState(4.5);
  const [growth, setGrowth] = useState(3);
  const [rentGrowth, setRentGrowth] = useState(4);
  const [years, setYears] = useState(10);
  const p = parse(price);
  const dep = (p * depositPct) / 100;
  const loan = p - dep;
  const pay = monthlyRepayment(loan, rate, 30);
  // Owner: interest + upkeep (1%/yr) + buying costs − equity gained. Renter: rent paid − returns on the deposit (4%/yr).
  let balance = loan, rentPaid = 0, interest = 0, r = parse(rent) * 12;
  for (let y = 0; y < years; y++) {
    for (let m = 0; m < 12; m++) {
      const i = (balance * rate) / 100 / 12;
      interest += i;
      balance -= pay - i;
    }
    rentPaid += r;
    r *= 1 + rentGrowth / 100;
  }
  const value = p * Math.pow(1 + growth / 100, years);
  const buyCost = interest + p * 0.01 * years + propertyTax(p, "ftb").tax + 3000 + value * 0.015 - (value - p);
  const rentCost = rentPaid - dep * (Math.pow(1.04, years) - 1);
  const cheaper = buyCost < rentCost ? "Buying" : "Renting";
  return (
    <form className="calc" onSubmit={(e) => e.preventDefault()}>
      <MoneyInput label="Home price" value={price} onChange={setPrice} />
      <MoneyInput label="Monthly rent for a similar home" value={rent} onChange={setRent} />
      <NumInput label="Deposit, %" value={depositPct} onChange={setDepositPct} step={1} />
      <NumInput label="Mortgage rate, %" value={rate} onChange={setRate} />
      <NumInput label="House price growth, %/yr" value={growth} onChange={setGrowth} />
      <NumInput label="Rent growth, %/yr" value={rentGrowth} onChange={setRentGrowth} />
      <NumInput label="Years" value={years} onChange={setYears} step={1} />
      <div className="calc-out" aria-live="polite">
        <b>{cheaper} is cheaper by {gbp(Math.abs(buyCost - rentCost))}</b>
        Over {years} years, buying costs about {gbp(buyCost)} after the equity you build; renting costs {gbp(rentCost)} after returns on the deposit you keep. Mortgage payment {gbp(pay)} a month.
        <span className="m-src" style={{ display: "block" }}>Buying includes interest, 1% a year upkeep, stamp duty, fees and selling costs. Returns on savings assumed at 4% a year.</span>
      </div>
    </form>
  );
}

export { loanFromPayment };
