import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import { scoped, sql } from "@/lib/db";
import type { MetricMeta } from "./types";

/** Metric registry with English names and data source (core.metric + translation + ops). */
export async function getMetricCatalog(market: string, locale: string): Promise<Record<string, MetricMeta>> {
  "use cache";
  cacheLife("days");
  cacheTag(`market:${market}`, "metric-catalog");
  return scoped(() => loadMetricCatalog(market, locale));
}

/** Uncached variant for use inside other cache scopes (nested cached calls would be deduped across scopes). */
export async function loadMetricCatalog(market: string, locale: string): Promise<Record<string, MetricMeta>> {
  {
    const rows = await sql`
      select m.id, m.category_code, m.value_type, m.unit, m.decimals::int, m.direction::int, m.native_level,
             m.comparable_scope_id, m.is_estimate, m.is_scorable, m.sensitivity,
             coalesce(t.name, te.name, m.id) as name, coalesce(t.short_name, te.short_name) as short_name,
             coalesce(t.description, te.description) as description, coalesce(t.caveats, te.caveats) as caveats,
             s.name as source, s.publisher
      from core.metric m
      left join core.metric_translation t on t.metric_id = m.id and t.locale_code = ${locale}
      left join core.metric_translation te on te.metric_id = m.id and te.locale_code = 'en'
      left join ops.dataset d on d.id = m.dataset_id
      left join ops.data_source s on s.id = d.source_id
      where m.market_code = ${market} and m.status = 'active'`;
    const out: Record<string, MetricMeta> = {};
    for (const r of rows) {
      out[r.id] = {
        id: r.id, category: r.category_code, valueType: r.value_type, unit: r.unit, decimals: r.decimals,
        direction: r.direction, nativeLevel: r.native_level, scope: r.comparable_scope_id, isEstimate: r.is_estimate,
        scorable: r.is_scorable, sensitivity: r.sensitivity, name: r.name, shortName: r.short_name,
        description: r.description, caveats: r.caveats, source: r.source, publisher: r.publisher,
      };
    }
    return out;
  }
}

export interface SourceRow {
  id: string;
  name: string;
  publisher: string;
  homepage: string | null;
  licence: string;
  licenceUrl: string | null;
  attribution: string | null;
  datasets: { id: string; name: string; frequency: string; coverage: string | null; version: string | null; fetchedAt: string | null; status: string | null }[];
}

export async function getSources(market: string): Promise<SourceRow[]> {
  "use cache";
  cacheLife("hours");
  cacheTag(`market:${market}`, "sources");
  return scoped(async () => {
    const rows = await sql`
      select s.id, s.name, s.publisher, s.homepage_url, l.name as licence, l.url as licence_url, s.attribution_text,
             d.id as dataset_id, d.name as dataset_name, d.update_frequency, d.coverage,
             r.version_label, r.fetched_at::text as fetched_at, r.status
      from ops.data_source s
      join ops.licence l on l.code = s.licence_code
      left join ops.dataset d on d.source_id = s.id and d.is_active
      left join lateral (
        select version_label, fetched_at, status from ops.dataset_release r
        where r.dataset_id = d.id order by r.fetched_at desc nulls last limit 1
      ) r on true
      where (s.market_code = ${market} or s.market_code is null) and s.status = 'active'
      order by s.name, d.name`;
    const by = new Map<string, SourceRow>();
    for (const r of rows) {
      let s = by.get(r.id);
      if (!s) {
        s = { id: r.id, name: r.name, publisher: r.publisher, homepage: r.homepage_url, licence: r.licence, licenceUrl: r.licence_url, attribution: r.attribution_text, datasets: [] };
        by.set(r.id, s);
      }
      if (r.dataset_id) {
        s.datasets.push({ id: r.dataset_id, name: r.dataset_name, frequency: r.update_frequency, coverage: r.coverage, version: r.version_label, fetchedAt: r.fetched_at, status: r.status });
      }
    }
    return [...by.values()];
  });
}
