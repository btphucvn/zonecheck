"use client";

import { useEffect, useState } from "react";

/** Highlights the table-of-contents entry for the section in view. */
export function TocSpy({ items }: { items: { id: string; label: string }[] }) {
  const [current, setCurrent] = useState(items[0]?.id);
  useEffect(() => {
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => { if (e.isIntersecting) setCurrent(e.target.id.replace("report-", "")); }),
      { rootMargin: "-30% 0px -60% 0px" },
    );
    items.forEach((i) => { const el = document.getElementById(`report-${i.id}`); if (el) io.observe(el); });
    return () => io.disconnect();
  }, [items]);
  return (
    <nav className="toc" aria-label="Report sections">
      <ol>
        {items.map((i) => (
          <li key={i.id}><a href={`#report-${i.id}`} className={current === i.id ? "on" : undefined} aria-current={current === i.id ? "location" : undefined}>{i.label}</a></li>
        ))}
      </ol>
    </nav>
  );
}

export function ShareButton({ label, copied }: { label: string; copied: string }) {
  const [done, setDone] = useState(false);
  const share = async () => {
    const url = location.href.split("#")[0];
    try {
      if (navigator.share) await navigator.share({ url, title: document.title });
      else { await navigator.clipboard.writeText(url); setDone(true); }
    } catch { /* dismissed */ }
  };
  return <button type="button" className="btn" onClick={share}>{done ? copied : label}</button>;
}

export function PrintButton({ label }: { label: string }) {
  return <button type="button" className="btn" onClick={() => window.print()}>{label}</button>;
}
