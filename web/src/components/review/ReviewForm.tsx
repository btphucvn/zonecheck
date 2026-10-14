"use client";

import { useState } from "react";
import { ASPECTS, RELATIONS, TAGS, validateReview, type Aspect, type ReviewInput } from "@/lib/reviewModel";

// Resident review form: eight aspects from 1 to 10 (any can be skipped, at least five), tags, the review and what
// could be better. Sent to /api/reviews; nothing appears on the site until a moderator approves it.

export function ReviewForm({ postcode: initial }: { postcode: string }) {
  const [startedAt] = useState(() => Date.now());
  const [ratings, setRatings] = useState<Partial<Record<Aspect, number | null>>>({});
  const [tags, setTags] = useState<string[]>([]);
  const [state, setState] = useState<{ status: "idle" | "sending" | "done" | "error"; msg?: string }>({ status: "idle" });

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const x: ReviewInput = {
      postcode: String(f.get("postcode") ?? "").toUpperCase().replace(/\s+/g, " ").trim(), ratings, tags,
      title: String(f.get("title") ?? ""), body: String(f.get("body") ?? ""), improve: String(f.get("improve") ?? ""),
      author: String(f.get("author") ?? ""), relation: String(f.get("relation") ?? ""), years: String(f.get("years") ?? ""),
      website: String(f.get("website") ?? ""), startedAt,
    };
    const err = validateReview(x);
    if (err) return setState({ status: "error", msg: err });
    setState({ status: "sending" });
    const r = await fetch("/api/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(x) }).catch(() => null);
    const j = r ? await r.json().catch(() => ({})) : {};
    if (r?.ok) setState({ status: "done" });
    else setState({ status: "error", msg: j.error ?? "Could not send the review. Please try again." });
  }

  if (state.status === "done") {
    return <div className="rv-done" role="status"><h2>Thank you</h2><p>Your review has been received. We read every review before it appears, usually within a few days.</p></div>;
  }
  return (
    <form className="rv-form" onSubmit={submit} noValidate>
      <label>Postcode of the street you are reviewing<input name="postcode" defaultValue={initial} required autoComplete="postal-code" /></label>
      <fieldset>
        <legend>How you know the area</legend>
        {RELATIONS.map(([k, label]) => <label key={k} className="rv-inline"><input type="radio" name="relation" value={k} defaultChecked={k === "resident"} /> {label}</label>)}
        <label>How long (optional)<select name="years" defaultValue=""><option value="">Prefer not to say</option><option>Less than a year</option><option>1 to 3 years</option><option>3 to 10 years</option><option>More than 10 years</option></select></label>
      </fieldset>
      <fieldset>
        <legend>Rate the area from 1 (poor) to 10 (excellent). Skip any you can&rsquo;t judge.</legend>
        {ASPECTS.map(([k, label]) => (
          <div key={k} className="rv-rate">
            <span>{label}</span>
            <div className="rv-scale" role="radiogroup" aria-label={label}>
              {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => (
                <button key={v} type="button" role="radio" aria-checked={ratings[k] === v} className={ratings[k] === v ? "on" : undefined}
                  onClick={() => setRatings((r) => ({ ...r, [k]: r[k] === v ? null : v }))}>{v}</button>
              ))}
            </div>
          </div>
        ))}
      </fieldset>
      <fieldset>
        <legend>Words that describe it (up to six)</legend>
        <div className="rv-tags">
          {TAGS.map((t) => (
            <button key={t} type="button" aria-pressed={tags.includes(t)} className={tags.includes(t) ? "on" : undefined}
              onClick={() => setTags((x) => (x.includes(t) ? x.filter((y) => y !== t) : x.length < 6 ? [...x, t] : x))}>{t}</button>
          ))}
        </div>
      </fieldset>
      <label>Title<input name="title" maxLength={120} required placeholder="e.g. Friendly streets, great park, busy high road" /></label>
      <label>Your review<textarea name="body" rows={6} maxLength={4000} required placeholder="What is it like to live here? Think about safety, noise, neighbours, shops, transport and green space." /></label>
      <label>Things to improve (optional)<textarea name="improve" rows={3} maxLength={2000} /></label>
      <label>Display name<input name="author" maxLength={40} required placeholder="First name or nickname" /></label>
      <input name="website" tabIndex={-1} autoComplete="off" className="rv-hp" aria-hidden="true" />
      <p className="m-src">Please don&rsquo;t name individuals or give house numbers. Reviews are checked before they appear and may be edited for length.</p>
      {state.status === "error" && <p className="rv-err" role="alert">{state.msg}</p>}
      <button className="btn" type="submit" disabled={state.status === "sending"}>{state.status === "sending" ? "Sending…" : "Send review"}</button>
    </form>
  );
}
