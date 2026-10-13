import { NextResponse, type NextRequest } from "next/server";
import { areaLayer, crimeAreaLayer, crimeLayer, locate, metricAreaLayer, parseBBox, poiLayer, zoneLayer } from "@/server/maplayers";
import { getLadShapes, getLadValues } from "@/server/choropleth";

// GET /api/uk/map/{crime|crime-areas|metric-areas|flood|planning|green|amenities|schools|transport|areas|locate}
export async function GET(req: NextRequest, ctx: RouteContext<"/api/uk/map/[layer]">) {
  const { layer } = await ctx.params;
  const sp = req.nextUrl.searchParams;
  try {
    if (layer === "lads") {
      return new NextResponse(await getLadShapes(), { headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800" } });
    }
    if (layer === "lad-values") {
      const data = await getLadValues(sp.get("metric") ?? "");
      if (!data) return NextResponse.json({ error: "Unknown metric" }, { status: 404 });
      return NextResponse.json(data, { headers: { "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400" } });
    }
    if (layer === "locate") {
      const lon = Number(sp.get("lon")), lat = Number(sp.get("lat"));
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return NextResponse.json({ error: "lon and lat are required" }, { status: 400 });
      return NextResponse.json(await locate(lon, lat), { headers: { "Cache-Control": "public, max-age=86400" } });
    }
    const bbox = parseBBox(sp.get("bbox"));
    if (!bbox) return NextResponse.json({ error: "bbox must be x0,y0,x1,y1 inside Great Britain and at most 0.5° × 0.3°" }, { status: 400 });
    let data: unknown = null;
    if (layer === "crime") data = await crimeLayer(bbox);
    else if (layer === "crime-areas") data = await crimeAreaLayer(bbox);
    else if (layer === "metric-areas") data = await metricAreaLayer(bbox, (sp.get("m") ?? "").split(","));
    else if (layer === "flood" || layer === "planning" || layer === "green") data = await zoneLayer(layer, bbox);
    else if (layer === "amenities" || layer === "schools" || layer === "transport") data = await poiLayer(layer, bbox);
    else if (layer === "areas") data = await areaLayer(sp.get("level") ?? "sector", bbox);
    if (!data) return NextResponse.json({ error: `Unknown layer "${layer}"` }, { status: 404 });
    return NextResponse.json(data, { headers: { "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400" } });
  } catch (e) {
    console.error(`[api/uk/map/${layer}]`, sp.toString(), e);
    return NextResponse.json({ error: "Map data is unavailable right now" }, { status: 503 });
  }
}
