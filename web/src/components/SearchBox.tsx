"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

interface Hit { kind: string; label: string; detail: string; href: string }

/** Bold the part of `label` the user typed ("se15 4" in "Choumert Road, London, SE15 4AA"). */
function highlight(label: string, q: string) {
  const query = q.trim().replace(/\s+/g, " ");
  const i = query ? label.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (i < 0) return label;
  return <>{label.slice(0, i)}<strong>{label.slice(i, i + query.length)}</strong>{label.slice(i + query.length)}</>;
}

export function SearchBox({ size, labels }: {
  size: "big" | "small";
  labels: { label: string; placeholder: string; button?: string; noResults: string; searching: string; error: string };
}) {
  const router = useRouter();
  const id = useId();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const box = useRef<HTMLFormElement>(null);
  const reqId = useRef(0);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) return;
    const my = ++reqId.current;
    const timer = setTimeout(async () => {
      setState("loading");
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        if (!r.ok) throw new Error(String(r.status));
        const data = (await r.json()) as { hits: Hit[] };
        if (my !== reqId.current) return;
        setHits(data.hits);
        setActive(data.hits.length ? 0 : -1);
        setState("idle");
      } catch {
        if (my === reqId.current) setState("error");
      }
    }, 180);
    return () => clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (h: Hit) => {
    setOpen(false);
    setQ("");
    setHits(null);
    router.push(h.href);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!hits?.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => (a + 1) % hits.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + hits.length) % hits.length); }
    else if (e.key === "Escape") setOpen(false);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (hits?.length && open) return go(hits[Math.max(active, 0)]);
    const query = q.trim();
    if (query.length < 2) return;
    setState("loading");
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
      const data = (await r.json()) as { hits: Hit[] };
      setState("idle");
      if (data.hits.length) go(data.hits[0]);
      else { setHits([]); setOpen(true); }
    } catch {
      setState("error");
      setOpen(true);
    }
  };

  const listId = `${id}-list`;
  const showList = open && q.trim().length >= 2 && (hits !== null || state !== "idle");
  return (
    <form ref={box} className={`search ${size}`} role="search" onSubmit={submit}>
      <div className="search-box">
        <label className="sr" htmlFor={`${id}-q`}>{labels.label}</label>
        <input
          id={`${id}-q`}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder={labels.placeholder}
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${id}-o${active}` : undefined}
        />
        {labels.button && <button type="submit">{labels.button}</button>}
      </div>
      {showList && (
        <ul className="suggest-list" id={listId} role="listbox">
          {state === "error" && <li className="empty">{labels.error}</li>}
          {state !== "error" && hits?.length === 0 && <li className="empty">{labels.noResults.replace("{q}", q.trim())}</li>}
          {state === "loading" && !hits && <li className="empty">{labels.searching}</li>}
          {hits?.map((h, i) => (
            <li key={h.href + i} role="presentation">
              <a
                id={`${id}-o${i}`}
                role="option"
                aria-selected={i === active}
                href={h.href}
                onClick={(e) => { e.preventDefault(); go(h); }}
                onMouseEnter={() => setActive(i)}
              >
                <span>{highlight(h.label, q)}</span>
                <span className="kind">{h.detail}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}
