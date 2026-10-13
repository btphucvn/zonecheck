// Map markers drawn on a canvas at runtime (no sprite sheet to host). Image ids
// are self-describing, e.g. "zc|school|2|S" or "zc|gp", and are created on
// demand from MapLibre's `styleimagemissing` event.

import type { Map as MlMap } from "maplibre-gl";

// The basemap is always light, so marker and label colours are fixed rather than themed.
export const MAP_INK = "#13233a";
export const OFSTED_COLORS: Record<number, string> = { 1: "#2f7d4f", 2: "#2b6cb0", 3: "#c98a0b", 4: "#b83a2e", 0: "#6b7a8c" };
export const AMENITY_STYLE: Record<string, { color: string; glyph: string; label: string }> = {
  "health.gp": { color: "#1f6b4a", glyph: "cross", label: "GP practice" },
  "health.pharmacy": { color: "#2a9d6f", glyph: "pill", label: "Pharmacy" },
  "health.dentist": { color: "#5b8a2e", glyph: "tooth", label: "Dentist" },
  "shop.supermarket": { color: "#b7791f", glyph: "basket", label: "Supermarket" },
};

const S = 2; // pixel ratio
const SIZE = 30;

function badge(ctx: CanvasRenderingContext2D, color: string, shape: "round" | "square") {
  const r = SIZE / 2 - 2;
  ctx.fillStyle = color;
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  if (shape === "round") ctx.arc(SIZE / 2, SIZE / 2, r, 0, Math.PI * 2);
  else ctx.roundRect(2, 2, SIZE - 4, SIZE - 4, 6);
  ctx.fill();
  ctx.stroke();
}

function text(ctx: CanvasRenderingContext2D, t: string, size = 13) {
  ctx.fillStyle = "#ffffff";
  ctx.font = `800 ${size}px system-ui, -apple-system, Segoe UI, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(t, SIZE / 2, SIZE / 2 + 1);
}

function glyph(ctx: CanvasRenderingContext2D, g: string) {
  const c = SIZE / 2;
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#ffffff";
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  switch (g) {
    case "cross":
      ctx.fillRect(c - 2.5, c - 8, 5, 16);
      ctx.fillRect(c - 8, c - 2.5, 16, 5);
      break;
    case "pill":
      ctx.save();
      ctx.translate(c, c);
      ctx.rotate(-Math.PI / 4);
      ctx.beginPath();
      ctx.roundRect(-9, -4.5, 18, 9, 4.5);
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillRect(0, -4.5, 9, 9);
      ctx.restore();
      break;
    case "tooth":
      ctx.beginPath();
      ctx.moveTo(c - 7, c - 5);
      ctx.quadraticCurveTo(c - 7, c - 9, c - 3, c - 8);
      ctx.quadraticCurveTo(c, c - 7, c + 3, c - 8);
      ctx.quadraticCurveTo(c + 7, c - 9, c + 7, c - 5);
      ctx.quadraticCurveTo(c + 7, c, c + 4, c + 8);
      ctx.lineTo(c + 1, c + 1);
      ctx.lineTo(c - 1, c + 1);
      ctx.lineTo(c - 4, c + 8);
      ctx.quadraticCurveTo(c - 7, c, c - 7, c - 5);
      ctx.fill();
      break;
    case "basket":
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(c - 8, c - 3);
      ctx.lineTo(c + 8, c - 3);
      ctx.lineTo(c + 6, c + 7);
      ctx.lineTo(c - 6, c + 7);
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(c - 4, c - 3);
      ctx.lineTo(c - 1, c - 9);
      ctx.moveTo(c + 4, c - 3);
      ctx.lineTo(c + 1, c - 9);
      ctx.stroke();
      break;
    case "rail": {
      // British Rail double arrow, simplified
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.moveTo(c - 9, c - 3.5); ctx.lineTo(c + 9, c - 3.5);
      ctx.moveTo(c - 9, c + 3.5); ctx.lineTo(c + 9, c + 3.5);
      ctx.moveTo(c - 3, c - 9); ctx.lineTo(c + 4, c - 3.5); ctx.lineTo(c - 3, c + 3.5);
      ctx.moveTo(c + 3, c - 3.5); ctx.lineTo(c - 4, c + 3.5); ctx.lineTo(c + 3, c + 9);
      ctx.stroke();
      break;
    }
    default:
      text(ctx, g);
  }
}

function draw(id: string): ImageData | null {
  const parts = id.split("|");
  if (parts[0] !== "zc") return null;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE * S;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(S, S);
  const [, kind, a, b] = parts;
  if (kind === "school") {
    badge(ctx, OFSTED_COLORS[Number(a)] ?? OFSTED_COLORS[0], "square");
    text(ctx, b || "S", 14);
  } else if (kind === "rail") {
    badge(ctx, "#c8102e", "round");
    glyph(ctx, "rail");
  } else if (kind === "metro") {
    // Underground roundel
    ctx.lineWidth = 4.5;
    ctx.strokeStyle = "#dc241f";
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(SIZE / 2, SIZE / 2, 9, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#0019a8";
    ctx.fillRect(2, SIZE / 2 - 3, SIZE - 4, 6);
  } else if (kind === "bus") {
    ctx.fillStyle = "#ffffff";
    ctx.strokeStyle = "#c0392b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(SIZE / 2, SIZE / 2, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  } else {
    const st = AMENITY_STYLE[kind];
    if (!st) return null;
    badge(ctx, st.color, "round");
    glyph(ctx, st.glyph);
  }
  return ctx.getImageData(0, 0, SIZE * S, SIZE * S);
}

/** Lets the map create any "zc|…" icon the first time a layer asks for it. */
export function installIconFactory(m: MlMap) {
  m.on("styleimagemissing", (e: { id: string }) => {
    if (m.hasImage(e.id)) return;
    const img = draw(e.id);
    if (img) m.addImage(e.id, img, { pixelRatio: S });
  });
}

/** Data-URL of an icon for HTML (legend, essentials bar). */
export function iconUrl(id: string): string {
  if (typeof document === "undefined") return "";
  const img = draw(id);
  if (!img) return "";
  const c = document.createElement("canvas");
  c.width = img.width;
  c.height = img.height;
  c.getContext("2d")!.putImageData(img, 0, 0);
  return c.toDataURL();
}

export function phaseLetter(type: string): string {
  return type === "school.primary" ? "P" : type === "school.secondary" ? "S" : type === "school.all_through" ? "A" : type === "school.nursery" ? "N" : type === "school.post16" ? "16" : "•";
}
