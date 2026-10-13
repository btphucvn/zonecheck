-- Kiểm tra chất lượng dữ liệu UK sau khi nạp. Chạy: ./auth_key/vps/psql.sh < get-data/uk/audit.sql
-- Mỗi truy vấn in ra "vấn đề" (nếu rỗng/0 là tốt) hoặc số liệu tổng quan để so với nguồn.
\pset footer off
\timing off

\echo '== 1. Release theo trạng thái'
SELECT d.id AS dataset, r.version_label, r.status, r.row_count
FROM ops.dataset d LEFT JOIN LATERAL (
    SELECT * FROM ops.dataset_release r WHERE r.dataset_id = d.id ORDER BY r.id DESC LIMIT 1) r ON true
WHERE d.id LIKE 'uk.%' ORDER BY r.status NULLS FIRST, d.id;

\echo '== 2. geo_area theo cấp (thiếu centroid / geom)'
SELECT level_code, count(*) total, count(*) FILTER (WHERE is_active) active,
       count(geom) with_geom, count(*) FILTER (WHERE NOT ST_Intersects(centroid, ST_MakeEnvelope(-9, 49.8, 2.1, 61, 4326))) outside_uk_bbox
FROM core.geo_area WHERE market_code = 'uk' GROUP BY 1 ORDER BY 1;

\echo '== 3. Cấp không có cha (liên kết thiếu)'
SELECT c.level_code, count(*) AS no_parent
FROM core.geo_area c
WHERE c.market_code = 'uk' AND c.is_active AND c.level_code IN ('oa', 'lsoa', 'msoa', 'lad', 'sector', 'district', 'town')
  AND NOT EXISTS (SELECT 1 FROM core.geo_area_link l WHERE l.child_id = c.id)
GROUP BY 1;

\echo '== 4. POI theo loại (đang mở, thiếu area_id, ngoài UK)'
SELECT type_code, count(*) FILTER (WHERE status = 'open') open, count(*) total,
       count(*) FILTER (WHERE area_id IS NULL) no_area,
       count(*) FILTER (WHERE NOT ST_Intersects(geom, ST_MakeEnvelope(-9, 49.8, 2.1, 61, 4326))) outside_uk_bbox
FROM core.poi WHERE market_code = 'uk' GROUP BY 1 ORDER BY 1;

\echo '== 5. Rating: phân bố grade hiện hành (grade_rank NULL = dữ liệu lạ)'
SELECT scheme, count(*) total, count(*) FILTER (WHERE is_current) current,
       count(*) FILTER (WHERE grade_rank IS NULL) null_rank, min(rated_on), max(rated_on)
FROM core.poi_rating GROUP BY 1 ORDER BY 1;

\echo '== 6. Chỉ số: số khu, kỳ, min/max (phát hiện giá trị vô lý)'
SELECT m.id, m.native_level, count(DISTINCT v.area_id) areas, count(DISTINCT v.period) periods,
       min(v.period) first_period, max(v.period) last_period,
       round(min(v.value_num)::numeric, 2) min_v, round(max(v.value_num)::numeric, 2) max_v,
       count(*) FILTER (WHERE v.value_num IS NULL) null_v
FROM core.metric m LEFT JOIN core.metric_value v ON v.market_code = 'uk' AND v.metric_id = m.id
WHERE m.market_code = 'uk'
GROUP BY 1, 2 ORDER BY 1;

\echo '== 7. Postcode: trạng thái, thiếu toạ độ'
SELECT status, country_code, count(*), count(geom) with_geom, count(lsoa21_code) with_lsoa
FROM mkt_uk.postcode GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 8. Tội phạm theo tháng (tháng đầu/cuối, số lực lượng)'
SELECT min(month), max(month), count(*) AS incidents, count(DISTINCT reported_by) forces,
       count(*) FILTER (WHERE geom IS NULL) no_geom, count(*) FILTER (WHERE lsoa21_code IS NULL) no_lsoa
FROM mkt_uk.crime_incident;
SELECT police_force, count(*) months_missing, min(month), max(month) FROM mkt_uk.crime_coverage_gap GROUP BY 1;

\echo '== 9. Price Paid (năm đầu/cuối, giá vô lý, không ghép được postcode)'
SELECT min(transfer_date), max(transfer_date), count(*) total,
       count(*) FILTER (WHERE area_id IS NULL) no_postcode_match,
       count(*) FILTER (WHERE price < 1000) price_lt_1k, count(*) FILTER (WHERE price > 50000000) price_gt_50m,
       count(*) FILTER (WHERE ppd_category = 'B') cat_b
FROM mkt_uk.price_paid;

\echo '== 10. Bảng stage còn sót (phải rỗng sau khi nạp xong)'
SELECT table_name FROM information_schema.tables WHERE table_schema = 'stage_uk';

\echo '== 11. Lần chạy ETL lỗi gần đây'
SELECT id, job_name, status, started_at::timestamp(0), left(split_part(error_message, E'\n', -2), 160) AS last_error_line
FROM ops.etl_run WHERE status <> 'succeeded' ORDER BY id DESC LIMIT 10;
