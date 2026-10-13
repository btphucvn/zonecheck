"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

// Per-viewer conveniences kept in localStorage: chosen persona and the compare
// list. Both render a sensible default when storage is unavailable.

export interface CompareItem {
  level: string; // URL segment: sector, district, town, area, region, postcode
  slug: string;
  label: string;
}

interface Ctx {
  persona: string;
  setPersona: (p: string) => void;
  compare: CompareItem[];
  toggleCompare: (item: CompareItem) => boolean;
  removeCompare: (key: string) => void;
}

const AppCtx = createContext<Ctx | null>(null);
export const MAX_COMPARE = 4;
export const itemKey = (i: { level: string; slug: string }) => `${i.level}:${i.slug}`;

function read<T>(k: string, fallback: T): T {
  try {
    const v = localStorage.getItem(k);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function write(k: string, v: unknown) {
  try {
    localStorage.setItem(k, JSON.stringify(v));
  } catch {
    /* private mode: keep in memory only */
  }
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [persona, setPersonaState] = useState("buyer");
  const [compare, setCompare] = useState<CompareItem[]>([]);

  useEffect(() => {
    // Hydrate from storage after mount so server and first client render match.
    /* eslint-disable react-hooks/set-state-in-effect */
    setPersonaState(read("zc:persona", "buyer"));
    setCompare(read<CompareItem[]>("zc:compare", []).slice(0, MAX_COMPARE));
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const setPersona = useCallback((p: string) => {
    setPersonaState(p);
    write("zc:persona", p);
  }, []);

  const toggleCompare = useCallback((item: CompareItem) => {
    const k = itemKey(item);
    let next: CompareItem[];
    if (compare.some((c) => itemKey(c) === k)) next = compare.filter((c) => itemKey(c) !== k);
    else if (compare.length >= MAX_COMPARE) return false;
    else next = [...compare, item];
    setCompare(next);
    write("zc:compare", next);
    return true;
  }, [compare]);

  const removeCompare = useCallback((k: string) => {
    setCompare((cur) => {
      const next = cur.filter((c) => itemKey(c) !== k);
      write("zc:compare", next);
      return next;
    });
  }, []);

  const value = useMemo(() => ({ persona, setPersona, compare, toggleCompare, removeCompare }), [persona, setPersona, compare, toggleCompare, removeCompare]);
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp(): Ctx {
  const c = useContext(AppCtx);
  if (!c) throw new Error("useApp outside <Providers>");
  return c;
}
