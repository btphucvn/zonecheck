import { Metric } from "./bits";
import { fmtMetric, goodness, mv, rankText, srcLine, val, type H } from "./helpers";

/** Metric tile straight from the registry: value, scale bar, rank wording, source. */
export function M({ h, id, name, note, map }: { h: H; id: string; name?: string; note?: string; map?: H["r"]["metrics"] }) {
  const m = map ?? h.r.metrics;
  const v = mv(m, id);
  if (!v || v.v == null) return null;
  const rank = map ? undefined : rankText(h, id);
  const { head, ctx } = h.r;
  // Counts (sales, people) scale with area size, so a sector vs its borough says nothing.
  const comparable = !map && h.cat[id]?.valueType !== "count";
  const wider: [string | undefined, H["r"]["metrics"]][] = !comparable ? [] : [
    [head.level !== "lad" ? ctx.lad?.name : undefined, h.r.ladMetrics],
    [head.level !== "nation" ? ctx.nation?.name : undefined, h.r.nationMetrics],
  ];
  const rows = [
    { label: head.level === "postcode_unit" ? h.t.report.thisArea : head.name, v: v.v, text: fmtMetric(h, id, v.v), self: true },
    ...wider.flatMap(([label, mm]) => {
      const x = label ? val(mm, id) : null;
      return x == null ? [] : [{ label: label!, v: x, text: fmtMetric(h, id, x) }];
    }),
  ];
  return (
    <Metric
      name={name ?? h.cat[id]?.shortName ?? h.cat[id]?.name ?? id}
      value={fmtMetric(h, id, v.v)}
      p={map ? undefined : goodness(h, id)}
      compare={map ? undefined : { rows: comparable ? rows : [], neutral: !h.cat[id]?.direction }}
      pLabel={rank}
      note={[rank, note].filter(Boolean).join(". ") || undefined}
      src={srcLine(h, id, m)}
    />
  );
}
