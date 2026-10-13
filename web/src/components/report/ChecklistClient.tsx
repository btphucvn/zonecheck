"use client";

import { useEffect, useState } from "react";
import { MapGlyph, type GlyphKind } from "./glyphs";

export interface ChecklistItem { text: string; glyph?: GlyphKind }

/** Tick-off list; ticks are remembered in this browser only (a convenience, never required). */
export function ChecklistClient({ storageKey, groups, doneLabel }: {
  storageKey: string;
  groups: { title: string; items: ChecklistItem[] }[];
  doneLabel: string;
}) {
  const [done, setDone] = useState<string[]>([]);
  useEffect(() => {
    // Hydrate from storage after mount so server and first client render match.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    try { setDone(JSON.parse(localStorage.getItem(storageKey) ?? "[]")); } catch { /* storage blocked */ }
  }, [storageKey]);
  const toggle = (text: string) => setDone((d) => {
    const next = d.includes(text) ? d.filter((x) => x !== text) : [...d, text];
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* storage blocked */ }
    return next;
  });
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const ticked = groups.reduce((n, g) => n + g.items.filter((i) => done.includes(i.text)).length, 0);
  return (
    <div className="offer-list">
      {groups.map((g) => (
        <fieldset key={g.title}>
          <legend>{g.title}</legend>
          {g.items.map((i) => (
            <label key={i.text} className={done.includes(i.text) ? "on" : undefined}>
              <input type="checkbox" checked={done.includes(i.text)} onChange={() => toggle(i.text)} />
              {i.glyph ? <MapGlyph kind={i.glyph} /> : <span aria-hidden="true" />}
              <span>{i.text}</span>
            </label>
          ))}
        </fieldset>
      ))}
      <p className="offer-count" aria-live="polite">{doneLabel.replace("{n}", String(ticked)).replace("{total}", String(total))}</p>
    </div>
  );
}
