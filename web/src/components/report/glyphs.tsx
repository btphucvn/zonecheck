/**
 * Map-key symbols for the risk checks, drawn the way an OS map draws them:
 * water in blue line work, ground hazards as brown hatching, land use as stipple.
 * 20×20, stroke-based, colour from the theme (water / contour / ink).
 */
export type GlyphKind = "water" | "surface" | "history" | "radon" | "coal" | "clay" | "ground" | "landfill" | "coast" | "pollution" | "planning" | "listed" | "lease" | "general";

const TINT: Record<GlyphKind, string> = {
  water: "var(--water)", surface: "var(--water)", history: "var(--water)",
  radon: "var(--contour)", coal: "var(--contour)", clay: "var(--contour)", ground: "var(--contour)",
  landfill: "var(--ink-2)", coast: "var(--contour)", pollution: "var(--ink-2)",
  planning: "var(--brand)", listed: "var(--brand)", lease: "var(--ink-2)", general: "var(--ink-2)",
};

export function MapGlyph({ kind }: { kind: GlyphKind }) {
  const body = (() => {
    switch (kind) {
      case "water": // river: three wavy lines
        return <>{[5, 10, 15].map((y) => <path key={y} d={`M2 ${y} q2 -2.5 4 0 t4 0 t4 0 t4 0`} />)}</>;
      case "surface": // ponding: one wave over a drop
        return <><path d="M10 2.5 C13 7 14.5 9 14.5 11 a4.5 4.5 0 0 1 -9 0 C5.5 9 7 7 10 2.5Z" /><path d="M2 17.5 q2 -2 4 0 t4 0 t4 0 t4 0" /></>;
      case "history": // recorded flood outline: dashed edge with a wave inside
        return <><rect x="2.5" y="2.5" width="15" height="15" rx="1" strokeDasharray="2.4 1.8" /><path d="M5 11 q1.25 -2 2.5 0 t2.5 0 t2.5 0 t2.5 0" /></>;
      case "radon": // gas rising from the ground
        return <><path d="M2 16.5 H18" /><circle cx="6" cy="11.5" r="1.4" /><circle cx="10" cy="7.5" r="1.8" /><circle cx="14.5" cy="11" r="1.2" /><circle cx="12" cy="3.5" r="1" /></>;
      case "coal": // OS mine symbol: crossed picks
        return <><path d="M4 16 L15 5" /><path d="M16 16 L5 5" /><path d="M12.5 3 q3 0.5 4.5 4.5" /><path d="M7.5 3 q-3 0.5 -4.5 4.5" /></>;
      case "clay": // diagonal hatching in a cell
        return <><rect x="2.5" y="2.5" width="15" height="15" rx="1" /><path d="M2.5 9 L9 2.5 M2.5 15 L15 2.5 M7 17.5 L17.5 7 M13 17.5 L17.5 13" /></>;
      case "ground": // landslip hachures under a slope
        return <><path d="M2 15 L9 5 L18 15" /><path d="M7 15 v-2.5 M10 15 v-4.5 M13 15 v-2.5" /></>;
      case "landfill": // OS refuse tip: stipple in a frame
        return <><rect x="2.5" y="2.5" width="15" height="15" rx="1" />{[[6, 6], [11, 6.5], [14.5, 8], [7, 11], [12, 12], [6, 15], [10, 15.5], [14.5, 14.5]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="0.9" fill="currentColor" stroke="none" />)}</>;
      case "coast": // cliff edge hachures facing the sea
        return <><path d="M2 6 H18" /><path d="M4 6 v4 M7.5 6 v6 M11 6 v4 M14.5 6 v6" /><path d="M2 16 q2 -2 4 0 t4 0 t4 0 t4 0" /></>;
      case "pollution": // outfall: pipe and spreading drop
        return <><path d="M2 6 H10 V9" /><path d="M10 11 C12 13.5 13 15 13 16 a3 3 0 0 1 -6 0 C7 15 8 13.5 10 11Z" /></>;
      case "planning": // conservation boundary: dash-dot outline
        return <rect x="2.5" y="2.5" width="15" height="15" rx="1" strokeDasharray="5 1.6 1 1.6" />;
      case "listed": // historic building
        return <><path d="M3 8 L10 3.5 L17 8" /><path d="M4.5 8 V16 M8.5 8 V16 M11.5 8 V16 M15.5 8 V16 M3 16.5 H17" /></>;
      case "lease": // document
        return <><path d="M5 2.5 H12.5 L15.5 5.5 V17.5 H5 Z" /><path d="M7.5 9 H13 M7.5 12 H13 M7.5 15 H11" /></>;
      default: // general step: a tick box outline
        return <><circle cx="10" cy="10" r="7" /><path d="M10 6.5 V10.5 L12.5 12" /></>;
    }
  })();
  return (
    <svg className="glyph" viewBox="0 0 20 20" width="22" height="22" aria-hidden="true" focusable="false"
      fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" style={{ color: TINT[kind] }}>
      {body}
    </svg>
  );
}
