# web: ZoneCheck (Next.js fullstack)

Giao diện dựa trên `demo-web/`, kiến trúc theo `PLAN.md` mục 3–5. Dữ liệu đọc trực tiếp từ PostgreSQL/PostGIS (schema `erd/schema.sql`) mà `get-data/` nạp vào.

## Chạy

```bash
../auth_key/vps/tunnel.sh -f          # mở tunnel 127.0.0.1:55432 → Postgres trên VPS
cp .env.example .env.local            # điền DATABASE_URL (bỏ qua nếu đã có)
npm install
npm run dev                           # http://localhost:3000
npm run build && npm start            # bản production (build cần DB để prerender vài trang mẫu)
```

Qua tunnel, mỗi truy vấn tốn khoảng 0,4–0,5 giây, nên lần mở đầu một trang khu vực mất 10–15 giây. Các lần sau phục vụ từ cache (khoảng 0,1 giây). Khi web chạy cùng máy hoặc cùng datacenter với DB, lần đầu chỉ còn dưới 1 giây.

## Trang

| URL | Nội dung |
|---|---|
| `/` | Tìm kiếm, chọn vai trò, khu phổ biến, công cụ, xếp hạng |
| `/uk/{postcode,sector,district,town,area,region}/{slug}` | Báo cáo khu vực: điểm theo vai trò, bản đồ, 15 section (có "Flood and ground risk" và checklist "Before you make an offer") |
| `/uk/school/{urn-slug}`, `/uk/station/{crs-slug}` | Trang trường học (Ofsted, kết quả thi) và trang ga |
| `/uk/compare?a=sector:se15-4&b=…` | So sánh tối đa 4 khu |
| `/uk/where-to-live?who=family&in=region:london&max=500000&flood=1` | Tìm ngược: xếp sector/district theo điểm vai trò (`core.area_overall_score`), lọc vùng, ngân sách, lũ, tội phạm, ga |
| `/uk/rankings`, `/uk/rankings/{metric}/{england-and-wales\|lad-slug}` | Xếp hạng |
| `/uk/tools/{stamp-duty,mortgage-affordability,moving-costs,rent-vs-buy}` | Máy tính |
| `/sources`, `/methodology`, `/glossary` | Nguồn và ngày cập nhật, phương pháp tính điểm, thuật ngữ |
| `/api/search?q=` | Tìm postcode, địa danh, trường, ga |
| `/api/uk/map/{crime,flood,planning,green,amenities,schools,transport,areas,locate}` | GeoJSON cho bản đồ, theo `bbox` |
| `/sitemap/{0..5}.xml`, `/robots.txt` | SEO. Postcode unit để `noindex` với canonical trỏ lên sector (PLAN 3.3) |

## Cấu trúc

```
src/
  app/[lang]/…          trang (lang là root param; en không có tiền tố URL, xem src/proxy.ts)
  app/api/…             route handler
  markets/              MarketAdapter (types.ts) + uk/ (cấp địa lý, parse postcode, mô hình điểm, thuế)
  server/               truy vấn DB (area, poi, search, rankings, meta, maplayers)
  components/           report/ (section, bản đồ, điểm), compare/, tools/, home/
  i18n/ + messages/     từ điển giao diện (MVP chỉ en, kiến trúc sẵn đa ngôn ngữ)
  lib/db.ts             kết nối Postgres chỉ đọc, có statement_timeout
```

## Ghi chú kỹ thuật

- **Next.js 16.4 + Cache Components.** Dữ liệu được cache bằng `"use cache"` + `cacheLife("days")` + `cacheTag("market:uk")`. Sau khi ETL publish, gọi `revalidateTag("market:uk")` để làm mới.
- **Mỗi lần nạp cache dùng client DB riêng** (`scoped()` trong `lib/db.ts`). Next không cho một scope `"use cache"` chờ promise tạo ngoài scope, mà hàng đợi của pool dùng chung chính là kiểu promise đó. Bên trong một scope cache, không gọi lồng hàm cache khác (dùng bản `load…` không cache), vì Next sẽ gộp lời gọi trùng giữa các scope.
- **Collation DB là `C.UTF-8`**, nên `LIKE 'SE15 4%'` không dùng được index btree. Hãy dùng điều kiện khoảng `>= 'SE15 4 ' and < 'SE15 4~'`, hoặc đi qua index `postcode.district`.
- **Phần phụ của báo cáo "mềm":** EPC, giao dịch, POI, vùng… nếu lỗi hoặc quá 9 giây thì chỉ ẩn phần đó và ghi log `[area] … failed for …`.
- **Tailwind chạy qua PostCSS (`@tailwindcss/postcss`), không qua loader `@tailwindcss/turbopack`.** Loader turbopack làm `next dev` phát sự kiện HMR mỗi lần trình duyệt tải trang, nên trang reload liên tục ("HMR hash mismatch"). `globals.css` dùng `source(none)` + `@source "../"` để Tailwind chỉ quét `src/`.
- **Postcode sector/district không có polygon chính thức.** Ranh giới trên bản đồ là concave hull của các postcode đang dùng, có ghi chú "không phải đường ranh chính thức".

## Điểm khu (score) và phân vị

Điểm 8 nhóm × 6 vai trò dùng đúng mô hình `uk.v1` của `get-data/uk/derive/scoring.py` (bản sao ở `src/markets/uk/scoring.ts`). Thứ tự ưu tiên:

1. Đọc `core.area_category_score` nếu bước ETL `scoring` đã chạy.
2. Nếu chưa, tính lại từ `core.metric_value.percentile`.
3. Nếu cột đó còn trống, dùng bảng phân vị dự phòng `data/quantiles/<level>.json`, tạo bằng:

```bash
npm run quantiles            # mọi cấp; mỗi cấp khoảng 1–2 phút trên DB, chỉ đọc
npm run quantiles sector     # một cấp
```

Khi chưa có cả ba nguồn trên, trang vẫn hiển thị mọi số liệu, nhưng ẩn thanh phân vị và hiện thông báo "Scores appear once…".

## Kiểm tra rủi ro (section `risk`, `components/report/risk.tsx`)

- **Trang postcode:** kiểm tra đúng tại tâm postcode trên `core.zone` (lũ, radon, mỏ than, GeoSure, lũ đã xảy ra, xói lở, AQMA), khoảng cách tới bãi rác, `mkt_uk.postcode_rofrs` và `mkt_uk.postcode_noise` (bỏ qua nếu bảng chưa có).
- **Sector trở lên:** dùng tỷ lệ dân `uk.zone.*_share` do `derive hazards` + `rollup` tạo. Chưa có chỉ số nào thì ẩn ô đó.
- Checklist "Before you make an offer" sinh từ các ô vàng/đỏ + quy hoạch/listed/tribunal. Chỉ hiện ở postcode, sector, district.
- MP (`admin.westminster_const` + `mkt_uk.mp`) và CQC (`poi_rating` scheme `cqc`) tự hiện khi ETL nạp xong.

## Việc còn lại (theo PLAN)

- AdSense + CMP (khung quảng cáo đã giữ sẵn kích thước), Plausible, Sentry.
- Broadband/mobile (chờ ETL Ofcom).
- EPC và £/m² ở cấp district trở lên: nên tính sẵn bằng ETL (tính trực tiếp quá chậm).
- Tài khoản, watchlist, tóm tắt AI, PDF động, thêm ngôn ngữ (giai đoạn 2).
