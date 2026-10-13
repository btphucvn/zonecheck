import "server-only";
import { readFileSync, statSync } from "node:fs";
import path from "node:path";

// Fallback percentiles while the ETL scoring step has not filled
// core.metric_value.percentile yet. `npm run quantiles` writes one file per
// level: { computedAt, metrics: { [metricId]: number[101] } } (0th..100th).

const DIR = path.join(process.cwd(), "data", "quantiles");
const memo = new Map<string, { mtime: number; q: Record<string, number[]> }>();

function load(level: string): Record<string, number[]> | null {
  const file = path.join(DIR, `${level}.json`);
  try {
    const mtime = statSync(file).mtimeMs;
    const hit = memo.get(level);
    if (hit && hit.mtime === mtime) return hit.q;
    const q = JSON.parse(readFileSync(file, "utf8")).metrics as Record<string, number[]>;
    memo.set(level, { mtime, q });
    return q;
  } catch {
    return null;
  }
}

/** Percentile (0–100) of `v` among areas of `level`, or null when no table exists. */
export function fallbackPercentile(level: string, metricId: string, v: number | null): number | null {
  if (v == null) return null;
  const q = load(level)?.[metricId];
  if (!q || q.length < 2) return null;
  if (v <= q[0]) return 0;
  if (v >= q[q.length - 1]) return 100;
  let lo = 0, hi = q.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (q[mid] <= v) lo = mid; else hi = mid;
  }
  // ties: many areas share the same value (e.g. 0 crimes) → take the middle of the run
  let first = lo;
  while (first > 0 && q[first - 1] === q[lo]) first--;
  const span = q[hi] - q[lo];
  const frac = span > 0 ? (v - q[lo]) / span : 0;
  const pos = q[lo] === v && first < lo ? (first + lo) / 2 : lo + frac;
  return Math.round((pos / (q.length - 1)) * 1000) / 10;
}
