-- =============================================================================
-- ZoneCheck — Database schema (PostgreSQL 16+ / PostGIS 3.4+)
-- =============================================================================
-- Nguyên tắc thiết kế (xem PLAN.md mục 4–5):
--   1. Tách theo schema (namespace) để mở rộng độc lập:
--        ops     : nguồn dữ liệu, giấy phép, phiên bản phát hành, lịch sử ETL
--        core    : lõi không phụ thuộc quốc gia (market, locale, địa lý, chỉ số, POI, vùng, điểm số)
--        mkt_uk  : dữ liệu thô đặc thù UK (thêm mkt_us, mkt_fr khi mở market mới)
--        content : nội dung, SEO, xếp hạng, cấu hình công cụ
--        auth    : tài khoản (Better Auth)
--        app     : tính năng người dùng (watchlist, cảnh báo, review, phản hồi)
--        billing : gói trả phí, API key (dự phòng cho tương lai, chưa dùng ở giai đoạn miễn phí)
--   2. "Market" (quốc gia dữ liệu) tách khỏi "Locale" (ngôn ngữ giao diện).
--   3. Chỉ số là DỮ LIỆU (metric registry), không phải cột cố định → thêm chỉ số/quốc gia không cần migration.
--   4. Mọi giá trị đều truy được nguồn gốc (release_id → ops.dataset_release).
--   5. Bảng lớn được partition (metric_value theo market, crime theo thời gian).
--   6. Toạ độ lưu ở WGS84 (EPSG:4326). Khoảng cách tính bằng geography hoặc chiếu tạm thời.
--
-- Quy ước file (để script build_erd.py đọc được):
--   * "-- @domain <key> | <Tiêu đề> | <mô tả>" đánh dấu nhóm bảng cho sơ đồ ERD.
--   * Mỗi cột một dòng; dấu ")" đóng CREATE TABLE đứng đầu dòng.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mkt_uk;
CREATE SCHEMA IF NOT EXISTS content;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS billing;

COMMENT ON SCHEMA ops IS 'Vận hành dữ liệu: nguồn, giấy phép, dataset, phiên bản phát hành, lần chạy ETL, kiểm tra chất lượng, feature flag.';
COMMENT ON SCHEMA core IS 'Lõi đa quốc gia: market, locale, đơn vị địa lý, danh mục chỉ số, giá trị chỉ số, POI, vùng rủi ro/quy hoạch, mô hình điểm số.';
COMMENT ON SCHEMA mkt_uk IS 'Dữ liệu chi tiết đặc thù của market UK (giao dịch, EPC, tội phạm, postcode, AVM). Mỗi market mới có schema mkt_<code> riêng.';
COMMENT ON SCHEMA content IS 'Nội dung và SEO: tóm tắt AI, glossary, trang biên tập, xếp hạng, cấu hình công cụ tính toán, trạng thái index, redirect.';
COMMENT ON SCHEMA auth IS 'Bảng xác thực theo schema lõi của Better Auth (user, session, account, verification). Sinh/đồng bộ bằng Better Auth CLI.';
COMMENT ON SCHEMA app IS 'Tính năng người dùng: hồ sơ, watchlist, quy tắc và sự kiện cảnh báo, thông báo, so sánh đã lưu, review, phản hồi dữ liệu, yêu cầu gỡ bỏ.';
COMMENT ON SCHEMA billing IS 'Dự phòng kiếm tiền tương lai: gói, tính năng, subscription, API client/key, thống kê dùng API. Giai đoạn miễn phí chỉ dùng gói "free".';

-- -----------------------------------------------------------------------------
-- Hàm tiện ích dùng chung
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.normalize_text(input text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, coalesce(input, ''))) $$;
COMMENT ON FUNCTION core.normalize_text(text) IS 'Chuẩn hoá chuỗi để tìm kiếm: bỏ dấu (unaccent) + chữ thường. IMMUTABLE để dùng được trong index trigram.';

CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;
COMMENT ON FUNCTION core.set_updated_at() IS 'Trigger BEFORE UPDATE: tự cập nhật cột updated_at. Được gắn tự động cho mọi bảng có cột updated_at (khối DO cuối file).';

-- =============================================================================
-- @domain reference | Market & Locale | Quốc gia dữ liệu, ngôn ngữ giao diện và ngôn ngữ được bật cho từng market
-- =============================================================================

CREATE TABLE core.locale (
    code text PRIMARY KEY CHECK (code ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
    name_native text NOT NULL,
    name_en text NOT NULL,
    direction text NOT NULL DEFAULT 'ltr' CHECK (direction IN ('ltr', 'rtl')),
    fallback_locale text REFERENCES core.locale (code),
    is_enabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE core.locale IS 'Ngôn ngữ giao diện (BCP 47). Độc lập với market: mọi locale xem được mọi market.';
COMMENT ON COLUMN core.locale.code IS 'Mã BCP 47, ví dụ en, en-GB, vi, pl, zh-Hans, ar.';
COMMENT ON COLUMN core.locale.name_native IS 'Tên ngôn ngữ bằng chính ngôn ngữ đó (Tiếng Việt, Polski...).';
COMMENT ON COLUMN core.locale.name_en IS 'Tên ngôn ngữ bằng tiếng Anh.';
COMMENT ON COLUMN core.locale.direction IS 'Hướng chữ: ltr hoặc rtl (Ả Rập, Urdu).';
COMMENT ON COLUMN core.locale.fallback_locale IS 'Locale dự phòng khi thiếu bản dịch (ví dụ en-GB → en).';
COMMENT ON COLUMN core.locale.is_enabled IS 'Bật/tắt toàn cục. Bật cho từng market ở core.market_locale.';
COMMENT ON COLUMN core.locale.created_at IS 'Thời điểm tạo bản ghi.';

CREATE TABLE core.market (
    code text PRIMARY KEY CHECK (code ~ '^[a-z]{2,3}$'),
    name text NOT NULL,
    country_codes text[] NOT NULL,
    currency_code char(3) NOT NULL,
    default_locale text NOT NULL REFERENCES core.locale (code),
    distance_unit text NOT NULL DEFAULT 'km' CHECK (distance_unit IN ('km', 'mi')),
    area_unit text NOT NULL DEFAULT 'm2' CHECK (area_unit IN ('m2', 'ft2')),
    timezone text NOT NULL,
    status text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'beta', 'live', 'retired')),
    launched_at timestamptz,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE core.market IS 'Thị trường dữ liệu (quốc gia). Mỗi market có bộ cấp địa lý, nguồn dữ liệu, chỉ số và adapter code riêng (packages/markets/<code>).';
COMMENT ON COLUMN core.market.code IS 'Mã market dùng trong URL và tên schema: uk, us, fr.';
COMMENT ON COLUMN core.market.name IS 'Tên hiển thị nội bộ (United Kingdom).';
COMMENT ON COLUMN core.market.country_codes IS 'Danh sách mã ISO 3166-1 alpha-2 thuộc market (UK: {GB}).';
COMMENT ON COLUMN core.market.currency_code IS 'Mã tiền tệ ISO 4217 dùng để hiển thị giá (GBP, USD, EUR).';
COMMENT ON COLUMN core.market.default_locale IS 'Locale mặc định của market (en-GB).';
COMMENT ON COLUMN core.market.distance_unit IS 'Đơn vị khoảng cách mặc định khi hiển thị (UK, US: mi; FR: km). Người dùng có thể đổi.';
COMMENT ON COLUMN core.market.area_unit IS 'Đơn vị diện tích mặc định (m2 hoặc ft2).';
COMMENT ON COLUMN core.market.timezone IS 'Múi giờ IANA (Europe/London) cho lịch ETL và hiển thị ngày.';
COMMENT ON COLUMN core.market.status IS 'planned / beta / live / retired.';
COMMENT ON COLUMN core.market.launched_at IS 'Thời điểm ra mắt công khai.';
COMMENT ON COLUMN core.market.config IS 'Cấu hình riêng của market (ngưỡng mẫu, quy tắc index, tuỳ chọn hiển thị). Ưu tiên cột riêng khi cấu hình ổn định.';
COMMENT ON COLUMN core.market.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN core.market.updated_at IS 'Thời điểm cập nhật cuối (trigger).';

CREATE TABLE core.market_locale (
    market_code text NOT NULL REFERENCES core.market (code),
    locale_code text NOT NULL REFERENCES core.locale (code),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'beta', 'live')),
    is_default boolean NOT NULL DEFAULT false,
    path_prefix text,
    launched_at timestamptz,
    PRIMARY KEY (market_code, locale_code)
);
COMMENT ON TABLE core.market_locale IS 'Ngôn ngữ được bật cho từng market và trạng thái phát hành (dùng cho định tuyến, sitemap, hreflang).';
COMMENT ON COLUMN core.market_locale.market_code IS 'Market.';
COMMENT ON COLUMN core.market_locale.locale_code IS 'Locale được bật cho market.';
COMMENT ON COLUMN core.market_locale.status IS 'draft (chưa công khai) / beta (noindex) / live (index + hreflang).';
COMMENT ON COLUMN core.market_locale.is_default IS 'Locale mặc định của market (không có tiền tố URL khi dùng localePrefix as-needed).';
COMMENT ON COLUMN core.market_locale.path_prefix IS 'Tiền tố URL, ví dụ /pl. NULL = không có tiền tố.';
COMMENT ON COLUMN core.market_locale.launched_at IS 'Thời điểm mở công khai locale này cho market.';

-- =============================================================================
-- @domain ops | Nguồn & dòng dữ liệu | Giấy phép, nguồn, dataset, phiên bản phát hành, ETL, kiểm tra chất lượng, feature flag
-- =============================================================================

CREATE TABLE ops.licence (
    code text PRIMARY KEY,
    name text NOT NULL,
    url text,
    allows_commercial boolean NOT NULL,
    requires_attribution boolean NOT NULL,
    is_share_alike boolean NOT NULL DEFAULT false,
    notes text
);
COMMENT ON TABLE ops.licence IS 'Danh mục giấy phép dữ liệu. Dùng để kiểm tra tự động: không cho dataset có giấy phép cấm thương mại lên trang công khai.';
COMMENT ON COLUMN ops.licence.code IS 'Mã giấy phép: OGL-UK-3.0, ODbL-1.0, CC-BY-4.0, LO-2.0, US-PD, PROPRIETARY...';
COMMENT ON COLUMN ops.licence.name IS 'Tên đầy đủ.';
COMMENT ON COLUMN ops.licence.url IS 'Đường dẫn văn bản giấy phép.';
COMMENT ON COLUMN ops.licence.allows_commercial IS 'Cho phép dùng thương mại (có quảng cáo) hay không.';
COMMENT ON COLUMN ops.licence.requires_attribution IS 'Bắt buộc ghi nguồn.';
COMMENT ON COLUMN ops.licence.is_share_alike IS 'Có điều khoản share-alike (ODbL) — không phát hành lại database dẫn xuất.';
COMMENT ON COLUMN ops.licence.notes IS 'Ghi chú pháp lý bổ sung.';

CREATE TABLE ops.data_source (
    id text PRIMARY KEY,
    market_code text REFERENCES core.market (code),
    name text NOT NULL,
    publisher text NOT NULL,
    homepage_url text,
    licence_code text NOT NULL REFERENCES ops.licence (code),
    attribution_text text,
    attribution_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
    terms_url text,
    terms_notes text,
    terms_reviewed_at date,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('evaluating', 'active', 'paused', 'retired')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.data_source IS 'Nhà cung cấp/nguồn dữ liệu (ví dụ HM Land Registry, data.police.uk). Một nguồn có nhiều dataset.';
COMMENT ON COLUMN ops.data_source.id IS 'Mã nguồn dạng <market>.<publisher>, ví dụ uk.land_registry, uk.police, global.osm.';
COMMENT ON COLUMN ops.data_source.market_code IS 'Market của nguồn. NULL = nguồn toàn cầu (OpenStreetMap).';
COMMENT ON COLUMN ops.data_source.name IS 'Tên hiển thị.';
COMMENT ON COLUMN ops.data_source.publisher IS 'Cơ quan/đơn vị phát hành.';
COMMENT ON COLUMN ops.data_source.homepage_url IS 'Trang chủ nguồn dữ liệu.';
COMMENT ON COLUMN ops.data_source.licence_code IS 'Giấy phép áp dụng.';
COMMENT ON COLUMN ops.data_source.attribution_text IS 'Câu ghi nguồn bắt buộc (hiển thị ở footer và /sources), có thể chứa {year}.';
COMMENT ON COLUMN ops.data_source.attribution_i18n IS 'Bản dịch câu ghi nguồn theo locale {"vi": "..."} nếu được phép dịch.';
COMMENT ON COLUMN ops.data_source.terms_url IS 'Đường dẫn điều khoản sử dụng.';
COMMENT ON COLUMN ops.data_source.terms_notes IS 'Kết quả rà soát pháp lý: hạn chế đặc biệt (ví dụ quyền Royal Mail trong ONSPD, cấm index giao dịch DVF).';
COMMENT ON COLUMN ops.data_source.terms_reviewed_at IS 'Ngày rà soát điều khoản gần nhất.';
COMMENT ON COLUMN ops.data_source.status IS 'evaluating (đang thẩm định giấy phép) / active / paused / retired.';
COMMENT ON COLUMN ops.data_source.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN ops.data_source.updated_at IS 'Thời điểm cập nhật cuối.';

CREATE TABLE ops.dataset (
    id text PRIMARY KEY,
    source_id text NOT NULL REFERENCES ops.data_source (id),
    name text NOT NULL,
    description text,
    update_frequency text NOT NULL CHECK (update_frequency IN ('realtime', 'daily', 'weekly', 'monthly', 'quarterly', 'semiannual', 'annual', 'irregular')),
    native_level text,
    coverage text,
    loader_module text,
    is_active boolean NOT NULL DEFAULT true,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.dataset IS 'Bộ dữ liệu cụ thể trong một nguồn (ví dụ uk.land_registry.ppd, uk.police.street_crime). Đơn vị lập lịch ETL.';
COMMENT ON COLUMN ops.dataset.id IS 'Mã dataset dạng <source_id>.<tên>.';
COMMENT ON COLUMN ops.dataset.source_id IS 'Nguồn chứa dataset.';
COMMENT ON COLUMN ops.dataset.name IS 'Tên dataset.';
COMMENT ON COLUMN ops.dataset.description IS 'Mô tả nội dung, phạm vi, lưu ý.';
COMMENT ON COLUMN ops.dataset.update_frequency IS 'Tần suất nguồn cập nhật: realtime/daily/weekly/monthly/quarterly/semiannual/annual/irregular.';
COMMENT ON COLUMN ops.dataset.native_level IS 'Cấp địa lý gốc của dữ liệu (postcode_unit, lsoa, lad, point, polygon...).';
COMMENT ON COLUMN ops.dataset.coverage IS 'Phạm vi địa lý (England, E&W, UK...).';
COMMENT ON COLUMN ops.dataset.loader_module IS 'Module Python trong etl/ xử lý dataset (etl.markets.uk.sources.ppd).';
COMMENT ON COLUMN ops.dataset.is_active IS 'Còn được lập lịch chạy hay không.';
COMMENT ON COLUMN ops.dataset.config IS 'Tham số loader (URL tải, mapping cột, ngưỡng validate).';
COMMENT ON COLUMN ops.dataset.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN ops.dataset.updated_at IS 'Thời điểm cập nhật cuối.';

CREATE TABLE ops.dataset_release (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_id text NOT NULL REFERENCES ops.dataset (id),
    version_label text NOT NULL,
    period_start date,
    period_end date,
    published_at timestamptz,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    raw_uri text,
    checksum_sha256 text,
    row_count bigint,
    status text NOT NULL DEFAULT 'fetched' CHECK (status IN ('fetched', 'validated', 'loaded', 'published', 'failed', 'superseded')),
    validation_report jsonb,
    supersedes_id bigint REFERENCES ops.dataset_release (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, version_label)
);
COMMENT ON TABLE ops.dataset_release IS 'Một lần phát hành/tải về của dataset. Mọi bản ghi dữ liệu tham chiếu release_id để truy vết nguồn gốc và cho phép rollback.';
COMMENT ON COLUMN ops.dataset_release.id IS 'Khoá chính tự tăng.';
COMMENT ON COLUMN ops.dataset_release.dataset_id IS 'Dataset được phát hành.';
COMMENT ON COLUMN ops.dataset_release.version_label IS 'Nhãn phiên bản theo nguồn (2026-08, May 2026, v2...).';
COMMENT ON COLUMN ops.dataset_release.period_start IS 'Kỳ dữ liệu bắt đầu.';
COMMENT ON COLUMN ops.dataset_release.period_end IS 'Kỳ dữ liệu kết thúc (dùng để hiển thị "dữ liệu tới ngày" và sitemap lastmod).';
COMMENT ON COLUMN ops.dataset_release.published_at IS 'Thời điểm nguồn công bố.';
COMMENT ON COLUMN ops.dataset_release.fetched_at IS 'Thời điểm ta tải về.';
COMMENT ON COLUMN ops.dataset_release.raw_uri IS 'Vị trí bản gốc lưu trữ (r2://zonecheck-raw/...). Cho phép tái tạo dữ liệu.';
COMMENT ON COLUMN ops.dataset_release.checksum_sha256 IS 'SHA-256 của file gốc, phát hiện tải trùng.';
COMMENT ON COLUMN ops.dataset_release.row_count IS 'Số dòng thô.';
COMMENT ON COLUMN ops.dataset_release.status IS 'fetched → validated → loaded → published; failed; superseded khi có bản mới thay thế (ví dụ DVF thay toàn bộ).';
COMMENT ON COLUMN ops.dataset_release.validation_report IS 'Tóm tắt kết quả validate (số dòng lệch, cột thiếu...).';
COMMENT ON COLUMN ops.dataset_release.supersedes_id IS 'Release cũ bị thay thế bởi release này.';
COMMENT ON COLUMN ops.dataset_release.created_at IS 'Thời điểm tạo bản ghi.';

CREATE TABLE ops.etl_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_name text NOT NULL,
    dataset_id text REFERENCES ops.dataset (id),
    release_id bigint REFERENCES ops.dataset_release (id),
    trigger_kind text NOT NULL DEFAULT 'schedule' CHECK (trigger_kind IN ('schedule', 'manual', 'backfill', 'dependency')),
    status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    stats jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    git_sha text,
    host text
);
COMMENT ON TABLE ops.etl_run IS 'Nhật ký mỗi lần chạy job ETL (fetch, transform, aggregate, score, sitemap...). Dùng để giám sát và cảnh báo lỗi.';
COMMENT ON COLUMN ops.etl_run.id IS 'Khoá chính.';
COMMENT ON COLUMN ops.etl_run.job_name IS 'Tên job (uk.ppd.load, uk.metrics.aggregate, uk.scores.compute...).';
COMMENT ON COLUMN ops.etl_run.dataset_id IS 'Dataset liên quan (nếu có).';
COMMENT ON COLUMN ops.etl_run.release_id IS 'Release được xử lý (nếu có).';
COMMENT ON COLUMN ops.etl_run.trigger_kind IS 'schedule / manual / backfill / dependency (chạy sau job khác).';
COMMENT ON COLUMN ops.etl_run.status IS 'running / succeeded / failed / cancelled.';
COMMENT ON COLUMN ops.etl_run.started_at IS 'Bắt đầu.';
COMMENT ON COLUMN ops.etl_run.finished_at IS 'Kết thúc.';
COMMENT ON COLUMN ops.etl_run.stats IS 'Số liệu thống kê (rows_in, rows_out, duration_ms...).';
COMMENT ON COLUMN ops.etl_run.error_message IS 'Thông báo lỗi khi failed.';
COMMENT ON COLUMN ops.etl_run.git_sha IS 'Commit code ETL đã chạy (tái lập kết quả).';
COMMENT ON COLUMN ops.etl_run.host IS 'Máy chạy job.';

CREATE TABLE ops.data_quality_check (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id bigint NOT NULL REFERENCES ops.dataset_release (id) ON DELETE CASCADE,
    check_name text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info', 'warn', 'error')),
    passed boolean NOT NULL,
    observed jsonb,
    expected jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.data_quality_check IS 'Kết quả từng kiểm tra chất lượng cho một release. Lỗi severity=error chặn bước publish.';
COMMENT ON COLUMN ops.data_quality_check.id IS 'Khoá chính.';
COMMENT ON COLUMN ops.data_quality_check.release_id IS 'Release được kiểm tra.';
COMMENT ON COLUMN ops.data_quality_check.check_name IS 'Tên kiểm tra (row_count_delta, null_rate.price, coverage.lsoa...).';
COMMENT ON COLUMN ops.data_quality_check.severity IS 'info / warn / error.';
COMMENT ON COLUMN ops.data_quality_check.passed IS 'Đạt hay không.';
COMMENT ON COLUMN ops.data_quality_check.observed IS 'Giá trị quan sát.';
COMMENT ON COLUMN ops.data_quality_check.expected IS 'Giá trị/ngưỡng kỳ vọng.';
COMMENT ON COLUMN ops.data_quality_check.created_at IS 'Thời điểm kiểm tra.';

CREATE TABLE ops.feature_flag (
    key text PRIMARY KEY,
    description text,
    is_enabled boolean NOT NULL DEFAULT false,
    rollout_percent smallint NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
    rules jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.feature_flag IS 'Cờ tính năng để bật dần tính năng mới (AVM, review, ngôn ngữ mới) theo % hoặc theo market/locale.';
COMMENT ON COLUMN ops.feature_flag.key IS 'Khoá cờ (uk.avm.public, reviews.enabled...).';
COMMENT ON COLUMN ops.feature_flag.description IS 'Mô tả.';
COMMENT ON COLUMN ops.feature_flag.is_enabled IS 'Bật/tắt tổng.';
COMMENT ON COLUMN ops.feature_flag.rollout_percent IS 'Tỷ lệ người dùng được bật (0–100).';
COMMENT ON COLUMN ops.feature_flag.rules IS 'Điều kiện chi tiết: {"markets":["uk"],"locales":["en"]}.';
COMMENT ON COLUMN ops.feature_flag.updated_at IS 'Thời điểm cập nhật cuối.';

-- =============================================================================
-- @domain geo | Địa lý | Cấp địa lý theo market, đơn vị địa lý (polygon/điểm), quan hệ cha–con có trọng số, bí danh, phạm vi so sánh
-- =============================================================================

CREATE TABLE core.geo_level (
    market_code text NOT NULL REFERENCES core.market (code),
    code text NOT NULL,
    name text NOT NULL,
    name_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
    rank smallint NOT NULL,
    kind text NOT NULL CHECK (kind IN ('postal', 'statistical', 'administrative', 'settlement', 'grid', 'custom')),
    is_searchable boolean NOT NULL DEFAULT false,
    has_pages boolean NOT NULL DEFAULT false,
    url_segment text,
    boundary_vintage text,
    notes text,
    PRIMARY KEY (market_code, code)
);
COMMENT ON TABLE core.geo_level IS 'Các cấp địa lý của từng market. UK: postcode_unit, sector, district, area, oa, lsoa, msoa, lad, region, nation, town. US: zcta, tract, county, place... FR: iris, commune, departement...';
COMMENT ON COLUMN core.geo_level.market_code IS 'Market sở hữu cấp này.';
COMMENT ON COLUMN core.geo_level.code IS 'Mã cấp (postcode_unit, lsoa, lad...).';
COMMENT ON COLUMN core.geo_level.name IS 'Tên tiếng Anh.';
COMMENT ON COLUMN core.geo_level.name_i18n IS 'Tên theo locale {"vi":"Quận hành chính"}.';
COMMENT ON COLUMN core.geo_level.rank IS 'Thứ bậc: 0 = nhỏ nhất. Dùng để sắp xếp breadcrumb và chọn cấp gộp khi thiếu mẫu.';
COMMENT ON COLUMN core.geo_level.kind IS 'postal (postcode/ZIP) / statistical (LSOA, tract) / administrative (LAD, county) / settlement (town) / grid / custom.';
COMMENT ON COLUMN core.geo_level.is_searchable IS 'Xuất hiện trong kết quả tìm kiếm.';
COMMENT ON COLUMN core.geo_level.has_pages IS 'Có trang công khai riêng.';
COMMENT ON COLUMN core.geo_level.url_segment IS 'Đoạn URL của cấp (postcode, sector, district, town, area).';
COMMENT ON COLUMN core.geo_level.boundary_vintage IS 'Phiên bản ranh giới đang dùng (2021 cho LSOA Census 2021).';
COMMENT ON COLUMN core.geo_level.notes IS 'Ghi chú.';

CREATE TABLE core.geo_area (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text NOT NULL,
    level_code text NOT NULL,
    code text NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    name_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
    display_name text,
    geom geometry(MultiPolygon, 4326),
    geom_simplified geometry(MultiPolygon, 4326),
    centroid geometry(Point, 4326) NOT NULL,
    area_km2 double precision,
    population integer,
    households integer,
    population_year smallint,
    is_active boolean NOT NULL DEFAULT true,
    valid_from date,
    valid_to date,
    replaced_by_id bigint REFERENCES core.geo_area (id),
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (market_code, level_code) REFERENCES core.geo_level (market_code, code),
    UNIQUE (market_code, level_code, code),
    UNIQUE (market_code, level_code, slug)
);
COMMENT ON TABLE core.geo_area IS 'Mọi đơn vị địa lý của mọi market (postcode, LSOA, LAD, town, ZIP, IRIS...). Trung tâm của mô hình: chỉ số, điểm số, trang SEO đều gắn vào id ở đây.';
COMMENT ON COLUMN core.geo_area.id IS 'Khoá chính nội bộ (bigint), ổn định giữa các lần nạp lại.';
COMMENT ON COLUMN core.geo_area.market_code IS 'Market.';
COMMENT ON COLUMN core.geo_area.level_code IS 'Cấp địa lý.';
COMMENT ON COLUMN core.geo_area.code IS 'Mã chính thức theo nguồn: "SW1A 1AA", E01000001 (LSOA), E09000033 (LAD).';
COMMENT ON COLUMN core.geo_area.slug IS 'Slug URL duy nhất trong cùng cấp: sw1a-1aa, westminster.';
COMMENT ON COLUMN core.geo_area.name IS 'Tên hiển thị gốc.';
COMMENT ON COLUMN core.geo_area.name_i18n IS 'Tên theo locale nếu có bản địa hoá (London → {"vi":"Luân Đôn"}).';
COMMENT ON COLUMN core.geo_area.display_name IS 'Tên đầy đủ có ngữ cảnh: "SW1A 1AA, Westminster, London".';
COMMENT ON COLUMN core.geo_area.geom IS 'Ranh giới đầy đủ (WGS84). NULL với cấp chỉ có điểm (postcode unit).';
COMMENT ON COLUMN core.geo_area.geom_simplified IS 'Ranh giới đơn giản hoá cho bản đồ nhỏ/thumbnail (ST_SimplifyPreserveTopology).';
COMMENT ON COLUMN core.geo_area.centroid IS 'Điểm đại diện (centroid hoặc point-on-surface). Bắt buộc, dùng cho tính khoảng cách tới POI.';
COMMENT ON COLUMN core.geo_area.area_km2 IS 'Diện tích (km²).';
COMMENT ON COLUMN core.geo_area.population IS 'Dân số dùng làm mẫu số cho tỷ lệ (ví dụ tội phạm/1.000 dân).';
COMMENT ON COLUMN core.geo_area.households IS 'Số hộ.';
COMMENT ON COLUMN core.geo_area.population_year IS 'Năm của số dân.';
COMMENT ON COLUMN core.geo_area.is_active IS 'Còn hiệu lực (postcode đã ngừng dùng = false, vẫn giữ để redirect).';
COMMENT ON COLUMN core.geo_area.valid_from IS 'Ngày bắt đầu hiệu lực.';
COMMENT ON COLUMN core.geo_area.valid_to IS 'Ngày hết hiệu lực.';
COMMENT ON COLUMN core.geo_area.replaced_by_id IS 'Đơn vị thay thế (postcode ngừng dùng → postcode mới; commune sáp nhập → commune mới).';
COMMENT ON COLUMN core.geo_area.attrs IS 'Thuộc tính riêng theo market/cấp không cần truy vấn thường xuyên (mã ONS phụ, loại urban/rural...).';
COMMENT ON COLUMN core.geo_area.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN core.geo_area.updated_at IS 'Thời điểm cập nhật cuối.';
CREATE INDEX geo_area_geom_gist ON core.geo_area USING gist (geom);
CREATE INDEX geo_area_centroid_gist ON core.geo_area USING gist (centroid);
CREATE INDEX geo_area_name_trgm ON core.geo_area USING gin (core.normalize_text(name) gin_trgm_ops);
CREATE INDEX geo_area_level_active ON core.geo_area (market_code, level_code) WHERE is_active;

CREATE TABLE core.geo_area_link (
    child_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    parent_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    relation text NOT NULL CHECK (relation IN ('within', 'overlaps', 'best_fit', 'neighbour')),
    weight real NOT NULL DEFAULT 1 CHECK (weight >= 0 AND weight <= 1),
    weight_basis text CHECK (weight_basis IN ('population', 'area', 'address_count', 'none')),
    PRIMARY KEY (child_id, parent_id, relation)
);
COMMENT ON TABLE core.geo_area_link IS 'Quan hệ giữa các đơn vị địa lý. Postcode và đơn vị thống kê không lồng nhau hoàn hảo nên dùng trọng số; cũng lưu quan hệ láng giềng cho mục "khu lân cận".';
COMMENT ON COLUMN core.geo_area_link.child_id IS 'Đơn vị con (nhỏ hơn).';
COMMENT ON COLUMN core.geo_area_link.parent_id IS 'Đơn vị cha (lớn hơn) hoặc láng giềng.';
COMMENT ON COLUMN core.geo_area_link.relation IS 'within (nằm trọn), overlaps (giao một phần, có weight), best_fit (gán duy nhất theo quy tắc ONS), neighbour (láng giềng cùng cấp).';
COMMENT ON COLUMN core.geo_area_link.weight IS 'Tỷ lệ của con nằm trong cha (0–1) theo weight_basis. Dùng khi phân bổ chỉ số giữa các cấp.';
COMMENT ON COLUMN core.geo_area_link.weight_basis IS 'Cơ sở trọng số: population / area / address_count / none.';
CREATE INDEX geo_area_link_parent ON core.geo_area_link (parent_id, relation);

CREATE TABLE core.geo_alias (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    market_code text NOT NULL REFERENCES core.market (code),
    alias_kind text NOT NULL CHECK (alias_kind IN ('terminated_code', 'former_name', 'alt_spelling', 'postal_town', 'abbreviation', 'legacy_code', 'translation')),
    alias_value text NOT NULL,
    alias_normalized text NOT NULL,
    locale_code text REFERENCES core.locale (code),
    valid_to date,
    UNIQUE (market_code, alias_kind, alias_normalized, area_id)
);
COMMENT ON TABLE core.geo_alias IS 'Tên/mã thay thế phục vụ tìm kiếm và redirect: postcode đã ngừng dùng, tên cũ, cách viết khác, tên bản địa hoá.';
COMMENT ON COLUMN core.geo_alias.id IS 'Khoá chính.';
COMMENT ON COLUMN core.geo_alias.area_id IS 'Đơn vị địa lý đích.';
COMMENT ON COLUMN core.geo_alias.market_code IS 'Market (để giới hạn tìm kiếm).';
COMMENT ON COLUMN core.geo_alias.alias_kind IS 'terminated_code / former_name / alt_spelling / postal_town / abbreviation / legacy_code / translation.';
COMMENT ON COLUMN core.geo_alias.alias_value IS 'Giá trị gốc.';
COMMENT ON COLUMN core.geo_alias.alias_normalized IS 'Giá trị đã chuẩn hoá (core.normalize_text, bỏ khoảng trắng với postcode).';
COMMENT ON COLUMN core.geo_alias.locale_code IS 'Locale của bí danh (với kind=translation).';
COMMENT ON COLUMN core.geo_alias.valid_to IS 'Hết hiệu lực (ví dụ postcode ngừng dùng từ ngày).';
CREATE INDEX geo_alias_trgm ON core.geo_alias USING gin (alias_normalized gin_trgm_ops);

CREATE TABLE core.comparison_scope (
    id text PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    name text NOT NULL,
    description text
);
COMMENT ON TABLE core.comparison_scope IS 'Phạm vi được phép so sánh/tính phân vị (uk.england, uk.wales, uk.ew). Ngăn so sánh chỉ số khác phương pháp (IoD England ≠ WIMD Wales).';
COMMENT ON COLUMN core.comparison_scope.id IS 'Mã phạm vi.';
COMMENT ON COLUMN core.comparison_scope.market_code IS 'Market.';
COMMENT ON COLUMN core.comparison_scope.name IS 'Tên phạm vi.';
COMMENT ON COLUMN core.comparison_scope.description IS 'Mô tả.';

CREATE TABLE core.comparison_scope_area (
    scope_id text NOT NULL REFERENCES core.comparison_scope (id) ON DELETE CASCADE,
    area_id bigint NOT NULL REFERENCES core.geo_area (id),
    PRIMARY KEY (scope_id, area_id)
);
COMMENT ON TABLE core.comparison_scope_area IS 'Các đơn vị cấp cao định nghĩa phạm vi (scope uk.ew = nation England + nation Wales). Khu thuộc scope nếu nằm trong một trong các đơn vị này.';
COMMENT ON COLUMN core.comparison_scope_area.scope_id IS 'Phạm vi.';
COMMENT ON COLUMN core.comparison_scope_area.area_id IS 'Đơn vị cấp cao thuộc phạm vi.';

-- =============================================================================
-- @domain metrics | Chỉ số | Danh mục chỉ số (metric registry), bản dịch, giá trị theo khu và theo POI, view giá trị mới nhất
-- =============================================================================

CREATE TABLE core.metric_category (
    code text PRIMARY KEY,
    name_i18n jsonb NOT NULL,
    icon text,
    sort_order smallint NOT NULL DEFAULT 0
);
COMMENT ON TABLE core.metric_category IS 'Nhóm chỉ số dùng để nhóm section trên trang: housing, rent, safety, education, transport, amenities, environment, risk, connectivity, people, energy, costs, planning.';
COMMENT ON COLUMN core.metric_category.code IS 'Mã nhóm.';
COMMENT ON COLUMN core.metric_category.name_i18n IS 'Tên theo locale {"en":"Safety","vi":"An ninh"}.';
COMMENT ON COLUMN core.metric_category.icon IS 'Tên icon giao diện.';
COMMENT ON COLUMN core.metric_category.sort_order IS 'Thứ tự hiển thị section.';

CREATE TABLE core.metric (
    id text PRIMARY KEY,
    market_code text REFERENCES core.market (code),
    category_code text NOT NULL REFERENCES core.metric_category (code),
    dataset_id text REFERENCES ops.dataset (id),
    subject text NOT NULL DEFAULT 'area' CHECK (subject IN ('area', 'poi')),
    value_type text NOT NULL CHECK (value_type IN ('number', 'percent', 'currency', 'count', 'rate', 'index', 'rank', 'rating', 'category', 'distribution', 'boolean', 'duration')),
    unit text,
    decimals smallint NOT NULL DEFAULT 0,
    direction smallint NOT NULL DEFAULT 0 CHECK (direction IN (-1, 0, 1)),
    period_type text NOT NULL CHECK (period_type IN ('month', 'quarter', 'year', 'financial_year', 'rolling_12m', 'rolling_36m', 'snapshot')),
    native_level text,
    aggregation text NOT NULL DEFAULT 'none' CHECK (aggregation IN ('sum', 'mean', 'weighted_mean', 'median_recompute', 'min', 'max', 'none')),
    comparable_scope_id text REFERENCES core.comparison_scope (id),
    min_sample integer,
    is_estimate boolean NOT NULL DEFAULT false,
    sensitivity text NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal', 'sensitive', 'restricted')),
    is_scorable boolean NOT NULL DEFAULT true,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('draft', 'active', 'deprecated')),
    replaced_by text REFERENCES core.metric (id),
    sort_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (sensitivity = 'normal' OR NOT is_scorable)
);
COMMENT ON TABLE core.metric IS 'Danh mục chỉ số (metric registry). Mỗi chỉ số là một dòng dữ liệu: thêm chỉ số/market mới không cần đổi schema.';
COMMENT ON COLUMN core.metric.id IS 'Mã chỉ số dạng <market>.<nhóm>.<tên>: uk.crime.rate_per_1000, uk.price.median_gbp_per_m2.';
COMMENT ON COLUMN core.metric.market_code IS 'Market. NULL = chỉ số dùng chung mọi market (ví dụ khoảng cách tới siêu thị gần nhất tính từ OSM).';
COMMENT ON COLUMN core.metric.category_code IS 'Nhóm hiển thị.';
COMMENT ON COLUMN core.metric.dataset_id IS 'Dataset gốc tạo ra chỉ số (NULL nếu là chỉ số dẫn xuất từ nhiều nguồn).';
COMMENT ON COLUMN core.metric.subject IS 'Đối tượng: area (lưu ở metric_value) hoặc poi (lưu ở poi_metric_value, ví dụ kết quả thi của trường).';
COMMENT ON COLUMN core.metric.value_type IS 'Kiểu giá trị để định dạng hiển thị: number, percent, currency, count, rate, index, rank, rating, category, distribution (dùng value_json), boolean, duration.';
COMMENT ON COLUMN core.metric.unit IS 'Đơn vị: per_1000, gbp, gbp_per_m2, minutes, m, mbps, ug_m3, db...';
COMMENT ON COLUMN core.metric.decimals IS 'Số chữ số thập phân khi hiển thị.';
COMMENT ON COLUMN core.metric.direction IS '1 = càng cao càng tốt, -1 = càng thấp càng tốt (tội phạm), 0 = trung tính (tuổi trung vị). Dùng khi đổi sang điểm.';
COMMENT ON COLUMN core.metric.period_type IS 'Kiểu kỳ dữ liệu: month, quarter, year, financial_year, rolling_12m, rolling_36m, snapshot.';
COMMENT ON COLUMN core.metric.native_level IS 'Cấp địa lý gốc của chỉ số (lsoa, msoa, lad, postcode_unit, point).';
COMMENT ON COLUMN core.metric.aggregation IS 'Cách gộp lên cấp cao hơn: sum, mean, weighted_mean (theo geo_area_link.weight), median_recompute (tính lại từ dữ liệu thô), min, max, none (không gộp).';
COMMENT ON COLUMN core.metric.comparable_scope_id IS 'Phạm vi tính phân vị/so sánh.';
COMMENT ON COLUMN core.metric.min_sample IS 'Mẫu tối thiểu để công bố. Dưới ngưỡng → is_suppressed, gộp lên cấp cao hơn.';
COMMENT ON COLUMN core.metric.is_estimate IS 'Chỉ số là ước tính/mô hình hoá (giá thuê MSOA, AVM) → giao diện gắn nhãn "ước tính".';
COMMENT ON COLUMN core.metric.sensitivity IS 'normal; sensitive (dân tộc, tôn giáo: chỉ hiển thị mô tả, không dùng làm điểm/bộ lọc); restricted (không công khai).';
COMMENT ON COLUMN core.metric.is_scorable IS 'Được phép dùng trong mô hình điểm số. CHECK: chỉ chỉ số normal mới được true.';
COMMENT ON COLUMN core.metric.status IS 'draft / active / deprecated.';
COMMENT ON COLUMN core.metric.replaced_by IS 'Chỉ số thay thế khi deprecated (ví dụ Ofsted cũ → report card).';
COMMENT ON COLUMN core.metric.sort_order IS 'Thứ tự trong section.';
COMMENT ON COLUMN core.metric.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN core.metric.updated_at IS 'Thời điểm cập nhật cuối.';

CREATE TABLE core.metric_translation (
    metric_id text NOT NULL REFERENCES core.metric (id) ON DELETE CASCADE,
    locale_code text NOT NULL REFERENCES core.locale (code),
    name text NOT NULL,
    short_name text,
    description text,
    methodology text,
    caveats text,
    PRIMARY KEY (metric_id, locale_code)
);
COMMENT ON TABLE core.metric_translation IS 'Tên, mô tả, phương pháp, lưu ý của chỉ số theo từng ngôn ngữ (hiển thị tooltip, /methodology). Thêm ngôn ngữ = thêm dòng.';
COMMENT ON COLUMN core.metric_translation.metric_id IS 'Chỉ số.';
COMMENT ON COLUMN core.metric_translation.locale_code IS 'Ngôn ngữ.';
COMMENT ON COLUMN core.metric_translation.name IS 'Tên đầy đủ.';
COMMENT ON COLUMN core.metric_translation.short_name IS 'Tên ngắn cho bảng/biểu đồ.';
COMMENT ON COLUMN core.metric_translation.description IS 'Giải thích dễ hiểu.';
COMMENT ON COLUMN core.metric_translation.methodology IS 'Cách tính (Markdown).';
COMMENT ON COLUMN core.metric_translation.caveats IS 'Lưu ý/giới hạn (vị trí tội phạm đã ẩn danh...).';

CREATE TABLE core.metric_value (
    market_code text NOT NULL,
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    metric_id text NOT NULL REFERENCES core.metric (id),
    period date NOT NULL,
    value_num double precision,
    value_json jsonb,
    sample_size integer,
    ci_low double precision,
    ci_high double precision,
    percentile real CHECK (percentile BETWEEN 0 AND 100),
    percentile_peer real CHECK (percentile_peer BETWEEN 0 AND 100),
    rank_in_scope integer,
    is_suppressed boolean NOT NULL DEFAULT false,
    suppression_reason text CHECK (suppression_reason IN ('small_sample', 'source_suppressed', 'quality', 'privacy')),
    is_imputed boolean NOT NULL DEFAULT false,
    release_id bigint REFERENCES ops.dataset_release (id),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (market_code, area_id, metric_id, period)
) PARTITION BY LIST (market_code);
COMMENT ON TABLE core.metric_value IS 'Giá trị chỉ số theo khu × kỳ. Bảng lớn nhất (50–100 triệu dòng/market), partition theo market. Mở market mới = tạo partition mới.';
COMMENT ON COLUMN core.metric_value.market_code IS 'Khoá partition.';
COMMENT ON COLUMN core.metric_value.area_id IS 'Đơn vị địa lý.';
COMMENT ON COLUMN core.metric_value.metric_id IS 'Chỉ số.';
COMMENT ON COLUMN core.metric_value.period IS 'Ngày đầu kỳ (2026-08-01 cho tháng 8/2026; 2025-04-01 cho năm tài chính 2025/26).';
COMMENT ON COLUMN core.metric_value.value_num IS 'Giá trị số chính.';
COMMENT ON COLUMN core.metric_value.value_json IS 'Giá trị cấu trúc khi value_type = distribution/category (phân bố hạng EPC {"A":0.02,...}).';
COMMENT ON COLUMN core.metric_value.sample_size IS 'Cỡ mẫu (số giao dịch, số vụ...). Hiển thị cho người dùng và kiểm tra ngưỡng.';
COMMENT ON COLUMN core.metric_value.ci_low IS 'Cận dưới khoảng tin cậy (nếu nguồn có).';
COMMENT ON COLUMN core.metric_value.ci_high IS 'Cận trên khoảng tin cậy.';
COMMENT ON COLUMN core.metric_value.percentile IS 'Phân vị thô 0–100 trong comparable_scope cùng cấp (100 = giá trị cao nhất). Việc đổi chiều theo metric.direction chỉ làm khi tính điểm.';
COMMENT ON COLUMN core.metric_value.percentile_peer IS 'Phân vị trong nhóm tương đồng (cùng cấp + cùng nhóm quy mô dân số/urban-rural).';
COMMENT ON COLUMN core.metric_value.rank_in_scope IS 'Thứ hạng trong scope (1 = giá trị cao nhất).';
COMMENT ON COLUMN core.metric_value.is_suppressed IS 'Không công bố giá trị (giữ dòng để giao diện hiển thị "không đủ dữ liệu").';
COMMENT ON COLUMN core.metric_value.suppression_reason IS 'small_sample / source_suppressed / quality / privacy.';
COMMENT ON COLUMN core.metric_value.is_imputed IS 'Giá trị được nội suy/gộp từ cấp khác.';
COMMENT ON COLUMN core.metric_value.release_id IS 'Release nguồn tạo ra giá trị (truy vết, rollback).';
COMMENT ON COLUMN core.metric_value.computed_at IS 'Thời điểm tính.';

CREATE TABLE core.metric_value_uk PARTITION OF core.metric_value FOR VALUES IN ('uk');
COMMENT ON TABLE core.metric_value_uk IS 'Partition của core.metric_value cho market UK.';
CREATE INDEX metric_value_metric_period ON core.metric_value (market_code, metric_id, period);

CREATE MATERIALIZED VIEW core.metric_latest AS
SELECT DISTINCT ON (area_id, metric_id)
       market_code, area_id, metric_id, period, value_num, value_json, sample_size,
       ci_low, ci_high, percentile, percentile_peer, rank_in_scope, is_suppressed, release_id
FROM core.metric_value
ORDER BY area_id, metric_id, period DESC;
COMMENT ON MATERIALIZED VIEW core.metric_latest IS 'Giá trị kỳ mới nhất của mỗi (khu, chỉ số). Trang báo cáo đọc từ đây. REFRESH MATERIALIZED VIEW CONCURRENTLY sau mỗi lần publish.';
CREATE UNIQUE INDEX metric_latest_pk ON core.metric_latest (area_id, metric_id);

CREATE TABLE core.poi_metric_value (
    poi_id bigint NOT NULL,
    metric_id text NOT NULL REFERENCES core.metric (id),
    period date NOT NULL,
    value_num double precision,
    value_json jsonb,
    sample_size integer,
    percentile real CHECK (percentile BETWEEN 0 AND 100),
    is_suppressed boolean NOT NULL DEFAULT false,
    release_id bigint REFERENCES ops.dataset_release (id),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (poi_id, metric_id, period)
);
COMMENT ON TABLE core.poi_metric_value IS 'Giá trị chỉ số gắn với POI (kết quả KS2/KS4 của trường, số bệnh nhân/GP, tần suất tàu của ga). Dùng chung metric registry với subject=poi.';
COMMENT ON COLUMN core.poi_metric_value.poi_id IS 'POI (FK thêm sau khi tạo core.poi).';
COMMENT ON COLUMN core.poi_metric_value.metric_id IS 'Chỉ số (subject = poi).';
COMMENT ON COLUMN core.poi_metric_value.period IS 'Ngày đầu kỳ.';
COMMENT ON COLUMN core.poi_metric_value.value_num IS 'Giá trị số.';
COMMENT ON COLUMN core.poi_metric_value.value_json IS 'Giá trị cấu trúc.';
COMMENT ON COLUMN core.poi_metric_value.sample_size IS 'Cỡ mẫu (số học sinh dự thi...).';
COMMENT ON COLUMN core.poi_metric_value.percentile IS 'Phân vị trong cùng loại POI và scope.';
COMMENT ON COLUMN core.poi_metric_value.is_suppressed IS 'Nguồn ẩn hoặc mẫu quá nhỏ.';
COMMENT ON COLUMN core.poi_metric_value.release_id IS 'Release nguồn.';
COMMENT ON COLUMN core.poi_metric_value.computed_at IS 'Thời điểm tính.';

-- =============================================================================
-- @domain poi | POI & vùng | Điểm quan tâm (trường, ga, GP...), đánh giá thanh tra, vùng rủi ro/quy hoạch/bảo tồn, dữ liệu tính sẵn theo khu
-- =============================================================================

CREATE TABLE core.poi_type (
    code text PRIMARY KEY,
    parent_code text REFERENCES core.poi_type (code),
    name_i18n jsonb NOT NULL,
    icon text,
    is_searchable boolean NOT NULL DEFAULT false,
    has_pages boolean NOT NULL DEFAULT false,
    url_segment text
);
COMMENT ON TABLE core.poi_type IS 'Phân loại POI dạng cây: school > school.primary/secondary; transport > station.rail/station.tube/stop.bus; health > health.gp/pharmacy; shop > shop.supermarket...';
COMMENT ON COLUMN core.poi_type.code IS 'Mã loại dạng chấm (school.secondary).';
COMMENT ON COLUMN core.poi_type.parent_code IS 'Loại cha.';
COMMENT ON COLUMN core.poi_type.name_i18n IS 'Tên theo locale.';
COMMENT ON COLUMN core.poi_type.icon IS 'Icon bản đồ.';
COMMENT ON COLUMN core.poi_type.is_searchable IS 'Có trong ô tìm kiếm (tên trường, tên ga).';
COMMENT ON COLUMN core.poi_type.has_pages IS 'Có trang công khai riêng (trường, ga).';
COMMENT ON COLUMN core.poi_type.url_segment IS 'Đoạn URL (school, station).';

CREATE TABLE core.poi (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    type_code text NOT NULL REFERENCES core.poi_type (code),
    external_scheme text NOT NULL,
    external_id text NOT NULL,
    name text NOT NULL,
    name_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
    slug text,
    geom geometry(Point, 4326) NOT NULL,
    address text,
    postal_code text,
    area_id bigint REFERENCES core.geo_area (id),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'proposed', 'temporarily_closed')),
    opened_on date,
    closed_on date,
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    dataset_id text REFERENCES ops.dataset (id),
    release_id bigint REFERENCES ops.dataset_release (id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (market_code, external_scheme, external_id)
);
COMMENT ON TABLE core.poi IS 'Điểm quan tâm của mọi market: trường học, nhà trẻ, ga, điểm dừng, GP, nhà thuốc, siêu thị, công viên (điểm đại diện), nhà hàng...';
COMMENT ON COLUMN core.poi.id IS 'Khoá chính.';
COMMENT ON COLUMN core.poi.market_code IS 'Market.';
COMMENT ON COLUMN core.poi.type_code IS 'Loại POI.';
COMMENT ON COLUMN core.poi.external_scheme IS 'Hệ mã định danh gốc: urn (trường UK), naptan_atco, crs (ga), ods (NHS), fhrs (FSA), osm, nces (US), uai (FR).';
COMMENT ON COLUMN core.poi.external_id IS 'Mã gốc theo scheme.';
COMMENT ON COLUMN core.poi.name IS 'Tên.';
COMMENT ON COLUMN core.poi.name_i18n IS 'Tên bản địa hoá (hiếm dùng).';
COMMENT ON COLUMN core.poi.slug IS 'Slug URL cho loại có trang riêng (urn-slug).';
COMMENT ON COLUMN core.poi.geom IS 'Vị trí (WGS84).';
COMMENT ON COLUMN core.poi.address IS 'Địa chỉ công khai của cơ sở (không phải nhà riêng).';
COMMENT ON COLUMN core.poi.postal_code IS 'Mã bưu chính.';
COMMENT ON COLUMN core.poi.area_id IS 'Đơn vị thống kê nhỏ nhất chứa POI (LSOA) để join nhanh.';
COMMENT ON COLUMN core.poi.status IS 'open / closed / proposed / temporarily_closed.';
COMMENT ON COLUMN core.poi.opened_on IS 'Ngày mở.';
COMMENT ON COLUMN core.poi.closed_on IS 'Ngày đóng.';
COMMENT ON COLUMN core.poi.attrs IS 'Thuộc tính theo loại: trường {phase, age_low, age_high, gender, religious_character, admissions_policy, capacity, pupils}; ga {operator, step_free}; GP {registered_patients}...';
COMMENT ON COLUMN core.poi.dataset_id IS 'Dataset gốc.';
COMMENT ON COLUMN core.poi.release_id IS 'Release gần nhất cập nhật POI.';
COMMENT ON COLUMN core.poi.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN core.poi.updated_at IS 'Thời điểm cập nhật cuối.';
CREATE INDEX poi_geom_gist ON core.poi USING gist (geom);
CREATE INDEX poi_type_status ON core.poi (market_code, type_code) WHERE status = 'open';
CREATE INDEX poi_name_trgm ON core.poi USING gin (core.normalize_text(name) gin_trgm_ops);
CREATE UNIQUE INDEX poi_slug_unique ON core.poi (market_code, type_code, slug) WHERE slug IS NOT NULL;
ALTER TABLE core.poi_metric_value ADD CONSTRAINT poi_metric_value_poi_fk FOREIGN KEY (poi_id) REFERENCES core.poi (id) ON DELETE CASCADE;

CREATE TABLE core.poi_rating (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    poi_id bigint NOT NULL REFERENCES core.poi (id) ON DELETE CASCADE,
    scheme text NOT NULL,
    aspect text NOT NULL DEFAULT 'overall',
    grade_code text NOT NULL,
    grade_label text,
    grade_rank smallint,
    grade_scale_max smallint,
    rated_on date NOT NULL,
    published_on date,
    report_url text,
    is_current boolean NOT NULL DEFAULT true,
    release_id bigint REFERENCES ops.dataset_release (id),
    UNIQUE (poi_id, scheme, aspect, rated_on)
);
COMMENT ON TABLE core.poi_rating IS 'Kết quả thanh tra/xếp hạng của POI theo nhiều hệ. Hỗ trợ song song Ofsted cũ (1–4) và report card (5 mức theo từng hạng mục) trong giai đoạn chuyển đổi, cùng FSA, Estyn, CQC.';
COMMENT ON COLUMN core.poi_rating.id IS 'Khoá chính.';
COMMENT ON COLUMN core.poi_rating.poi_id IS 'POI được đánh giá.';
COMMENT ON COLUMN core.poi_rating.scheme IS 'Hệ đánh giá: ofsted_legacy, ofsted_report_card, estyn, fsa_fhrs, cqc...';
COMMENT ON COLUMN core.poi_rating.aspect IS 'Hạng mục: overall, quality_of_education, behaviour, leadership, safeguarding, early_years...';
COMMENT ON COLUMN core.poi_rating.grade_code IS 'Mã điểm gốc (1, 2, exceptional, met, 5...).';
COMMENT ON COLUMN core.poi_rating.grade_label IS 'Nhãn gốc (Outstanding, Strong standard...).';
COMMENT ON COLUMN core.poi_rating.grade_rank IS 'Thứ hạng chuẩn hoá: 1 = tốt nhất. NULL với kết quả dạng met/not met.';
COMMENT ON COLUMN core.poi_rating.grade_scale_max IS 'Số mức của thang (4 với Ofsted cũ, 5 với report card, 6 với FSA 0–5).';
COMMENT ON COLUMN core.poi_rating.rated_on IS 'Ngày thanh tra.';
COMMENT ON COLUMN core.poi_rating.published_on IS 'Ngày công bố báo cáo.';
COMMENT ON COLUMN core.poi_rating.report_url IS 'Link báo cáo gốc.';
COMMENT ON COLUMN core.poi_rating.is_current IS 'Là kết quả hiện hành của (poi, scheme, aspect).';
COMMENT ON COLUMN core.poi_rating.release_id IS 'Release nguồn.';
CREATE INDEX poi_rating_current ON core.poi_rating (poi_id, scheme) WHERE is_current;

CREATE TABLE core.zone_type (
    code text PRIMARY KEY,
    category_code text NOT NULL REFERENCES core.metric_category (code),
    name_i18n jsonb NOT NULL,
    is_hazard boolean NOT NULL DEFAULT false,
    level_scale jsonb,
    dataset_id text REFERENCES ops.dataset (id)
);
COMMENT ON TABLE core.zone_type IS 'Loại vùng polygon: flood.rivers_sea, flood.surface_water, flood.alert_area, radon.potential, mining.coal_reporting, landfill.historic, planning.conservation_area, planning.article4, planning.green_belt, nature.sssi, nature.national_landscape, nature.national_park, noise.road, noise.rail...';
COMMENT ON COLUMN core.zone_type.code IS 'Mã loại vùng.';
COMMENT ON COLUMN core.zone_type.category_code IS 'Nhóm hiển thị (risk, planning, environment).';
COMMENT ON COLUMN core.zone_type.name_i18n IS 'Tên theo locale.';
COMMENT ON COLUMN core.zone_type.is_hazard IS 'Là rủi ro (hiển thị cảnh báo) hay chỉ là thông tin (conservation area).';
COMMENT ON COLUMN core.zone_type.level_scale IS 'Thang mức theo thứ tự: ["very_low","low","medium","high"] hoặc dải dB.';
COMMENT ON COLUMN core.zone_type.dataset_id IS 'Dataset gốc.';

CREATE TABLE core.zone (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    type_code text NOT NULL REFERENCES core.zone_type (code),
    external_id text,
    name text,
    level_code text,
    level_rank smallint,
    geom geometry(MultiPolygon, 4326) NOT NULL,
    valid_from date,
    valid_to date,
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    release_id bigint REFERENCES ops.dataset_release (id),
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE core.zone IS 'Các polygon rủi ro/quy hoạch/bảo tồn/tiếng ồn. Polygon lớn nên được chia nhỏ (ST_Subdivide) khi nạp để truy vấn giao cắt nhanh.';
COMMENT ON COLUMN core.zone.id IS 'Khoá chính.';
COMMENT ON COLUMN core.zone.market_code IS 'Market.';
COMMENT ON COLUMN core.zone.type_code IS 'Loại vùng.';
COMMENT ON COLUMN core.zone.external_id IS 'Mã gốc (mã conservation area, mã SSSI...).';
COMMENT ON COLUMN core.zone.name IS 'Tên vùng (nếu có).';
COMMENT ON COLUMN core.zone.level_code IS 'Mức theo zone_type.level_scale (high, 55-59dB...).';
COMMENT ON COLUMN core.zone.level_rank IS 'Thứ tự mức: số càng lớn càng nghiêm trọng.';
COMMENT ON COLUMN core.zone.geom IS 'Hình học (WGS84), đã subdivide.';
COMMENT ON COLUMN core.zone.valid_from IS 'Hiệu lực từ.';
COMMENT ON COLUMN core.zone.valid_to IS 'Hiệu lực đến.';
COMMENT ON COLUMN core.zone.attrs IS 'Thuộc tính khác (ngày chỉ định conservation area, nguồn mô hình lũ...).';
COMMENT ON COLUMN core.zone.release_id IS 'Release nguồn.';
COMMENT ON COLUMN core.zone.created_at IS 'Thời điểm tạo.';
CREATE INDEX zone_geom_gist ON core.zone USING gist (geom);
CREATE INDEX zone_market_type ON core.zone (market_code, type_code);

CREATE TABLE core.zone_alert (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    zone_id bigint REFERENCES core.zone (id),
    type_code text NOT NULL REFERENCES core.zone_type (code),
    external_id text NOT NULL,
    severity text NOT NULL,
    message text,
    issued_at timestamptz NOT NULL,
    expires_at timestamptz,
    raw jsonb,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (market_code, external_id, issued_at)
);
COMMENT ON TABLE core.zone_alert IS 'Cảnh báo thời gian thực gắn với vùng (cảnh báo lũ EA Flood Monitoring API). Cập nhật mỗi ~15 phút, hiển thị banner trên trang khu.';
COMMENT ON COLUMN core.zone_alert.id IS 'Khoá chính.';
COMMENT ON COLUMN core.zone_alert.market_code IS 'Market.';
COMMENT ON COLUMN core.zone_alert.zone_id IS 'Vùng cảnh báo (flood.alert_area) nếu khớp được.';
COMMENT ON COLUMN core.zone_alert.type_code IS 'Loại vùng.';
COMMENT ON COLUMN core.zone_alert.external_id IS 'Mã cảnh báo của nguồn.';
COMMENT ON COLUMN core.zone_alert.severity IS 'Mức (severe_warning, warning, alert...).';
COMMENT ON COLUMN core.zone_alert.message IS 'Nội dung.';
COMMENT ON COLUMN core.zone_alert.issued_at IS 'Thời điểm phát.';
COMMENT ON COLUMN core.zone_alert.expires_at IS 'Hết hạn (NULL = đến khi nguồn gỡ).';
COMMENT ON COLUMN core.zone_alert.raw IS 'Payload gốc.';
COMMENT ON COLUMN core.zone_alert.fetched_at IS 'Thời điểm lấy về.';

CREATE TABLE core.area_poi_nearest (
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    poi_type_code text NOT NULL REFERENCES core.poi_type (code),
    rank smallint NOT NULL CHECK (rank >= 1),
    poi_id bigint NOT NULL REFERENCES core.poi (id) ON DELETE CASCADE,
    distance_m real NOT NULL,
    walk_minutes smallint,
    drive_minutes smallint,
    transit_minutes smallint,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area_id, poi_type_code, rank)
);
COMMENT ON TABLE core.area_poi_nearest IS 'Tính sẵn N POI gần nhất theo loại cho mỗi khu (từ centroid). Giúp trang báo cáo không phải chạy truy vấn không gian khi tải.';
COMMENT ON COLUMN core.area_poi_nearest.area_id IS 'Khu.';
COMMENT ON COLUMN core.area_poi_nearest.poi_type_code IS 'Loại POI.';
COMMENT ON COLUMN core.area_poi_nearest.rank IS 'Thứ tự gần (1 = gần nhất).';
COMMENT ON COLUMN core.area_poi_nearest.poi_id IS 'POI.';
COMMENT ON COLUMN core.area_poi_nearest.distance_m IS 'Khoảng cách đường chim bay (m).';
COMMENT ON COLUMN core.area_poi_nearest.walk_minutes IS 'Phút đi bộ theo mạng đường (khi có routing, giai đoạn 3).';
COMMENT ON COLUMN core.area_poi_nearest.drive_minutes IS 'Phút lái xe.';
COMMENT ON COLUMN core.area_poi_nearest.transit_minutes IS 'Phút đi phương tiện công cộng.';
COMMENT ON COLUMN core.area_poi_nearest.computed_at IS 'Thời điểm tính.';

CREATE TABLE core.area_poi_count (
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    poi_type_code text NOT NULL REFERENCES core.poi_type (code),
    radius_m integer NOT NULL,
    poi_count integer NOT NULL,
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area_id, poi_type_code, radius_m)
);
COMMENT ON TABLE core.area_poi_count IS 'Số POI theo loại trong bán kính (500 m, 1 km, 2 km) quanh khu. Nguồn cho chỉ số tiện ích và tìm ngược.';
COMMENT ON COLUMN core.area_poi_count.area_id IS 'Khu.';
COMMENT ON COLUMN core.area_poi_count.poi_type_code IS 'Loại POI.';
COMMENT ON COLUMN core.area_poi_count.radius_m IS 'Bán kính (m).';
COMMENT ON COLUMN core.area_poi_count.poi_count IS 'Số lượng.';
COMMENT ON COLUMN core.area_poi_count.computed_at IS 'Thời điểm tính.';

CREATE TABLE core.area_zone_exposure (
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    zone_type_code text NOT NULL REFERENCES core.zone_type (code),
    intersects boolean NOT NULL,
    max_level_rank smallint,
    share_of_area real CHECK (share_of_area BETWEEN 0 AND 1),
    share_of_addresses real CHECK (share_of_addresses BETWEEN 0 AND 1),
    nearest_distance_m real,
    release_id bigint REFERENCES ops.dataset_release (id),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area_id, zone_type_code)
);
COMMENT ON TABLE core.area_zone_exposure IS 'Tính sẵn mức phơi nhiễm của khu với từng loại vùng (khu có nằm trong vùng lũ? bao nhiêu % địa chỉ? mức cao nhất?).';
COMMENT ON COLUMN core.area_zone_exposure.area_id IS 'Khu.';
COMMENT ON COLUMN core.area_zone_exposure.zone_type_code IS 'Loại vùng.';
COMMENT ON COLUMN core.area_zone_exposure.intersects IS 'Có giao với vùng loại này không.';
COMMENT ON COLUMN core.area_zone_exposure.max_level_rank IS 'Mức nghiêm trọng cao nhất giao cắt.';
COMMENT ON COLUMN core.area_zone_exposure.share_of_area IS 'Tỷ lệ diện tích khu nằm trong vùng.';
COMMENT ON COLUMN core.area_zone_exposure.share_of_addresses IS 'Tỷ lệ địa chỉ (UPRN) nằm trong vùng — chính xác hơn tỷ lệ diện tích.';
COMMENT ON COLUMN core.area_zone_exposure.nearest_distance_m IS 'Khoảng cách tới vùng gần nhất khi không giao (m).';
COMMENT ON COLUMN core.area_zone_exposure.release_id IS 'Release của dữ liệu vùng.';
COMMENT ON COLUMN core.area_zone_exposure.computed_at IS 'Thời điểm tính.';

-- =============================================================================
-- @domain scoring | Điểm số | Vai trò người dùng, nhóm điểm, mô hình điểm có phiên bản, trọng số, điểm theo khu
-- =============================================================================

CREATE TABLE core.persona (
    code text PRIMARY KEY,
    name_i18n jsonb NOT NULL,
    description_i18n jsonb NOT NULL DEFAULT '{}'::jsonb,
    icon text,
    sort_order smallint NOT NULL DEFAULT 0,
    is_active boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE core.persona IS 'Vai trò người dùng dùng chung mọi market: buyer, renter, family, commuter, newcomer, retiree, investor.';
COMMENT ON COLUMN core.persona.code IS 'Mã vai trò.';
COMMENT ON COLUMN core.persona.name_i18n IS 'Tên theo locale.';
COMMENT ON COLUMN core.persona.description_i18n IS 'Mô tả theo locale.';
COMMENT ON COLUMN core.persona.icon IS 'Icon.';
COMMENT ON COLUMN core.persona.sort_order IS 'Thứ tự hiển thị.';
COMMENT ON COLUMN core.persona.is_active IS 'Đang dùng.';

CREATE TABLE core.score_category (
    code text PRIMARY KEY,
    name_i18n jsonb NOT NULL,
    icon text,
    sort_order smallint NOT NULL DEFAULT 0
);
COMMENT ON TABLE core.score_category IS 'Nhóm điểm: affordability, safety, schools, transport, amenities, environment, connectivity, economy.';
COMMENT ON COLUMN core.score_category.code IS 'Mã nhóm.';
COMMENT ON COLUMN core.score_category.name_i18n IS 'Tên theo locale.';
COMMENT ON COLUMN core.score_category.icon IS 'Icon.';
COMMENT ON COLUMN core.score_category.sort_order IS 'Thứ tự.';

CREATE TABLE core.score_model (
    id text PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    version integer NOT NULL,
    description text,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (market_code, version)
);
COMMENT ON TABLE core.score_model IS 'Mô hình điểm có phiên bản (uk.v1, uk.v2). Cho phép thử mô hình mới song song, tái lập điểm cũ và công bố phương pháp chính xác.';
COMMENT ON COLUMN core.score_model.id IS 'Mã mô hình.';
COMMENT ON COLUMN core.score_model.market_code IS 'Market.';
COMMENT ON COLUMN core.score_model.version IS 'Số phiên bản.';
COMMENT ON COLUMN core.score_model.description IS 'Mô tả thay đổi.';
COMMENT ON COLUMN core.score_model.params IS 'Tham số chung (cách xử lý thiếu dữ liệu, làm mượt...).';
COMMENT ON COLUMN core.score_model.is_active IS 'Mô hình đang hiển thị công khai (mỗi market một mô hình active).';
COMMENT ON COLUMN core.score_model.created_at IS 'Thời điểm tạo.';
CREATE UNIQUE INDEX score_model_one_active ON core.score_model (market_code) WHERE is_active;

CREATE TABLE core.score_component (
    model_id text NOT NULL REFERENCES core.score_model (id) ON DELETE CASCADE,
    category_code text NOT NULL REFERENCES core.score_category (code),
    metric_id text NOT NULL REFERENCES core.metric (id),
    weight real NOT NULL CHECK (weight >= 0),
    transform text NOT NULL DEFAULT 'percentile' CHECK (transform IN ('percentile', 'percentile_peer', 'log_percentile', 'threshold', 'distance_decay')),
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (model_id, category_code, metric_id)
);
COMMENT ON TABLE core.score_component IS 'Chỉ số nào tạo nên nhóm điểm nào, với trọng số và phép biến đổi. Chỉ dùng metric có is_scorable = true (kiểm tra ở tầng ứng dụng/ETL).';
COMMENT ON COLUMN core.score_component.model_id IS 'Mô hình.';
COMMENT ON COLUMN core.score_component.category_code IS 'Nhóm điểm.';
COMMENT ON COLUMN core.score_component.metric_id IS 'Chỉ số thành phần.';
COMMENT ON COLUMN core.score_component.weight IS 'Trọng số trong nhóm (được chuẩn hoá khi tính).';
COMMENT ON COLUMN core.score_component.transform IS 'Biến đổi sang thang 0–100: percentile, percentile_peer, log_percentile, threshold, distance_decay.';
COMMENT ON COLUMN core.score_component.params IS 'Tham số biến đổi (ngưỡng, hệ số suy giảm...).';

CREATE TABLE core.persona_weight (
    model_id text NOT NULL REFERENCES core.score_model (id) ON DELETE CASCADE,
    persona_code text NOT NULL REFERENCES core.persona (code),
    category_code text NOT NULL REFERENCES core.score_category (code),
    weight real NOT NULL CHECK (weight >= 0),
    PRIMARY KEY (model_id, persona_code, category_code)
);
COMMENT ON TABLE core.persona_weight IS 'Trọng số mặc định của từng nhóm điểm theo vai trò. Người dùng chỉnh bằng thanh trượt ở client; điểm tổng tuỳ chỉnh tính lúc hiển thị.';
COMMENT ON COLUMN core.persona_weight.model_id IS 'Mô hình.';
COMMENT ON COLUMN core.persona_weight.persona_code IS 'Vai trò.';
COMMENT ON COLUMN core.persona_weight.category_code IS 'Nhóm điểm.';
COMMENT ON COLUMN core.persona_weight.weight IS 'Trọng số (chuẩn hoá tổng = 1 khi tính).';

CREATE TABLE core.area_category_score (
    model_id text NOT NULL REFERENCES core.score_model (id) ON DELETE CASCADE,
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    category_code text NOT NULL REFERENCES core.score_category (code),
    score real CHECK (score BETWEEN 0 AND 100),
    coverage real NOT NULL CHECK (coverage BETWEEN 0 AND 1),
    percentile real CHECK (percentile BETWEEN 0 AND 100),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model_id, area_id, category_code)
);
COMMENT ON TABLE core.area_category_score IS 'Điểm từng nhóm (0–100) của mỗi khu theo mô hình. Không phụ thuộc vai trò.';
COMMENT ON COLUMN core.area_category_score.model_id IS 'Mô hình.';
COMMENT ON COLUMN core.area_category_score.area_id IS 'Khu.';
COMMENT ON COLUMN core.area_category_score.category_code IS 'Nhóm điểm.';
COMMENT ON COLUMN core.area_category_score.score IS 'Điểm 0–100. NULL khi không đủ dữ liệu.';
COMMENT ON COLUMN core.area_category_score.coverage IS 'Tỷ lệ trọng số thành phần có dữ liệu (0–1). Giao diện cảnh báo khi thấp.';
COMMENT ON COLUMN core.area_category_score.percentile IS 'Phân vị của điểm trong cùng cấp.';
COMMENT ON COLUMN core.area_category_score.computed_at IS 'Thời điểm tính.';
CREATE INDEX area_category_score_rank ON core.area_category_score (model_id, category_code, score DESC);

CREATE TABLE core.area_overall_score (
    model_id text NOT NULL REFERENCES core.score_model (id) ON DELETE CASCADE,
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    persona_code text NOT NULL REFERENCES core.persona (code),
    score real CHECK (score BETWEEN 0 AND 100),
    coverage real NOT NULL CHECK (coverage BETWEEN 0 AND 1),
    percentile real CHECK (percentile BETWEEN 0 AND 100),
    strengths text[],
    weaknesses text[],
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model_id, area_id, persona_code)
);
COMMENT ON TABLE core.area_overall_score IS 'Điểm tổng theo vai trò mặc định (tính sẵn cho SEO, xếp hạng, tìm ngược).';
COMMENT ON COLUMN core.area_overall_score.model_id IS 'Mô hình.';
COMMENT ON COLUMN core.area_overall_score.area_id IS 'Khu.';
COMMENT ON COLUMN core.area_overall_score.persona_code IS 'Vai trò.';
COMMENT ON COLUMN core.area_overall_score.score IS 'Điểm tổng 0–100.';
COMMENT ON COLUMN core.area_overall_score.coverage IS 'Độ phủ dữ liệu.';
COMMENT ON COLUMN core.area_overall_score.percentile IS 'Phân vị trong cùng cấp.';
COMMENT ON COLUMN core.area_overall_score.strengths IS 'Mã metric/nhóm là điểm mạnh nổi bật (hiển thị "3 điểm mạnh").';
COMMENT ON COLUMN core.area_overall_score.weaknesses IS 'Mã metric/nhóm cần lưu ý.';
COMMENT ON COLUMN core.area_overall_score.computed_at IS 'Thời điểm tính.';
CREATE INDEX area_overall_score_rank ON core.area_overall_score (model_id, persona_code, score DESC);

-- =============================================================================
-- @domain mkt_uk | Dữ liệu UK | Bảng chi tiết đặc thù UK: postcode (ONSPD), giao dịch Land Registry, EPC, ghép giao dịch↔EPC, tội phạm, AVM, council tax
-- =============================================================================

CREATE TABLE mkt_uk.postcode (
    postcode text PRIMARY KEY,
    postcode_compact text NOT NULL UNIQUE,
    area_id bigint REFERENCES core.geo_area (id),
    sector text NOT NULL,
    district text NOT NULL,
    postal_area text NOT NULL,
    status text NOT NULL CHECK (status IN ('live', 'terminated')),
    introduced_on date,
    terminated_on date,
    country_code text NOT NULL,
    region_code text,
    lad_code text,
    ward_code text,
    oa21_code text,
    lsoa21_code text,
    msoa21_code text,
    positional_quality smallint,
    geom geometry(Point, 4326),
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.postcode IS 'Danh bạ postcode UK từ ONSPD (hoặc Code-Point Open). Bảng tra cứu nhanh postcode → các mã hành chính/thống kê. Lưu ý quyền Royal Mail/OS trong điều khoản ONSPD.';
COMMENT ON COLUMN mkt_uk.postcode.postcode IS 'Postcode định dạng chuẩn có khoảng trắng: "SW1A 1AA".';
COMMENT ON COLUMN mkt_uk.postcode.postcode_compact IS 'Postcode viết liền chữ hoa "SW1A1AA" để tra nhanh từ input người dùng.';
COMMENT ON COLUMN mkt_uk.postcode.area_id IS 'geo_area cấp postcode_unit tương ứng.';
COMMENT ON COLUMN mkt_uk.postcode.sector IS 'Sector "SW1A 1".';
COMMENT ON COLUMN mkt_uk.postcode.district IS 'District "SW1A".';
COMMENT ON COLUMN mkt_uk.postcode.postal_area IS 'Area "SW".';
COMMENT ON COLUMN mkt_uk.postcode.status IS 'live / terminated.';
COMMENT ON COLUMN mkt_uk.postcode.introduced_on IS 'Tháng bắt đầu dùng.';
COMMENT ON COLUMN mkt_uk.postcode.terminated_on IS 'Tháng ngừng dùng.';
COMMENT ON COLUMN mkt_uk.postcode.country_code IS 'Mã ONS quốc gia (E92000001 England, W92000004 Wales...).';
COMMENT ON COLUMN mkt_uk.postcode.region_code IS 'Mã vùng ONS.';
COMMENT ON COLUMN mkt_uk.postcode.lad_code IS 'Mã Local Authority District.';
COMMENT ON COLUMN mkt_uk.postcode.ward_code IS 'Mã ward.';
COMMENT ON COLUMN mkt_uk.postcode.oa21_code IS 'Output Area 2021.';
COMMENT ON COLUMN mkt_uk.postcode.lsoa21_code IS 'LSOA 2021.';
COMMENT ON COLUMN mkt_uk.postcode.msoa21_code IS 'MSOA 2021.';
COMMENT ON COLUMN mkt_uk.postcode.positional_quality IS 'Chất lượng toạ độ theo ONSPD (1 = tốt nhất).';
COMMENT ON COLUMN mkt_uk.postcode.geom IS 'Toạ độ tâm postcode (WGS84).';
COMMENT ON COLUMN mkt_uk.postcode.release_id IS 'Release ONSPD.';
CREATE INDEX postcode_lsoa ON mkt_uk.postcode (lsoa21_code);
CREATE INDEX postcode_district ON mkt_uk.postcode (district);
CREATE INDEX postcode_geom_gist ON mkt_uk.postcode USING gist (geom);

CREATE TABLE mkt_uk.postcode_street (
    postcode text PRIMARY KEY REFERENCES mkt_uk.postcode (postcode),
    street text NOT NULL,
    post_town text,
    sales integer NOT NULL,
    is_nearest boolean NOT NULL DEFAULT false,
    distance_m real
);
COMMENT ON TABLE mkt_uk.postcode_street IS 'Tên đường + post town cho mỗi postcode, suy ra từ Price Paid (bước derive streets). Dùng cho gợi ý tìm kiếm "Choumert Road, London, SE15 4AA". Postcode đang dùng chưa có giao dịch lấy tên đường của postcode gần nhất (≤ 250 m, is_nearest).';
COMMENT ON COLUMN mkt_uk.postcode_street.postcode IS 'Postcode định dạng chuẩn "SE15 4AA".';
COMMENT ON COLUMN mkt_uk.postcode_street.street IS 'Tên đường chữ hoa như Price Paid ("CHOUMERT ROAD"): cặp street/town có nhiều giao dịch nhất.';
COMMENT ON COLUMN mkt_uk.postcode_street.post_town IS 'Post town chữ hoa ("LONDON").';
COMMENT ON COLUMN mkt_uk.postcode_street.sales IS 'Số giao dịch Price Paid có cặp street/town này ở postcode (0 khi is_nearest).';
COMMENT ON COLUMN mkt_uk.postcode_street.is_nearest IS 'true: postcode không có giao dịch, tên đường lấy từ postcode gần nhất; web hiển thị "gần ...".';
COMMENT ON COLUMN mkt_uk.postcode_street.distance_m IS 'Khoảng cách (m) tới postcode lấy tên đường khi is_nearest.';
CREATE INDEX postcode_street_trgm ON mkt_uk.postcode_street USING gin ((street || ' ' || coalesce(post_town, '')) gin_trgm_ops);

CREATE TABLE mkt_uk.price_paid (
    transaction_id uuid PRIMARY KEY,
    price integer NOT NULL CHECK (price > 0),
    transfer_date date NOT NULL,
    postcode text,
    property_type char(1) NOT NULL CHECK (property_type IN ('D', 'S', 'T', 'F', 'O')),
    is_new_build boolean NOT NULL,
    tenure char(1) NOT NULL CHECK (tenure IN ('F', 'L', 'U')),
    paon text,
    saon text,
    street text,
    locality text,
    town text,
    ppd_category char(1) NOT NULL CHECK (ppd_category IN ('A', 'B')),
    uprn bigint,
    area_id bigint REFERENCES core.geo_area (id),
    lsoa21_code text,
    geom geometry(Point, 4326),
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.price_paid IS 'Giao dịch bất động sản E&W từ HM Land Registry Price Paid Data (~30 triệu dòng từ 1995). Không lưu tên người. Chỉ hiển thị số nhà + đường.';
COMMENT ON COLUMN mkt_uk.price_paid.transaction_id IS 'Mã giao dịch duy nhất của Land Registry.';
COMMENT ON COLUMN mkt_uk.price_paid.price IS 'Giá (GBP).';
COMMENT ON COLUMN mkt_uk.price_paid.transfer_date IS 'Ngày chuyển nhượng.';
COMMENT ON COLUMN mkt_uk.price_paid.postcode IS 'Postcode.';
COMMENT ON COLUMN mkt_uk.price_paid.property_type IS 'D detached, S semi-detached, T terraced, F flat/maisonette, O other.';
COMMENT ON COLUMN mkt_uk.price_paid.is_new_build IS 'Nhà mới xây.';
COMMENT ON COLUMN mkt_uk.price_paid.tenure IS 'F freehold, L leasehold, U unknown.';
COMMENT ON COLUMN mkt_uk.price_paid.paon IS 'Primary Addressable Object Name (số nhà/tên nhà).';
COMMENT ON COLUMN mkt_uk.price_paid.saon IS 'Secondary Addressable Object Name (số căn hộ).';
COMMENT ON COLUMN mkt_uk.price_paid.street IS 'Tên đường.';
COMMENT ON COLUMN mkt_uk.price_paid.locality IS 'Locality.';
COMMENT ON COLUMN mkt_uk.price_paid.town IS 'Thị trấn/thành phố.';
COMMENT ON COLUMN mkt_uk.price_paid.ppd_category IS 'A = giao dịch chuẩn giá thị trường; B = khác (công ty, repossession, buy-to-let...). Thống kê giá chỉ dùng A.';
COMMENT ON COLUMN mkt_uk.price_paid.uprn IS 'UPRN sau khi khớp địa chỉ (nếu có) để ghép EPC.';
COMMENT ON COLUMN mkt_uk.price_paid.area_id IS 'geo_area cấp postcode_unit.';
COMMENT ON COLUMN mkt_uk.price_paid.lsoa21_code IS 'LSOA 2021 (phi chuẩn hoá để tổng hợp nhanh).';
COMMENT ON COLUMN mkt_uk.price_paid.geom IS 'Toạ độ (UPRN nếu khớp, ngược lại tâm postcode).';
COMMENT ON COLUMN mkt_uk.price_paid.release_id IS 'Release PPD.';
CREATE INDEX price_paid_postcode_date ON mkt_uk.price_paid (postcode, transfer_date DESC);
CREATE INDEX price_paid_lsoa_date ON mkt_uk.price_paid (lsoa21_code, transfer_date);
CREATE INDEX price_paid_date ON mkt_uk.price_paid (transfer_date);
CREATE INDEX price_paid_uprn ON mkt_uk.price_paid (uprn) WHERE uprn IS NOT NULL;

CREATE TABLE mkt_uk.epc_certificate (
    lmk_key text PRIMARY KEY,
    uprn bigint,
    postcode text,
    address_key text,
    lodgement_date date NOT NULL,
    inspection_date date,
    current_rating char(1) CHECK (current_rating BETWEEN 'A' AND 'G'),
    potential_rating char(1) CHECK (potential_rating BETWEEN 'A' AND 'G'),
    current_efficiency smallint,
    property_type text,
    built_form text,
    construction_age_band text,
    total_floor_area_m2 numeric(8, 2),
    habitable_rooms smallint,
    main_fuel text,
    main_heating text,
    tenure text,
    transaction_type text,
    is_latest_for_address boolean NOT NULL DEFAULT false,
    area_id bigint REFERENCES core.geo_area (id),
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.epc_certificate IS 'Chứng chỉ năng lượng EPC nhà ở (E&W). Dùng cho thống kê hạng EPC theo khu, diện tích sàn → £/m², và đặc trưng cho AVM. Trường địa chỉ có quyền bên thứ ba: chỉ lưu khoá chuẩn hoá để ghép, không hiển thị.';
COMMENT ON COLUMN mkt_uk.epc_certificate.lmk_key IS 'Mã chứng chỉ duy nhất.';
COMMENT ON COLUMN mkt_uk.epc_certificate.uprn IS 'UPRN (nếu nguồn cung cấp).';
COMMENT ON COLUMN mkt_uk.epc_certificate.postcode IS 'Postcode.';
COMMENT ON COLUMN mkt_uk.epc_certificate.address_key IS 'Khoá địa chỉ chuẩn hoá (số nhà + đường + postcode) dùng ghép với Price Paid. Không hiển thị công khai.';
COMMENT ON COLUMN mkt_uk.epc_certificate.lodgement_date IS 'Ngày nộp chứng chỉ.';
COMMENT ON COLUMN mkt_uk.epc_certificate.inspection_date IS 'Ngày khảo sát.';
COMMENT ON COLUMN mkt_uk.epc_certificate.current_rating IS 'Hạng hiện tại A–G.';
COMMENT ON COLUMN mkt_uk.epc_certificate.potential_rating IS 'Hạng tiềm năng A–G.';
COMMENT ON COLUMN mkt_uk.epc_certificate.current_efficiency IS 'Điểm SAP hiện tại.';
COMMENT ON COLUMN mkt_uk.epc_certificate.property_type IS 'Loại nhà (House, Flat, Bungalow, Maisonette).';
COMMENT ON COLUMN mkt_uk.epc_certificate.built_form IS 'Dạng (Detached, Semi-Detached, Mid-Terrace...).';
COMMENT ON COLUMN mkt_uk.epc_certificate.construction_age_band IS 'Khoảng năm xây.';
COMMENT ON COLUMN mkt_uk.epc_certificate.total_floor_area_m2 IS 'Tổng diện tích sàn (m²).';
COMMENT ON COLUMN mkt_uk.epc_certificate.habitable_rooms IS 'Số phòng ở.';
COMMENT ON COLUMN mkt_uk.epc_certificate.main_fuel IS 'Nhiên liệu chính.';
COMMENT ON COLUMN mkt_uk.epc_certificate.main_heating IS 'Mô tả hệ thống sưởi chính.';
COMMENT ON COLUMN mkt_uk.epc_certificate.tenure IS 'Hình thức sở hữu khi lập EPC (owner-occupied, rental...).';
COMMENT ON COLUMN mkt_uk.epc_certificate.transaction_type IS 'Lý do lập EPC (marketed sale, rental, new dwelling...).';
COMMENT ON COLUMN mkt_uk.epc_certificate.is_latest_for_address IS 'Là chứng chỉ mới nhất của địa chỉ (thống kê chỉ dùng bản mới nhất).';
COMMENT ON COLUMN mkt_uk.epc_certificate.area_id IS 'geo_area cấp postcode_unit.';
COMMENT ON COLUMN mkt_uk.epc_certificate.release_id IS 'Release EPC.';
CREATE INDEX epc_uprn ON mkt_uk.epc_certificate (uprn) WHERE uprn IS NOT NULL;
CREATE INDEX epc_postcode_latest ON mkt_uk.epc_certificate (postcode) WHERE is_latest_for_address;
CREATE INDEX epc_address_key ON mkt_uk.epc_certificate (address_key);

CREATE TABLE mkt_uk.ppd_epc_match (
    transaction_id uuid PRIMARY KEY REFERENCES mkt_uk.price_paid (transaction_id) ON DELETE CASCADE,
    lmk_key text NOT NULL REFERENCES mkt_uk.epc_certificate (lmk_key) ON DELETE CASCADE,
    match_method text NOT NULL CHECK (match_method IN ('uprn', 'exact_address', 'fuzzy_address')),
    match_score real NOT NULL CHECK (match_score BETWEEN 0 AND 1),
    matched_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE mkt_uk.ppd_epc_match IS 'Kết quả ghép giao dịch ↔ EPC gần nhất trước ngày giao dịch. Nền tảng cho £/m² và AVM (khớp lợi thế dữ liệu với PropertyData/CrystalRoof).';
COMMENT ON COLUMN mkt_uk.ppd_epc_match.transaction_id IS 'Giao dịch.';
COMMENT ON COLUMN mkt_uk.ppd_epc_match.lmk_key IS 'Chứng chỉ EPC được ghép.';
COMMENT ON COLUMN mkt_uk.ppd_epc_match.match_method IS 'uprn / exact_address / fuzzy_address.';
COMMENT ON COLUMN mkt_uk.ppd_epc_match.match_score IS 'Độ tin cậy ghép (0–1). Thống kê chỉ dùng điểm ≥ ngưỡng cấu hình.';
COMMENT ON COLUMN mkt_uk.ppd_epc_match.matched_at IS 'Thời điểm ghép.';
CREATE INDEX ppd_epc_match_lmk ON mkt_uk.ppd_epc_match (lmk_key);

CREATE TABLE mkt_uk.uprn_point (
    uprn bigint PRIMARY KEY,
    x real NOT NULL,
    y real NOT NULL,
    geom geometry(Point, 4326) NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id)
);
COMMENT ON TABLE mkt_uk.uprn_point IS 'Toạ độ OS Open UPRN (OGL) cho các UPRN đang dùng: nhà có EPC. Dùng cho chỉ số theo từng nhà (lũ nước mặt...).';
COMMENT ON COLUMN mkt_uk.uprn_point.uprn IS 'Unique Property Reference Number.';
COMMENT ON COLUMN mkt_uk.uprn_point.x IS 'Easting EPSG:27700 (m).';
COMMENT ON COLUMN mkt_uk.uprn_point.y IS 'Northing EPSG:27700 (m).';
COMMENT ON COLUMN mkt_uk.uprn_point.geom IS 'Toạ độ WGS84.';
COMMENT ON COLUMN mkt_uk.uprn_point.release_id IS 'Release OS Open UPRN.';

CREATE TABLE mkt_uk.crime_incident (
    id bigint GENERATED ALWAYS AS IDENTITY,
    month date NOT NULL,
    crime_ref text,
    reported_by text NOT NULL,
    falls_within text,
    crime_type text NOT NULL,
    lsoa21_code text,
    location_desc text,
    last_outcome text,
    geom geometry(Point, 4326),
    release_id bigint REFERENCES ops.dataset_release (id),
    PRIMARY KEY (id, month)
) PARTITION BY RANGE (month);
COMMENT ON TABLE mkt_uk.crime_incident IS 'Vụ việc tội phạm/ASB từ data.police.uk (archive hằng tháng). Toạ độ đã được nguồn ẩn danh (snap về điểm gần nhất). Partition theo năm; giữ ~36 tháng chi tiết, cũ hơn chỉ giữ tổng hợp.';
COMMENT ON COLUMN mkt_uk.crime_incident.id IS 'Khoá nội bộ.';
COMMENT ON COLUMN mkt_uk.crime_incident.month IS 'Tháng (ngày 1). Khoá partition.';
COMMENT ON COLUMN mkt_uk.crime_incident.crime_ref IS 'Crime ID của nguồn (trống với anti-social behaviour).';
COMMENT ON COLUMN mkt_uk.crime_incident.reported_by IS 'Lực lượng cảnh sát báo cáo.';
COMMENT ON COLUMN mkt_uk.crime_incident.falls_within IS 'Lực lượng phụ trách khu vực.';
COMMENT ON COLUMN mkt_uk.crime_incident.crime_type IS 'Loại (Burglary, Violence and sexual offences, Anti-social behaviour...).';
COMMENT ON COLUMN mkt_uk.crime_incident.lsoa21_code IS 'LSOA nơi xảy ra.';
COMMENT ON COLUMN mkt_uk.crime_incident.location_desc IS 'Mô tả vị trí ẩn danh ("On or near High Street").';
COMMENT ON COLUMN mkt_uk.crime_incident.last_outcome IS 'Kết quả xử lý gần nhất.';
COMMENT ON COLUMN mkt_uk.crime_incident.geom IS 'Toạ độ ẩn danh.';
COMMENT ON COLUMN mkt_uk.crime_incident.release_id IS 'Release archive tháng.';

CREATE TABLE mkt_uk.crime_incident_2024 PARTITION OF mkt_uk.crime_incident FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE mkt_uk.crime_incident_2025 PARTITION OF mkt_uk.crime_incident FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE mkt_uk.crime_incident_2026 PARTITION OF mkt_uk.crime_incident FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE mkt_uk.crime_incident_default PARTITION OF mkt_uk.crime_incident DEFAULT;
COMMENT ON TABLE mkt_uk.crime_incident_2024 IS 'Partition năm 2024.';
COMMENT ON TABLE mkt_uk.crime_incident_2025 IS 'Partition năm 2025.';
COMMENT ON TABLE mkt_uk.crime_incident_2026 IS 'Partition năm 2026. ETL tạo partition năm mới trước tháng 1.';
COMMENT ON TABLE mkt_uk.crime_incident_default IS 'Partition mặc định, phải luôn rỗng (cảnh báo nếu có dòng).';
CREATE INDEX crime_incident_lsoa_month ON mkt_uk.crime_incident (lsoa21_code, month);
CREATE INDEX crime_incident_geom_gist ON mkt_uk.crime_incident USING gist (geom);

CREATE TABLE mkt_uk.crime_coverage_gap (
    police_force text NOT NULL,
    month date NOT NULL,
    reason text,
    detected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (police_force, month)
);
COMMENT ON TABLE mkt_uk.crime_coverage_gap IS 'Tháng mà một lực lượng cảnh sát không gửi dữ liệu (ví dụ Greater Manchester Police 2019–2020). Giao diện hiển thị "thiếu dữ liệu" thay vì báo tội phạm = 0.';
COMMENT ON COLUMN mkt_uk.crime_coverage_gap.police_force IS 'Lực lượng cảnh sát.';
COMMENT ON COLUMN mkt_uk.crime_coverage_gap.month IS 'Tháng thiếu.';
COMMENT ON COLUMN mkt_uk.crime_coverage_gap.reason IS 'Lý do (nếu biết).';
COMMENT ON COLUMN mkt_uk.crime_coverage_gap.detected_at IS 'Thời điểm phát hiện.';

CREATE TABLE mkt_uk.avm_estimate (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_version text NOT NULL,
    postcode text NOT NULL,
    property_type char(1) NOT NULL CHECK (property_type IN ('D', 'S', 'T', 'F')),
    bedrooms smallint NOT NULL CHECK (bedrooms BETWEEN 0 AND 10),
    tenure char(1) NOT NULL CHECK (tenure IN ('F', 'L')),
    estimate_low integer NOT NULL,
    estimate_mid integer NOT NULL,
    estimate_high integer NOT NULL,
    confidence text NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    comparables_count integer,
    valid_on date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (estimate_low <= estimate_mid AND estimate_mid <= estimate_high),
    UNIQUE (model_version, postcode, property_type, bedrooms, tenure)
);
COMMENT ON TABLE mkt_uk.avm_estimate IS 'Định giá tự động (AVM) tính sẵn theo postcode × loại nhà × số phòng ngủ × tenure (giai đoạn 3). Không định giá từng địa chỉ. Hiển thị khoảng giá + độ tin cậy, ẩn khi confidence = low.';
COMMENT ON COLUMN mkt_uk.avm_estimate.id IS 'Khoá chính.';
COMMENT ON COLUMN mkt_uk.avm_estimate.model_version IS 'Phiên bản mô hình (để so sánh/backtest và rollback).';
COMMENT ON COLUMN mkt_uk.avm_estimate.postcode IS 'Postcode.';
COMMENT ON COLUMN mkt_uk.avm_estimate.property_type IS 'D, S, T, F.';
COMMENT ON COLUMN mkt_uk.avm_estimate.bedrooms IS 'Số phòng ngủ (suy từ habitable_rooms của EPC).';
COMMENT ON COLUMN mkt_uk.avm_estimate.tenure IS 'F freehold, L leasehold.';
COMMENT ON COLUMN mkt_uk.avm_estimate.estimate_low IS 'Cận dưới (GBP).';
COMMENT ON COLUMN mkt_uk.avm_estimate.estimate_mid IS 'Ước tính trung tâm (GBP).';
COMMENT ON COLUMN mkt_uk.avm_estimate.estimate_high IS 'Cận trên (GBP).';
COMMENT ON COLUMN mkt_uk.avm_estimate.confidence IS 'high / medium / low.';
COMMENT ON COLUMN mkt_uk.avm_estimate.comparables_count IS 'Số giao dịch tương đồng dùng làm căn cứ.';
COMMENT ON COLUMN mkt_uk.avm_estimate.valid_on IS 'Ngày định giá tham chiếu.';
COMMENT ON COLUMN mkt_uk.avm_estimate.created_at IS 'Thời điểm tạo.';

CREATE TABLE mkt_uk.council_tax_rate (
    lad_code text NOT NULL,
    financial_year text NOT NULL CHECK (financial_year ~ '^\d{4}/\d{2}$'),
    band char(1) NOT NULL CHECK (band BETWEEN 'A' AND 'I'),
    parish_code text NOT NULL DEFAULT '',
    amount_gbp numeric(10, 2) NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id),
    PRIMARY KEY (lad_code, financial_year, band, parish_code)
);
COMMENT ON TABLE mkt_uk.council_tax_rate IS 'Mức council tax hằng năm theo băng của từng LA (England A–H, Wales A–I), có thể chi tiết theo parish.';
COMMENT ON COLUMN mkt_uk.council_tax_rate.lad_code IS 'Mã Local Authority District.';
COMMENT ON COLUMN mkt_uk.council_tax_rate.financial_year IS 'Năm tài chính "2026/27".';
COMMENT ON COLUMN mkt_uk.council_tax_rate.band IS 'Băng A–I.';
COMMENT ON COLUMN mkt_uk.council_tax_rate.parish_code IS 'Parish (chuỗi rỗng = mức trung bình toàn LA).';
COMMENT ON COLUMN mkt_uk.council_tax_rate.amount_gbp IS 'Số tiền hằng năm (GBP).';
COMMENT ON COLUMN mkt_uk.council_tax_rate.release_id IS 'Release nguồn.';

-- =============================================================================
-- @domain content | Nội dung & SEO | Tóm tắt AI, glossary, trang biên tập, cấu hình công cụ, xếp hạng, trạng thái index, redirect
-- =============================================================================

CREATE TABLE content.area_summary (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    locale_code text NOT NULL REFERENCES core.locale (code),
    persona_code text REFERENCES core.persona (code),
    data_version text NOT NULL,
    model_name text NOT NULL,
    prompt_version text NOT NULL,
    body_md text NOT NULL,
    highlights jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'rejected', 'stale')),
    generated_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    UNIQUE NULLS NOT DISTINCT (area_id, locale_code, persona_code, data_version)
);
COMMENT ON TABLE content.area_summary IS 'Tóm tắt khu do AI sinh, cache theo (khu, ngôn ngữ, vai trò, phiên bản dữ liệu). Chỉ được viết từ số liệu trong DB; gắn nhãn AI trên giao diện.';
COMMENT ON COLUMN content.area_summary.id IS 'Khoá chính.';
COMMENT ON COLUMN content.area_summary.area_id IS 'Khu.';
COMMENT ON COLUMN content.area_summary.locale_code IS 'Ngôn ngữ.';
COMMENT ON COLUMN content.area_summary.persona_code IS 'Vai trò (NULL = tóm tắt chung).';
COMMENT ON COLUMN content.area_summary.data_version IS 'Hash của bộ số liệu đầu vào. Số liệu đổi → bản cũ thành stale.';
COMMENT ON COLUMN content.area_summary.model_name IS 'Model sinh nội dung (claude-haiku-5-5).';
COMMENT ON COLUMN content.area_summary.prompt_version IS 'Phiên bản prompt.';
COMMENT ON COLUMN content.area_summary.body_md IS 'Nội dung Markdown.';
COMMENT ON COLUMN content.area_summary.highlights IS 'Danh sách điểm nổi bật có cấu trúc [{"metric_id":..,"tone":"positive"}].';
COMMENT ON COLUMN content.area_summary.status IS 'draft / published / rejected / stale.';
COMMENT ON COLUMN content.area_summary.generated_at IS 'Thời điểm sinh.';
COMMENT ON COLUMN content.area_summary.reviewed_at IS 'Thời điểm được người duyệt (nếu có).';

CREATE TABLE content.glossary_term (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text REFERENCES core.market (code),
    slug text NOT NULL,
    term_original text NOT NULL,
    category text,
    related_metric_ids text[],
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (market_code, slug)
);
COMMENT ON TABLE content.glossary_term IS 'Thuật ngữ cần giải thích (council tax, leasehold, Ofsted, EPC, stamp duty...). Vừa là tooltip vừa là trang SEO /glossary.';
COMMENT ON COLUMN content.glossary_term.id IS 'Khoá chính.';
COMMENT ON COLUMN content.glossary_term.market_code IS 'Market (NULL = chung).';
COMMENT ON COLUMN content.glossary_term.slug IS 'Slug URL.';
COMMENT ON COLUMN content.glossary_term.term_original IS 'Thuật ngữ gốc giữ nguyên ở mọi ngôn ngữ.';
COMMENT ON COLUMN content.glossary_term.category IS 'Nhóm (buying, renting, schools, tax...).';
COMMENT ON COLUMN content.glossary_term.related_metric_ids IS 'Chỉ số liên quan (hiển thị tooltip).';
COMMENT ON COLUMN content.glossary_term.created_at IS 'Thời điểm tạo.';

CREATE TABLE content.glossary_translation (
    term_id bigint NOT NULL REFERENCES content.glossary_term (id) ON DELETE CASCADE,
    locale_code text NOT NULL REFERENCES core.locale (code),
    title text NOT NULL,
    short_definition text NOT NULL,
    body_md text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (term_id, locale_code)
);
COMMENT ON TABLE content.glossary_translation IS 'Giải thích thuật ngữ theo ngôn ngữ.';
COMMENT ON COLUMN content.glossary_translation.term_id IS 'Thuật ngữ.';
COMMENT ON COLUMN content.glossary_translation.locale_code IS 'Ngôn ngữ.';
COMMENT ON COLUMN content.glossary_translation.title IS 'Tiêu đề.';
COMMENT ON COLUMN content.glossary_translation.short_definition IS 'Định nghĩa ngắn (tooltip).';
COMMENT ON COLUMN content.glossary_translation.body_md IS 'Nội dung đầy đủ.';
COMMENT ON COLUMN content.glossary_translation.updated_at IS 'Thời điểm cập nhật.';

CREATE TABLE content.page (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text REFERENCES core.market (code),
    page_type text NOT NULL CHECK (page_type IN ('guide', 'article', 'landing', 'legal', 'about')),
    key text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
    author text,
    published_at timestamptz,
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE content.page IS 'Trang biên tập (hướng dẫn "moving to the UK", bài viết, landing, pháp lý). Nội dung theo ngôn ngữ ở page_translation.';
COMMENT ON COLUMN content.page.id IS 'Khoá chính.';
COMMENT ON COLUMN content.page.market_code IS 'Market (NULL = chung).';
COMMENT ON COLUMN content.page.page_type IS 'guide / article / landing / legal / about.';
COMMENT ON COLUMN content.page.key IS 'Khoá ổn định (uk.guide.council-tax).';
COMMENT ON COLUMN content.page.status IS 'draft / published / archived.';
COMMENT ON COLUMN content.page.author IS 'Tác giả (E-E-A-T).';
COMMENT ON COLUMN content.page.published_at IS 'Ngày đăng.';
COMMENT ON COLUMN content.page.attrs IS 'Thuộc tính khác (ảnh bìa, khu liên quan...).';
COMMENT ON COLUMN content.page.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN content.page.updated_at IS 'Thời điểm cập nhật.';

CREATE TABLE content.page_translation (
    page_id bigint NOT NULL REFERENCES content.page (id) ON DELETE CASCADE,
    locale_code text NOT NULL REFERENCES core.locale (code),
    slug text NOT NULL,
    title text NOT NULL,
    meta_description text,
    body_md text NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'machine_translated', 'reviewed', 'published')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (page_id, locale_code)
);
COMMENT ON TABLE content.page_translation IS 'Nội dung trang theo ngôn ngữ, có trạng thái dịch (máy dịch → người duyệt → xuất bản).';
COMMENT ON COLUMN content.page_translation.page_id IS 'Trang.';
COMMENT ON COLUMN content.page_translation.locale_code IS 'Ngôn ngữ.';
COMMENT ON COLUMN content.page_translation.slug IS 'Slug đã dịch.';
COMMENT ON COLUMN content.page_translation.title IS 'Tiêu đề.';
COMMENT ON COLUMN content.page_translation.meta_description IS 'Meta description.';
COMMENT ON COLUMN content.page_translation.body_md IS 'Nội dung Markdown.';
COMMENT ON COLUMN content.page_translation.status IS 'draft / machine_translated / reviewed / published.';
COMMENT ON COLUMN content.page_translation.updated_at IS 'Thời điểm cập nhật.';

CREATE TABLE content.tool_config (
    id text PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    tool_code text NOT NULL CHECK (tool_code IN ('stamp_duty', 'mortgage_affordability', 'moving_costs', 'rent_vs_buy', 'cost_of_living', 'commute')),
    jurisdiction text,
    valid_from date NOT NULL,
    valid_to date,
    params jsonb NOT NULL,
    source_url text,
    notes text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE content.tool_config IS 'Tham số các công cụ tính toán có hiệu lực theo thời gian (bậc thuế stamp duty England, LTT Wales, LBTT Scotland...). Đổi luật thuế không cần deploy.';
COMMENT ON COLUMN content.tool_config.id IS 'Mã cấu hình (uk.stamp_duty.england.2025-04).';
COMMENT ON COLUMN content.tool_config.market_code IS 'Market.';
COMMENT ON COLUMN content.tool_config.tool_code IS 'Công cụ.';
COMMENT ON COLUMN content.tool_config.jurisdiction IS 'Phạm vi áp dụng (england, wales, scotland).';
COMMENT ON COLUMN content.tool_config.valid_from IS 'Hiệu lực từ.';
COMMENT ON COLUMN content.tool_config.valid_to IS 'Hiệu lực đến (NULL = hiện hành).';
COMMENT ON COLUMN content.tool_config.params IS 'Tham số (bậc thuế, ngưỡng first-time buyer, lãi suất mặc định...).';
COMMENT ON COLUMN content.tool_config.source_url IS 'Nguồn chính thức (gov.uk).';
COMMENT ON COLUMN content.tool_config.notes IS 'Ghi chú.';
COMMENT ON COLUMN content.tool_config.updated_at IS 'Thời điểm cập nhật.';

CREATE TABLE content.ranking_def (
    id text PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    slug text NOT NULL,
    metric_id text REFERENCES core.metric (id),
    score_category_code text REFERENCES core.score_category (code),
    persona_code text REFERENCES core.persona (code),
    area_level text NOT NULL,
    scope_area_id bigint REFERENCES core.geo_area (id),
    sort_direction text NOT NULL CHECK (sort_direction IN ('asc', 'desc')),
    min_population integer,
    limit_n integer NOT NULL DEFAULT 20,
    filters jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_published boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (market_code, slug),
    CHECK (num_nonnulls(metric_id, score_category_code, persona_code) >= 1)
);
COMMENT ON TABLE content.ranking_def IS 'Định nghĩa trang xếp hạng ("10 sector an toàn nhất Manchester"). Xếp theo một chỉ số, một nhóm điểm hoặc điểm tổng của một vai trò.';
COMMENT ON COLUMN content.ranking_def.id IS 'Mã xếp hạng.';
COMMENT ON COLUMN content.ranking_def.market_code IS 'Market.';
COMMENT ON COLUMN content.ranking_def.slug IS 'Slug URL.';
COMMENT ON COLUMN content.ranking_def.metric_id IS 'Xếp theo chỉ số (tuỳ chọn).';
COMMENT ON COLUMN content.ranking_def.score_category_code IS 'Xếp theo nhóm điểm (tuỳ chọn).';
COMMENT ON COLUMN content.ranking_def.persona_code IS 'Xếp theo điểm tổng của vai trò (tuỳ chọn).';
COMMENT ON COLUMN content.ranking_def.area_level IS 'Cấp khu được xếp (sector, district, town, lad).';
COMMENT ON COLUMN content.ranking_def.scope_area_id IS 'Giới hạn trong khu cha (NULL = cả market).';
COMMENT ON COLUMN content.ranking_def.sort_direction IS 'asc / desc.';
COMMENT ON COLUMN content.ranking_def.min_population IS 'Bỏ qua khu quá nhỏ.';
COMMENT ON COLUMN content.ranking_def.limit_n IS 'Số mục.';
COMMENT ON COLUMN content.ranking_def.filters IS 'Bộ lọc thêm.';
COMMENT ON COLUMN content.ranking_def.is_published IS 'Đã công khai.';
COMMENT ON COLUMN content.ranking_def.created_at IS 'Thời điểm tạo.';

CREATE TABLE content.ranking_translation (
    ranking_id text NOT NULL REFERENCES content.ranking_def (id) ON DELETE CASCADE,
    locale_code text NOT NULL REFERENCES core.locale (code),
    title text NOT NULL,
    intro_md text,
    PRIMARY KEY (ranking_id, locale_code)
);
COMMENT ON TABLE content.ranking_translation IS 'Tiêu đề và đoạn giới thiệu của trang xếp hạng theo ngôn ngữ.';
COMMENT ON COLUMN content.ranking_translation.ranking_id IS 'Xếp hạng.';
COMMENT ON COLUMN content.ranking_translation.locale_code IS 'Ngôn ngữ.';
COMMENT ON COLUMN content.ranking_translation.title IS 'Tiêu đề.';
COMMENT ON COLUMN content.ranking_translation.intro_md IS 'Giới thiệu.';

CREATE TABLE content.ranking_entry (
    ranking_id text NOT NULL REFERENCES content.ranking_def (id) ON DELETE CASCADE,
    computed_on date NOT NULL,
    position integer NOT NULL CHECK (position >= 1),
    area_id bigint NOT NULL REFERENCES core.geo_area (id),
    value_num double precision,
    PRIMARY KEY (ranking_id, computed_on, position)
);
COMMENT ON TABLE content.ranking_entry IS 'Ảnh chụp kết quả xếp hạng mỗi kỳ. Giữ lịch sử để hiển thị "tăng/giảm hạng" và làm nội dung báo chí.';
COMMENT ON COLUMN content.ranking_entry.ranking_id IS 'Xếp hạng.';
COMMENT ON COLUMN content.ranking_entry.computed_on IS 'Ngày tính.';
COMMENT ON COLUMN content.ranking_entry.position IS 'Vị trí.';
COMMENT ON COLUMN content.ranking_entry.area_id IS 'Khu.';
COMMENT ON COLUMN content.ranking_entry.value_num IS 'Giá trị dùng để xếp.';

CREATE TABLE content.seo_page (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text REFERENCES core.market (code),
    locale_code text NOT NULL REFERENCES core.locale (code),
    page_kind text NOT NULL CHECK (page_kind IN ('area', 'poi', 'ranking', 'tool', 'glossary', 'page', 'hub')),
    entity_id bigint,
    entity_key text,
    path text NOT NULL,
    canonical_path text,
    index_status text NOT NULL DEFAULT 'pending' CHECK (index_status IN ('pending', 'index', 'noindex')),
    index_reason text,
    quality_score real,
    content_hash text,
    lastmod timestamptz,
    sitemap_shard text,
    evaluated_at timestamptz,
    UNIQUE (locale_code, path)
);
COMMENT ON TABLE content.seo_page IS 'Sổ đăng ký mọi trang công khai và quyết định index/noindex (chống trang mỏng: mở index dần theo chất lượng). Nguồn sinh sitemap, canonical, hreflang.';
COMMENT ON COLUMN content.seo_page.id IS 'Khoá chính.';
COMMENT ON COLUMN content.seo_page.market_code IS 'Market (NULL với trang chung).';
COMMENT ON COLUMN content.seo_page.locale_code IS 'Ngôn ngữ của trang.';
COMMENT ON COLUMN content.seo_page.page_kind IS 'area / poi / ranking / tool / glossary / page / hub.';
COMMENT ON COLUMN content.seo_page.entity_id IS 'id của thực thể (geo_area.id, poi.id...) — đa hình theo page_kind nên không có FK.';
COMMENT ON COLUMN content.seo_page.entity_key IS 'Khoá chuỗi cho thực thể không có id số (ranking_def.id, tool_code).';
COMMENT ON COLUMN content.seo_page.path IS 'Đường dẫn đầy đủ (/uk/postcode/sw1a-1aa).';
COMMENT ON COLUMN content.seo_page.canonical_path IS 'Canonical khi khác path (postcode mỏng → sector).';
COMMENT ON COLUMN content.seo_page.index_status IS 'pending / index / noindex.';
COMMENT ON COLUMN content.seo_page.index_reason IS 'Lý do quyết định (thin_content, low_sample, ok...).';
COMMENT ON COLUMN content.seo_page.quality_score IS 'Điểm chất lượng nội dung (độ khác biệt dữ liệu so với cấp cha, độ phủ chỉ số).';
COMMENT ON COLUMN content.seo_page.content_hash IS 'Hash nội dung chính để phát hiện thay đổi (cập nhật lastmod).';
COMMENT ON COLUMN content.seo_page.lastmod IS 'Lần thay đổi nội dung có ý nghĩa gần nhất (sitemap lastmod).';
COMMENT ON COLUMN content.seo_page.sitemap_shard IS 'Tên file sitemap chứa trang (uk-en-postcode-0007).';
COMMENT ON COLUMN content.seo_page.evaluated_at IS 'Lần đánh giá index gần nhất.';
CREATE INDEX seo_page_kind_status ON content.seo_page (market_code, page_kind, index_status);
CREATE INDEX seo_page_entity ON content.seo_page (page_kind, entity_id);

CREATE TABLE content.redirect (
    from_path text PRIMARY KEY,
    to_path text NOT NULL,
    status_code smallint NOT NULL DEFAULT 301 CHECK (status_code IN (301, 302, 308, 410)),
    reason text CHECK (reason IN ('postcode_terminated', 'slug_change', 'merged_area', 'removed', 'manual')),
    hit_count bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE content.redirect IS 'Chuyển hướng URL (postcode ngừng dùng, đổi slug, khu sáp nhập, trang bị gỡ = 410). Đọc bởi middleware.';
COMMENT ON COLUMN content.redirect.from_path IS 'Đường dẫn cũ.';
COMMENT ON COLUMN content.redirect.to_path IS 'Đường dẫn mới (bỏ qua khi 410).';
COMMENT ON COLUMN content.redirect.status_code IS '301 / 302 / 308 / 410.';
COMMENT ON COLUMN content.redirect.reason IS 'Lý do.';
COMMENT ON COLUMN content.redirect.hit_count IS 'Số lượt truy cập (cập nhật theo lô).';
COMMENT ON COLUMN content.redirect.created_at IS 'Thời điểm tạo.';

-- =============================================================================
-- @domain auth | Xác thực | Schema lõi Better Auth: user, session, account (OAuth/mật khẩu), verification (magic link)
-- =============================================================================

CREATE TABLE auth."user" (
    id text PRIMARY KEY,
    name text NOT NULL,
    email text NOT NULL,
    email_verified boolean NOT NULL DEFAULT false,
    image text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE auth."user" IS 'Người dùng (Better Auth). Chỉ cần cho watchlist/cảnh báo/review; xem báo cáo không cần đăng nhập.';
COMMENT ON COLUMN auth."user".id IS 'ID chuỗi do Better Auth sinh.';
COMMENT ON COLUMN auth."user".name IS 'Tên hiển thị.';
COMMENT ON COLUMN auth."user".email IS 'Email (duy nhất, so sánh không phân biệt hoa thường).';
COMMENT ON COLUMN auth."user".email_verified IS 'Đã xác minh email.';
COMMENT ON COLUMN auth."user".image IS 'Ảnh đại diện.';
COMMENT ON COLUMN auth."user".created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN auth."user".updated_at IS 'Thời điểm cập nhật.';
CREATE UNIQUE INDEX user_email_lower ON auth."user" (lower(email));

CREATE TABLE auth.session (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    token text NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    ip_address text,
    user_agent text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE auth.session IS 'Phiên đăng nhập (Better Auth).';
COMMENT ON COLUMN auth.session.id IS 'ID phiên.';
COMMENT ON COLUMN auth.session.user_id IS 'Người dùng.';
COMMENT ON COLUMN auth.session.token IS 'Token phiên.';
COMMENT ON COLUMN auth.session.expires_at IS 'Hết hạn.';
COMMENT ON COLUMN auth.session.ip_address IS 'IP (dữ liệu cá nhân — xoá theo chính sách lưu trữ).';
COMMENT ON COLUMN auth.session.user_agent IS 'User agent.';
COMMENT ON COLUMN auth.session.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN auth.session.updated_at IS 'Thời điểm cập nhật.';
CREATE INDEX session_user_id_idx ON auth.session (user_id);

CREATE TABLE auth.account (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    account_id text NOT NULL,
    provider_id text NOT NULL,
    access_token text,
    refresh_token text,
    id_token text,
    access_token_expires_at timestamptz,
    refresh_token_expires_at timestamptz,
    scope text,
    password text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_id, account_id)
);
COMMENT ON TABLE auth.account IS 'Liên kết tài khoản nhà cung cấp (Google...) hoặc mật khẩu (Better Auth).';
COMMENT ON COLUMN auth.account.id IS 'ID.';
COMMENT ON COLUMN auth.account.user_id IS 'Người dùng.';
COMMENT ON COLUMN auth.account.account_id IS 'ID tài khoản phía nhà cung cấp.';
COMMENT ON COLUMN auth.account.provider_id IS 'Nhà cung cấp (google, credential...).';
COMMENT ON COLUMN auth.account.access_token IS 'Access token OAuth (nên mã hoá ở tầng ứng dụng).';
COMMENT ON COLUMN auth.account.refresh_token IS 'Refresh token OAuth.';
COMMENT ON COLUMN auth.account.id_token IS 'ID token OIDC.';
COMMENT ON COLUMN auth.account.access_token_expires_at IS 'Hết hạn access token.';
COMMENT ON COLUMN auth.account.refresh_token_expires_at IS 'Hết hạn refresh token.';
COMMENT ON COLUMN auth.account.scope IS 'Phạm vi quyền.';
COMMENT ON COLUMN auth.account.password IS 'Hash mật khẩu (nếu bật đăng nhập mật khẩu).';
COMMENT ON COLUMN auth.account.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN auth.account.updated_at IS 'Thời điểm cập nhật.';
CREATE INDEX account_user_id_idx ON auth.account (user_id);

CREATE TABLE auth.verification (
    id text PRIMARY KEY,
    identifier text NOT NULL,
    value text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE auth.verification IS 'Mã xác minh tạm thời (magic link, xác minh email) — Better Auth.';
COMMENT ON COLUMN auth.verification.id IS 'ID.';
COMMENT ON COLUMN auth.verification.identifier IS 'Định danh (email).';
COMMENT ON COLUMN auth.verification.value IS 'Giá trị/mã.';
COMMENT ON COLUMN auth.verification.expires_at IS 'Hết hạn.';
COMMENT ON COLUMN auth.verification.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN auth.verification.updated_at IS 'Thời điểm cập nhật.';
CREATE INDEX verification_identifier ON auth.verification (identifier);

-- =============================================================================
-- @domain app | Người dùng | Hồ sơ, watchlist, quy tắc cảnh báo, sự kiện dữ liệu, thông báo, so sánh đã lưu, review, phản hồi, yêu cầu gỡ bỏ
-- =============================================================================

CREATE TABLE app.user_profile (
    user_id text PRIMARY KEY REFERENCES auth."user" (id) ON DELETE CASCADE,
    preferred_locale text REFERENCES core.locale (code),
    preferred_market text REFERENCES core.market (code),
    default_persona text REFERENCES core.persona (code),
    distance_unit text CHECK (distance_unit IN ('km', 'mi')),
    marketing_opt_in boolean NOT NULL DEFAULT false,
    consent jsonb NOT NULL DEFAULT '{}'::jsonb,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.user_profile IS 'Tuỳ chọn của người dùng, tách khỏi bảng Better Auth để không đụng schema của thư viện.';
COMMENT ON COLUMN app.user_profile.user_id IS 'Người dùng.';
COMMENT ON COLUMN app.user_profile.preferred_locale IS 'Ngôn ngữ ưa thích.';
COMMENT ON COLUMN app.user_profile.preferred_market IS 'Market hay xem.';
COMMENT ON COLUMN app.user_profile.default_persona IS 'Vai trò mặc định khi xem điểm.';
COMMENT ON COLUMN app.user_profile.distance_unit IS 'Đơn vị khoảng cách ưa thích (ghi đè mặc định market).';
COMMENT ON COLUMN app.user_profile.marketing_opt_in IS 'Đồng ý nhận email marketing (PECR/GDPR).';
COMMENT ON COLUMN app.user_profile.consent IS 'Lịch sử đồng ý {"marketing":{"at":"...","source":"signup"}}.';
COMMENT ON COLUMN app.user_profile.deleted_at IS 'Yêu cầu xoá tài khoản (job ẩn danh hoá sau thời hạn).';
COMMENT ON COLUMN app.user_profile.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN app.user_profile.updated_at IS 'Thời điểm cập nhật.';

CREATE TABLE app.watchlist (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    name text NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.watchlist IS 'Danh sách khu người dùng theo dõi (có thể nhiều danh sách: "Đi làm London", "Gần trường").';
COMMENT ON COLUMN app.watchlist.id IS 'Khoá chính.';
COMMENT ON COLUMN app.watchlist.user_id IS 'Chủ sở hữu.';
COMMENT ON COLUMN app.watchlist.name IS 'Tên danh sách.';
COMMENT ON COLUMN app.watchlist.is_default IS 'Danh sách mặc định.';
COMMENT ON COLUMN app.watchlist.created_at IS 'Thời điểm tạo.';
CREATE UNIQUE INDEX watchlist_one_default ON app.watchlist (user_id) WHERE is_default;

CREATE TABLE app.watchlist_item (
    watchlist_id bigint NOT NULL REFERENCES app.watchlist (id) ON DELETE CASCADE,
    area_id bigint NOT NULL REFERENCES core.geo_area (id),
    persona_code text REFERENCES core.persona (code),
    note text,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (watchlist_id, area_id)
);
COMMENT ON TABLE app.watchlist_item IS 'Khu trong watchlist.';
COMMENT ON COLUMN app.watchlist_item.watchlist_id IS 'Watchlist.';
COMMENT ON COLUMN app.watchlist_item.area_id IS 'Khu.';
COMMENT ON COLUMN app.watchlist_item.persona_code IS 'Vai trò dùng để xem điểm khu này.';
COMMENT ON COLUMN app.watchlist_item.note IS 'Ghi chú cá nhân.';
COMMENT ON COLUMN app.watchlist_item.added_at IS 'Thời điểm thêm.';
CREATE INDEX watchlist_item_area ON app.watchlist_item (area_id);

CREATE TABLE app.data_event (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_code text NOT NULL REFERENCES core.market (code),
    area_id bigint NOT NULL REFERENCES core.geo_area (id) ON DELETE CASCADE,
    event_kind text NOT NULL CHECK (event_kind IN ('new_sales', 'price_change', 'crime_change', 'school_rating', 'new_zone', 'flood_alert', 'score_change', 'new_data')),
    period date,
    payload jsonb NOT NULL,
    release_id bigint REFERENCES ops.dataset_release (id),
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.data_event IS 'Sự kiện thay đổi dữ liệu theo khu do ETL sinh ra (không phụ thuộc người dùng). Bộ gửi thông báo đối chiếu với alert_rule để tạo notification.';
COMMENT ON COLUMN app.data_event.id IS 'Khoá chính.';
COMMENT ON COLUMN app.data_event.market_code IS 'Market.';
COMMENT ON COLUMN app.data_event.area_id IS 'Khu bị ảnh hưởng.';
COMMENT ON COLUMN app.data_event.event_kind IS 'new_sales / price_change / crime_change / school_rating / new_zone / flood_alert / score_change / new_data.';
COMMENT ON COLUMN app.data_event.period IS 'Kỳ dữ liệu.';
COMMENT ON COLUMN app.data_event.payload IS 'Chi tiết (số giao dịch mới, % thay đổi...).';
COMMENT ON COLUMN app.data_event.release_id IS 'Release gây ra sự kiện.';
COMMENT ON COLUMN app.data_event.created_at IS 'Thời điểm tạo.';
CREATE INDEX data_event_area_time ON app.data_event (area_id, created_at DESC);

CREATE TABLE app.alert_rule (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    area_id bigint NOT NULL REFERENCES core.geo_area (id),
    event_kind text NOT NULL,
    threshold jsonb NOT NULL DEFAULT '{}'::jsonb,
    frequency text NOT NULL DEFAULT 'monthly' CHECK (frequency IN ('instant', 'weekly', 'monthly')),
    is_active boolean NOT NULL DEFAULT true,
    last_sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, area_id, event_kind)
);
COMMENT ON TABLE app.alert_rule IS 'Quy tắc cảnh báo của người dùng cho một khu và một loại sự kiện.';
COMMENT ON COLUMN app.alert_rule.id IS 'Khoá chính.';
COMMENT ON COLUMN app.alert_rule.user_id IS 'Người dùng.';
COMMENT ON COLUMN app.alert_rule.area_id IS 'Khu.';
COMMENT ON COLUMN app.alert_rule.event_kind IS 'Loại sự kiện (khớp app.data_event.event_kind).';
COMMENT ON COLUMN app.alert_rule.threshold IS 'Ngưỡng ({"min_change_pct":10}).';
COMMENT ON COLUMN app.alert_rule.frequency IS 'instant / weekly / monthly (gộp email).';
COMMENT ON COLUMN app.alert_rule.is_active IS 'Đang bật.';
COMMENT ON COLUMN app.alert_rule.last_sent_at IS 'Lần gửi gần nhất.';
COMMENT ON COLUMN app.alert_rule.created_at IS 'Thời điểm tạo.';
CREATE INDEX alert_rule_area_kind ON app.alert_rule (area_id, event_kind) WHERE is_active;

CREATE TABLE app.notification (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    channel text NOT NULL CHECK (channel IN ('email', 'web_push')),
    template text NOT NULL,
    locale_code text REFERENCES core.locale (code),
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'bounced', 'suppressed')),
    provider_message_id text,
    error text,
    queued_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz
);
COMMENT ON TABLE app.notification IS 'Thông báo gửi tới người dùng (email tổng hợp, web push) và trạng thái gửi.';
COMMENT ON COLUMN app.notification.id IS 'Khoá chính.';
COMMENT ON COLUMN app.notification.user_id IS 'Người nhận.';
COMMENT ON COLUMN app.notification.channel IS 'email / web_push.';
COMMENT ON COLUMN app.notification.template IS 'Mẫu (alert_digest_monthly...).';
COMMENT ON COLUMN app.notification.locale_code IS 'Ngôn ngữ nội dung.';
COMMENT ON COLUMN app.notification.payload IS 'Dữ liệu render.';
COMMENT ON COLUMN app.notification.status IS 'queued / sent / failed / bounced / suppressed.';
COMMENT ON COLUMN app.notification.provider_message_id IS 'ID tin nhắn phía nhà cung cấp (Resend).';
COMMENT ON COLUMN app.notification.error IS 'Lỗi gửi.';
COMMENT ON COLUMN app.notification.queued_at IS 'Thời điểm xếp hàng.';
COMMENT ON COLUMN app.notification.sent_at IS 'Thời điểm gửi.';

CREATE TABLE app.notification_event (
    notification_id bigint NOT NULL REFERENCES app.notification (id) ON DELETE CASCADE,
    data_event_id bigint NOT NULL REFERENCES app.data_event (id) ON DELETE CASCADE,
    PRIMARY KEY (notification_id, data_event_id)
);
COMMENT ON TABLE app.notification_event IS 'Sự kiện dữ liệu nào nằm trong thông báo nào (tránh gửi trùng).';
COMMENT ON COLUMN app.notification_event.notification_id IS 'Thông báo.';
COMMENT ON COLUMN app.notification_event.data_event_id IS 'Sự kiện.';

CREATE TABLE app.saved_comparison (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    share_token text NOT NULL UNIQUE,
    user_id text REFERENCES auth."user" (id) ON DELETE SET NULL,
    market_code text NOT NULL REFERENCES core.market (code),
    area_ids bigint[] NOT NULL CHECK (cardinality(area_ids) BETWEEN 2 AND 4),
    persona_code text REFERENCES core.persona (code),
    custom_weights jsonb,
    view_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE app.saved_comparison IS 'So sánh 2–4 khu được lưu/chia sẻ qua link (có thể ẩn danh). Link chia sẻ là kênh lan truyền.';
COMMENT ON COLUMN app.saved_comparison.id IS 'Khoá chính.';
COMMENT ON COLUMN app.saved_comparison.share_token IS 'Token ngẫu nhiên trong URL chia sẻ.';
COMMENT ON COLUMN app.saved_comparison.user_id IS 'Người tạo (NULL = ẩn danh).';
COMMENT ON COLUMN app.saved_comparison.market_code IS 'Market.';
COMMENT ON COLUMN app.saved_comparison.area_ids IS 'Danh sách id khu (không ràng buộc FK vì là mảng; kiểm tra ở tầng ứng dụng).';
COMMENT ON COLUMN app.saved_comparison.persona_code IS 'Vai trò.';
COMMENT ON COLUMN app.saved_comparison.custom_weights IS 'Trọng số tuỳ chỉnh từ thanh trượt.';
COMMENT ON COLUMN app.saved_comparison.view_count IS 'Số lượt xem.';
COMMENT ON COLUMN app.saved_comparison.created_at IS 'Thời điểm tạo.';

CREATE TABLE app.review (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    area_id bigint NOT NULL REFERENCES core.geo_area (id),
    relationship text NOT NULL CHECK (relationship IN ('resident', 'former_resident', 'worker', 'visitor')),
    years_lived smallint,
    rating_overall smallint NOT NULL CHECK (rating_overall BETWEEN 1 AND 5),
    ratings jsonb NOT NULL DEFAULT '{}'::jsonb,
    title text,
    body text NOT NULL,
    locale_code text REFERENCES core.locale (code),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'removed')),
    moderation_note text,
    moderated_by text,
    moderated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, area_id)
);
COMMENT ON TABLE app.review IS 'Review của cư dân (giai đoạn 3). Bắt buộc kiểm duyệt trước khi hiển thị; không dùng trong điểm số chính thức.';
COMMENT ON COLUMN app.review.id IS 'Khoá chính.';
COMMENT ON COLUMN app.review.user_id IS 'Tác giả.';
COMMENT ON COLUMN app.review.area_id IS 'Khu được review (thường cấp sector/district/town).';
COMMENT ON COLUMN app.review.relationship IS 'resident / former_resident / worker / visitor.';
COMMENT ON COLUMN app.review.years_lived IS 'Số năm sống ở khu.';
COMMENT ON COLUMN app.review.rating_overall IS 'Điểm tổng 1–5.';
COMMENT ON COLUMN app.review.ratings IS 'Điểm theo khía cạnh {"safety":4,"transport":5}.';
COMMENT ON COLUMN app.review.title IS 'Tiêu đề.';
COMMENT ON COLUMN app.review.body IS 'Nội dung.';
COMMENT ON COLUMN app.review.locale_code IS 'Ngôn ngữ viết.';
COMMENT ON COLUMN app.review.status IS 'pending / approved / rejected / removed.';
COMMENT ON COLUMN app.review.moderation_note IS 'Ghi chú kiểm duyệt.';
COMMENT ON COLUMN app.review.moderated_by IS 'Người kiểm duyệt.';
COMMENT ON COLUMN app.review.moderated_at IS 'Thời điểm kiểm duyệt.';
COMMENT ON COLUMN app.review.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN app.review.updated_at IS 'Thời điểm cập nhật.';
CREATE INDEX review_area_approved ON app.review (area_id) WHERE status = 'approved';

CREATE TABLE app.review_report (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id bigint NOT NULL REFERENCES app.review (id) ON DELETE CASCADE,
    reporter_user_id text REFERENCES auth."user" (id) ON DELETE SET NULL,
    reason text NOT NULL CHECK (reason IN ('spam', 'offensive', 'defamatory', 'personal_data', 'inaccurate', 'other')),
    details text,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);
COMMENT ON TABLE app.review_report IS 'Báo cáo vi phạm đối với review (phỉ báng, dữ liệu cá nhân...).';
COMMENT ON COLUMN app.review_report.id IS 'Khoá chính.';
COMMENT ON COLUMN app.review_report.review_id IS 'Review bị báo cáo.';
COMMENT ON COLUMN app.review_report.reporter_user_id IS 'Người báo cáo (NULL = ẩn danh).';
COMMENT ON COLUMN app.review_report.reason IS 'spam / offensive / defamatory / personal_data / inaccurate / other.';
COMMENT ON COLUMN app.review_report.details IS 'Chi tiết.';
COMMENT ON COLUMN app.review_report.created_at IS 'Thời điểm báo cáo.';
COMMENT ON COLUMN app.review_report.resolved_at IS 'Thời điểm xử lý xong.';

CREATE TABLE app.data_feedback (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text REFERENCES auth."user" (id) ON DELETE SET NULL,
    area_id bigint REFERENCES core.geo_area (id),
    poi_id bigint REFERENCES core.poi (id),
    metric_id text REFERENCES core.metric (id),
    page_path text,
    message text NOT NULL,
    contact_email text,
    status text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'triaged', 'fixed', 'wont_fix', 'duplicate')),
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);
COMMENT ON TABLE app.data_feedback IS 'Người dùng báo lỗi dữ liệu (nút "Báo sai" cạnh mỗi chỉ số). KPI chất lượng dữ liệu.';
COMMENT ON COLUMN app.data_feedback.id IS 'Khoá chính.';
COMMENT ON COLUMN app.data_feedback.user_id IS 'Người báo (NULL = ẩn danh).';
COMMENT ON COLUMN app.data_feedback.area_id IS 'Khu liên quan.';
COMMENT ON COLUMN app.data_feedback.poi_id IS 'POI liên quan.';
COMMENT ON COLUMN app.data_feedback.metric_id IS 'Chỉ số liên quan.';
COMMENT ON COLUMN app.data_feedback.page_path IS 'Trang phát sinh.';
COMMENT ON COLUMN app.data_feedback.message IS 'Nội dung.';
COMMENT ON COLUMN app.data_feedback.contact_email IS 'Email liên hệ (tuỳ chọn, xoá sau khi xử lý).';
COMMENT ON COLUMN app.data_feedback.status IS 'new / triaged / fixed / wont_fix / duplicate.';
COMMENT ON COLUMN app.data_feedback.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN app.data_feedback.resolved_at IS 'Thời điểm xử lý.';

CREATE TABLE app.takedown_request (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requester_email text NOT NULL,
    page_path text NOT NULL,
    request_kind text NOT NULL CHECK (request_kind IN ('hide_transaction', 'remove_review', 'gdpr_erasure', 'copyright', 'other')),
    details text,
    status text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'in_progress', 'actioned', 'rejected')),
    action_taken text,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);
COMMENT ON TABLE app.takedown_request IS 'Yêu cầu gỡ/ẩn nội dung (ẩn giao dịch, xoá review, quyền xoá GDPR). Cam kết xử lý trong 1 ngày làm việc.';
COMMENT ON COLUMN app.takedown_request.id IS 'Khoá chính.';
COMMENT ON COLUMN app.takedown_request.requester_email IS 'Email người yêu cầu.';
COMMENT ON COLUMN app.takedown_request.page_path IS 'Trang liên quan.';
COMMENT ON COLUMN app.takedown_request.request_kind IS 'hide_transaction / remove_review / gdpr_erasure / copyright / other.';
COMMENT ON COLUMN app.takedown_request.details IS 'Chi tiết.';
COMMENT ON COLUMN app.takedown_request.status IS 'new / in_progress / actioned / rejected.';
COMMENT ON COLUMN app.takedown_request.action_taken IS 'Hành động đã thực hiện.';
COMMENT ON COLUMN app.takedown_request.created_at IS 'Thời điểm nhận.';
COMMENT ON COLUMN app.takedown_request.resolved_at IS 'Thời điểm xử lý xong.';

CREATE TABLE app.hidden_transaction (
    market_code text NOT NULL REFERENCES core.market (code),
    transaction_ref text NOT NULL,
    takedown_id bigint REFERENCES app.takedown_request (id),
    hidden_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (market_code, transaction_ref)
);
COMMENT ON TABLE app.hidden_transaction IS 'Danh sách giao dịch bị ẩn theo yêu cầu (áp dụng mọi market). ETL và API giao dịch luôn loại trừ các mã này, kể cả sau khi nạp lại dữ liệu.';
COMMENT ON COLUMN app.hidden_transaction.market_code IS 'Market.';
COMMENT ON COLUMN app.hidden_transaction.transaction_ref IS 'Mã giao dịch gốc (UK: transaction_id của Price Paid).';
COMMENT ON COLUMN app.hidden_transaction.takedown_id IS 'Yêu cầu gốc.';
COMMENT ON COLUMN app.hidden_transaction.hidden_at IS 'Thời điểm ẩn.';

-- =============================================================================
-- @domain billing | Kiếm tiền (tương lai) | Gói, tính năng, quyền theo gói, subscription, API client/key, thống kê dùng API
-- =============================================================================

CREATE TABLE billing.feature (
    code text PRIMARY KEY,
    description text NOT NULL,
    unit text
);
COMMENT ON TABLE billing.feature IS 'Tính năng có thể giới hạn theo gói: ad_free, alerts_max, compare_max, pdf_export, api_requests_month...';
COMMENT ON COLUMN billing.feature.code IS 'Mã tính năng.';
COMMENT ON COLUMN billing.feature.description IS 'Mô tả.';
COMMENT ON COLUMN billing.feature.unit IS 'Đơn vị giới hạn (count, requests/month) hoặc NULL nếu bật/tắt.';

CREATE TABLE billing.plan (
    code text PRIMARY KEY,
    name_i18n jsonb NOT NULL,
    price_minor integer NOT NULL DEFAULT 0 CHECK (price_minor >= 0),
    currency_code char(3),
    billing_interval text CHECK (billing_interval IN ('month', 'year', 'one_off')),
    audience text NOT NULL DEFAULT 'consumer' CHECK (audience IN ('consumer', 'api', 'enterprise')),
    is_public boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE billing.plan IS 'Gói dịch vụ. Giai đoạn đầu chỉ có "free" (mọi người dùng). Thiết kế sẵn để bật gói trả phí/API mà không đổi schema.';
COMMENT ON COLUMN billing.plan.code IS 'Mã gói (free, pro, api_starter).';
COMMENT ON COLUMN billing.plan.name_i18n IS 'Tên theo locale.';
COMMENT ON COLUMN billing.plan.price_minor IS 'Giá theo đơn vị nhỏ nhất (pence/cent).';
COMMENT ON COLUMN billing.plan.currency_code IS 'Tiền tệ.';
COMMENT ON COLUMN billing.plan.billing_interval IS 'month / year / one_off.';
COMMENT ON COLUMN billing.plan.audience IS 'consumer / api / enterprise.';
COMMENT ON COLUMN billing.plan.is_public IS 'Hiển thị trên trang giá.';
COMMENT ON COLUMN billing.plan.is_active IS 'Còn bán.';
COMMENT ON COLUMN billing.plan.created_at IS 'Thời điểm tạo.';

CREATE TABLE billing.plan_feature (
    plan_code text NOT NULL REFERENCES billing.plan (code) ON DELETE CASCADE,
    feature_code text NOT NULL REFERENCES billing.feature (code),
    limit_value integer,
    PRIMARY KEY (plan_code, feature_code)
);
COMMENT ON TABLE billing.plan_feature IS 'Quyền của từng gói. Ứng dụng kiểm tra quyền qua bảng này thay vì hard-code.';
COMMENT ON COLUMN billing.plan_feature.plan_code IS 'Gói.';
COMMENT ON COLUMN billing.plan_feature.feature_code IS 'Tính năng.';
COMMENT ON COLUMN billing.plan_feature.limit_value IS 'Giới hạn (NULL = không giới hạn / bật).';

CREATE TABLE billing.subscription (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES auth."user" (id) ON DELETE CASCADE,
    plan_code text NOT NULL REFERENCES billing.plan (code),
    status text NOT NULL CHECK (status IN ('trialing', 'active', 'past_due', 'canceled', 'expired')),
    provider text NOT NULL DEFAULT 'stripe',
    provider_subscription_id text UNIQUE,
    current_period_start timestamptz,
    current_period_end timestamptz,
    cancel_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE billing.subscription IS 'Đăng ký gói trả phí (tương lai). Người dùng không có subscription active = gói free.';
COMMENT ON COLUMN billing.subscription.id IS 'Khoá chính.';
COMMENT ON COLUMN billing.subscription.user_id IS 'Người dùng.';
COMMENT ON COLUMN billing.subscription.plan_code IS 'Gói.';
COMMENT ON COLUMN billing.subscription.status IS 'trialing / active / past_due / canceled / expired.';
COMMENT ON COLUMN billing.subscription.provider IS 'Cổng thanh toán.';
COMMENT ON COLUMN billing.subscription.provider_subscription_id IS 'ID phía cổng thanh toán.';
COMMENT ON COLUMN billing.subscription.current_period_start IS 'Đầu kỳ.';
COMMENT ON COLUMN billing.subscription.current_period_end IS 'Cuối kỳ.';
COMMENT ON COLUMN billing.subscription.cancel_at IS 'Lịch huỷ.';
COMMENT ON COLUMN billing.subscription.created_at IS 'Thời điểm tạo.';
COMMENT ON COLUMN billing.subscription.updated_at IS 'Thời điểm cập nhật.';
CREATE UNIQUE INDEX subscription_one_active ON billing.subscription (user_id) WHERE status IN ('trialing', 'active', 'past_due');

CREATE TABLE billing.api_client (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_user_id text NOT NULL REFERENCES auth."user" (id),
    name text NOT NULL,
    plan_code text NOT NULL REFERENCES billing.plan (code),
    allowed_origins text[],
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'closed')),
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE billing.api_client IS 'Khách hàng B2B dùng API/widget (môi giới, trang tin đăng, trường đại học) — tương lai.';
COMMENT ON COLUMN billing.api_client.id IS 'Khoá chính.';
COMMENT ON COLUMN billing.api_client.owner_user_id IS 'Người quản lý.';
COMMENT ON COLUMN billing.api_client.name IS 'Tên tổ chức/ứng dụng.';
COMMENT ON COLUMN billing.api_client.plan_code IS 'Gói API.';
COMMENT ON COLUMN billing.api_client.allowed_origins IS 'Domain được nhúng widget.';
COMMENT ON COLUMN billing.api_client.status IS 'active / suspended / closed.';
COMMENT ON COLUMN billing.api_client.created_at IS 'Thời điểm tạo.';

CREATE TABLE billing.api_key (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id bigint NOT NULL REFERENCES billing.api_client (id) ON DELETE CASCADE,
    key_prefix text NOT NULL,
    key_hash text NOT NULL UNIQUE,
    scopes text[] NOT NULL DEFAULT '{}',
    last_used_at timestamptz,
    expires_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE billing.api_key IS 'API key (chỉ lưu hash, hiển thị prefix để nhận diện).';
COMMENT ON COLUMN billing.api_key.id IS 'Khoá chính.';
COMMENT ON COLUMN billing.api_key.client_id IS 'Client.';
COMMENT ON COLUMN billing.api_key.key_prefix IS 'Vài ký tự đầu của key (zc_live_ab12...).';
COMMENT ON COLUMN billing.api_key.key_hash IS 'Hash SHA-256 của key.';
COMMENT ON COLUMN billing.api_key.scopes IS 'Quyền (areas:read, scores:read...).';
COMMENT ON COLUMN billing.api_key.last_used_at IS 'Lần dùng gần nhất.';
COMMENT ON COLUMN billing.api_key.expires_at IS 'Hết hạn.';
COMMENT ON COLUMN billing.api_key.revoked_at IS 'Thời điểm thu hồi.';
COMMENT ON COLUMN billing.api_key.created_at IS 'Thời điểm tạo.';

CREATE TABLE billing.api_usage_daily (
    client_id bigint NOT NULL REFERENCES billing.api_client (id) ON DELETE CASCADE,
    day date NOT NULL,
    endpoint text NOT NULL,
    request_count integer NOT NULL DEFAULT 0,
    error_count integer NOT NULL DEFAULT 0,
    PRIMARY KEY (client_id, day, endpoint)
);
COMMENT ON TABLE billing.api_usage_daily IS 'Thống kê dùng API theo ngày (tính phí, giới hạn quota).';
COMMENT ON COLUMN billing.api_usage_daily.client_id IS 'Client.';
COMMENT ON COLUMN billing.api_usage_daily.day IS 'Ngày.';
COMMENT ON COLUMN billing.api_usage_daily.endpoint IS 'Endpoint.';
COMMENT ON COLUMN billing.api_usage_daily.request_count IS 'Số request.';
COMMENT ON COLUMN billing.api_usage_daily.error_count IS 'Số request lỗi.';

-- =============================================================================
-- Trigger updated_at cho mọi bảng có cột updated_at
-- =============================================================================
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT c.table_schema, c.table_name
        FROM information_schema.columns c
        JOIN information_schema.tables t USING (table_schema, table_name)
        WHERE c.column_name = 'updated_at'
          AND t.table_type = 'BASE TABLE'
          AND c.table_schema IN ('ops', 'core', 'mkt_uk', 'content', 'auth', 'app', 'billing')
    LOOP
        EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I.%I FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()', r.table_schema, r.table_name);
    END LOOP;
END $$;
