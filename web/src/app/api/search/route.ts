import { NextResponse, type NextRequest } from "next/server";
import { search } from "@/server/search";

export async function GET(req: NextRequest) {
  const q = req.nextUrl.searchParams.get("q") ?? "";
  try {
    const hits = await search(q);
    return NextResponse.json({ hits }, { headers: { "Cache-Control": "public, max-age=300" } });
  } catch (e) {
    console.error("[api/search]", JSON.stringify(q), e);
    return NextResponse.json({ hits: [], error: "Search is unavailable" }, { status: 503 });
  }
}
