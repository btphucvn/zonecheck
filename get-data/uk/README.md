# get-data/uk: tool cào dữ liệu UK

Danh mục theo PLAN.md §2.2. `python -m uk list` in trạng thái hiện tại.

## Đã có

| Tool | dataset_id | Nguồn / cách lấy bản mới nhất | Tuỳ chọn |
|---|---|---|---|
| `onspd` | uk.ons.onspd | ArcGIS search "ONS Postcode Directory (Tháng Năm)" → zip CSV | |
| `os_codepoint_open` | uk.os.codepoint_open | OS Downloads API (kiểm md5) | |
| `os_open_names` | uk.os.open_names | OS Downloads API | |
| `os_open_uprn` | uk.os.open_uprn | OS Downloads API | |
| `os_open_greenspace` | uk.os.open_greenspace | OS Downloads API (GeoPackage) | |
| `boundaries_oa21` / `_lsoa21` / `_msoa21` | uk.ons.boundaries_* | ArcGIS FeatureServer BGC bản V cao nhất → GeoJSON EPSG:4326 | |
| `boundaries_lad` / `_rgn` | uk.ons.boundaries_* | ArcGIS, chọn bản (Tháng Năm) mới nhất | |
| `ppd` | uk.land_registry.ppd | S3 Land Registry, version theo Last-Modified | `--mode complete\|monthly\|year`, `--year` |
| `uk_hpi` | uk.land_registry.hpi | `UK-HPI-full-file-YYYY-MM.csv`, dò lùi 8 tháng | |
| `pipr` | uk.ons.pipr | ONS dataset page `/data` JSON | |
| `ons_income_msoa` | uk.ons.income_msoa | ONS dataset page `/data` JSON | |
| `police` | uk.police.street_crime | `/api/crimes-street-dates` → `archive/YYYY-MM.zip` (36 tháng) + danh sách lực lượng theo tháng | `--month` |
| `gias` | uk.dfe.gias | `edubasealldataYYYYMMDD.csv` + links, dò lùi 10 ngày | |
| `ofsted` | uk.ofsted.schools_mi | gov.uk Content API, file "latest inspections as at …" mới nhất + "year to date" | |
| `census2021` | uk.ons.census2021 | Nomis bulk zip, mặc định 20 bảng TS | `--tables ts001,ts054`, `--all-tables` |
| `iod2025` | uk.mhclg.iod2025 | gov.uk Content API, File 7 CSV | `--all-files` |
| `journey_time` | uk.dft.journey_time | gov.uk Content API, bảng JTS05xx (LSOA) | `--all-files` |
| `naptan` | uk.dft.naptan | NaPTAN API CSV | |
| `fsa` | uk.fsa.food_hygiene | FSA API v2 `/Authorities` → XML từng LA (4 luồng) | |
| `nhs_ods` | uk.nhs.ods | ODS report: epraccur (GP), edispensary (nhà thuốc), egdpprac (nha khoa), ets (cơ sở trust) | |
| `defra_pcm` | uk.defra.pcm | `mappm25{y}g`, `mappm10{y}g`, `mapno2{y}` năm mới nhất có đủ | `--year` |
| `ea_flood_areas` | uk.ea.flood_areas | EA Flood Monitoring API (khu cảnh báo lũ) | |

### Nguồn bổ sung (đợt 2)

| Tool | dataset_id | Ghi chú |
|---|---|---|
| `epc` | uk.mhclg.epc_domestic | Cần `EPC_API_KEY`; bulk zip ~8 GB (CSV theo năm) |
| `dfe_performance` | uk.dfe.school_performance | KS2/KS4/KS5 theo trường, 4 năm học (UA trình duyệt) |
| `wimd`, `wales_schools` | uk.welsh_gov.* | WIMD 2025 (LSOA 2021), danh sách trường Wales |
| `orr_station_usage` | uk.orr.station_usage | Lượt khách theo ga + mã CRS |
| `transport_connectivity` | uk.dft.connectivity | DfT connectivity 2025 theo OA/LSOA (thay JTS 2019) |
| `council_tax` | uk.council_tax | Mức band A–I theo LA (England + Wales) + VOA CTSOP1.1 |
| `planning_data` | uk.mhclg.planning_data | Conservation, Article 4, green belt, TPO, listed building |
| `natural_england` | uk.ne.designations | SSSI, National Parks, National Landscapes, LNR |
| `ea_flood_zones` | uk.ea.flood_zones | Flood Map for Planning (Zone 2/3, storage) |
| `police_force_areas` | uk.ons.pfa | Ranh giới lực lượng cảnh sát (xác định vùng thiếu dữ liệu tội phạm) |
| `ea_rofsw` | uk.ea.rofsw | Lũ nước mặt NaFRA2: lưới lớp High/Medium/Low 5 m lấy qua WMS (xem dưới) | `--workers`, `--pause` |
| `ofcom_connected_nations`, `nhs_gp_patients` | uk.ofcom.connected_nations, uk.nhs.gp_patients | Tải tay bằng Chrome thật (`uk/manual/fetch.py`) |

**RoFSW (lũ nước mặt):** bản vector có 4–12 triệu polygon pixel 2 m mỗi lớp. DSP từ chối tải trọn bộ
("requested too much data"), còn tải theo vùng thì mất khoảng 45 giây cho 4 km². Vì vậy lấy WMS GetMap theo ô 10 km ở 5 m/pixel, kèm style
SLD tự định nghĩa (mỗi `risk_band` một màu, không khử răng cưa), rồi giải mã thành PNG xám (1 = High, 2 = Medium, 3 = Low) kèm `.pgw`.
Chỉ tải ô có postcode England (1.467 ô, khoảng 300 MB, 20 phút). Tường lửa EA (Azure) trả 403 khi gọi dồn: mặc định 2 luồng,
nghỉ 0,5 giây giữa các request, gặp 403 thì nghỉ 2 phút. Tải dở thì chạy lại để resume.

### Nguồn bổ sung (đợt 3, `sources/extra2.py`)

| Tool | dataset_id | Ghi chú |
|---|---|---|
| `gp_patient_survey` | uk.nhs.gpps | GP Patient Survey: CSV theo phòng khám trên gp-patient.co.uk (`/latest-survey/results`, link `practice-data-csv`) |
| `hmlr_ccod`, `hmlr_ocod` | uk.land_registry.ccod / .ocod | HMLR công ty UK / nước ngoài sở hữu nhà đất. Cần `HMLR_API_KEY` **và ký licence từng dataset** trên use-land-property-data.service.gov.uk |
| `hmlr_leases` | uk.land_registry.leases | HMLR Registered Leases (freemium): cần xin quyền truy cập trên web trước |
| `dwp_uc` | uk.dwp.uc_people | DWP Stat-Xplore API (`STATXPLORE_API_KEY`): người nhận UC theo LSOA × có/không việc làm, tháng mới nhất đã tách việc làm |
| `nrw_rofsw` | uk.nrw.rofsw | NRW lũ nước mặt (Wales) qua WFS, lọc BBOX theo ô 10 km có postcode Wales, lưu `nrw_sw_XXX_YYY.json.gz` (EPSG:27700) |

**Lũ nước mặt Wales:** lớp NRW có ~2,8 triệu polygon (5,6 GB GeoJSON), nhưng tải theo ô 10 km thì mỗi lần chỉ
vài chục nghìn polygon, RAM thấp. Loader `nrw_rofsw` dựng STRtree (shapely) từng ô và lấy mẫu tại toạ độ UPRN của
nhà có EPC, ghi cùng chỉ số `uk.zone.sw_*_share` với England (mỗi loader chỉ thay LSOA của nước mình).
Lần đầu chạy ở máy local (`get-data/.venv` + tunnel DB), cập nhật sau chạy được trên VPS.

`ea_flood_areas`: danh sách khu kèm polygon từng khu (Flood Monitoring API, 1 luồng) → `flood_warning_areas.geojson`, `flood_alert_areas.geojson`.

Đọc ODS lớn: `common/ods.py` (streaming, ~34 MB RAM cho file 1 GB). Xuất ArcGIS: phân trang keyset theo OBJECTID,
kiểm tra số feature từng khúc, chờ 65 s khi gặp hạn mức 429.

### Nguồn bổ sung (đợt 4, khảo sát CrystalRoof — COMPETITOR_CRYSTALROOF.md)

| Tool | dataset_id | Ghi chú |
|---|---|---|
| `dfe_school_profile` | uk.dfe.school_profile | Compare School Performance: CENSUS (SEN), PUPILABSENCE, KS4/KS5 destinations, KS5 HE, KS4UNDERLYING (bài thi theo môn); mỗi loại lấy năm mới nhất có file |
| `dfe_spc` | uk.dfe.spc | EES "Schools, pupils and their characteristics": zip release (~240 MB), chỉ đọc 2 file cấp trường |
| `boundaries_ward` | uk.ons.boundaries_ward | Ward BGC mới nhất (05/2026 khớp mã ONSPD 100%), chỉ E&W |
| `geods_oac` | uk.geods.oac2021 | OAC 2021/22: `UK_OAC_Final.parquet` (GitHub GeoDS) + tên/mô tả từ API apps.geods.ac.uk (cần DB để chọn postcode đại diện). Cần `pyarrow` |
| `os_open_roads` | uk.os.open_roads | OS Open Roads GeoPackage |
| `laei` | uk.gla.laei | LAEI 2022 nồng độ ASCII 20 m (NO2, NOx, PM10, PM2.5, ngày PM10 > 50) |
| `census2021_more` | uk.ons.census2021 | 18 bảng Census bổ sung (xem `Census2021More.DEFAULT`) |
| `london_planning` | uk.gla.planning_datahub | London Planning Datahub (Elasticsearch khách), 3 năm |
| `police_history` | uk.police.history | 5 archive police 2013-11…2023-08 (~8 GB) → LSOA 2021 × năm × loại + độ phủ LAD × tháng. Chạy trên VPS (`ZC_WORKERS=1`): mạng local quá chậm |

## Loader (nạp DB) — `uk/loaders/`

| Nguồn | Bảng đích |
|---|---|
| `boundaries_*` | `core.geo_area` (oa, lsoa, msoa, lad, region) + nation gộp từ LAD, liên kết oa→lsoa, lad→nation |
| `onspd` | `mkt_uk.postcode`, `core.geo_area` (postcode_unit, sector, district, postal_area), liên kết các cấp |
| `os_open_names` | `core.geo_area` level `town` (City/Town/Village/Suburban Area) + liên kết town→lad |
| `os_open_greenspace` | `core.zone` (`greenspace.*`) |
| `gias` / `ofsted` | `core.poi` (`school.*`, `college`) / `core.poi_rating` (report card + OEIF) |
| `naptan`, `nhs_ods`, `fsa` | `core.poi` (giao thông, y tế, ăn uống) + `core.poi_rating` (FHRS/FHIS) |
| `iod2025`, `census2021`, `uk_hpi`, `pipr`, `ons_income_msoa`, `defra_pcm` | `core.metric` + `core.metric_value` (+ refresh `core.metric_latest`) |
| `police` | `mkt_uk.crime_incident` (partition theo năm) + `mkt_uk.crime_coverage_gap` |
| `ppd` | `mkt_uk.price_paid` |
| `epc` | `mkt_uk.epc_certificate` |
| `os_open_uprn` | `mkt_uk.uprn_point`: toạ độ các UPRN của nhà có EPC (khoảng 20 triệu) |
| `ea_rofsw` | `uk.zone.sw_{high,medium_plus,any}_share`: % nhà (có EPC) có rủi ro lũ nước mặt theo LSOA, lấy mẫu đúng tại toạ độ UPRN |
| `ea_flood_areas` | `core.zone` (`flood.warning_area`, `flood.alert_area`) |
| `ofcom_connected_nations` | `uk.bb.*` (% nhà có gigabit/ultrafast/superfast/thiếu broadband, OA + LSOA cộng theo số nhà), `uk.mobile.*` (theo LA) |
| `nhs_gp_patients` | `core.poi.attrs.registered_patients` của GP |
| `gp_patient_survey` | `core.poi_metric_value` `uk.gp.*` (% đánh giá tích cực, số phản hồi) cho POI `health.gp` |
| `dwp_uc` | `uk.benefit.uc_rate`, `uc_not_working_rate` (/100 dân 16–64), `uc_working_share` theo LSOA |
| `hmlr_ccod`, `hmlr_ocod` | `mkt_uk.company_title` + `uk.own.{company,overseas}_titles_per_1k_hh` theo LSOA |
| `hmlr_leases` | `mkt_uk.registered_lease` (thời hạn thuê tách từ cột Term) |
| `nrw_rofsw` | `uk.zone.sw_*_share` cho LSOA Wales |
| `planning_data_extra` | 16 lớp `core.zone` (thêm `heritage.at_risk`, `heritage.listed_outline`, `heritage.locally_listed`, `planning.open_space`, `planning.local_plan_area`) + brownfield → `core.poi` `planning.brownfield_site` + `mkt_uk.local_plan` |
| `parliament_mps` | `mkt_uk.mp` + `gss_code` (ghép tên đã chuẩn hoá với `admin.westminster_const`, 632/632) |
| `dfe_performance` | thêm `uk.ks4.ebacc_entry_pct`, `uk.ks5.best3_*`, `uk.ks5.aab_pct`; dòng TB LA/England → `mkt_uk.school_benchmark` |
| `dfe_school_profile`, `dfe_spc` | `uk.pupils.*`, `uk.dest.*`, `uk.ks4.subject_entries`, `uk.school.class_size_*` (poi) + `mkt_uk.school_benchmark` |
| `boundaries_ward` | `core.geo_area` level `ward` (slug "tên-ward-tên-lad") + liên kết ward → lad |
| `geods_oac` | `mkt_uk.oac`, `mkt_uk.oac_label` |
| `os_open_roads` | `mkt_uk.road` (Motorway/A/B) |
| `laei` | `mkt_uk.postcode_air` |
| `london_ptal` | thêm `mkt_uk.ptal_grid` (lưới 100 m) |
| `orr_station_usage` | thêm attrs `operator` (station facility owner), `main_destination` |
| `osm_uk` | thêm `emergency.ambulance_station`, `health.hospital` (attrs `emergency`) |
| `london_planning` | `mkt_uk.planning_application` |
| `police_history` | `mkt_uk.crime_lsoa_year` + `mkt_uk.crime_lsoa_year_cover` |

Ngưng dùng (`RETIRED` trong `uk/__main__.py`: `cleanup` đặt release `superseded` rồi xoá file thô, `uk all` bỏ qua):
`os_codepoint_open` (trùng ONSPD), `journey_time` (JTS 2019 theo LSOA 2011, đã thay bằng DfT connectivity 2025).

Ghi chú dữ liệu:
- Census: 6 LAD đổi mã sau 2021 (Cumberland, Westmorland and Furness, North Yorkshire, Somerset, Barnsley, Sheffield)
  được cộng dồn từ MSOA (`is_imputed = true`); mật độ (ts006) tính lại bằng Σ dân số / Σ diện tích.
- Police: Greater Manchester Police không có dữ liệu trên data.police.uk, Gloucestershire thiếu từ 02/2026.
  Các tháng thiếu nằm trong `crime_coverage_gap`.
- Ofsted: "Not applicable" và mã OEIF 9/0 không phải điểm nên bỏ qua.

## Derive (tổng hợp, điểm) — `python -m uk derive <bước|all>`

| Bước | Kết quả |
|---|---|
| `membership` | Dân số postcode (OA ÷ số postcode) → `geo_area_link` overlaps (LSOA ↔ sector/district/town/MSOA/LAD/region/nation), `geo_area.population` |
| `crime` | `uk.crime.*` 12 tháng (số vụ, tỉ lệ / 1.000 dân theo nhóm, xu hướng). Lực lượng theo PFA; tỉ lệ tính trên phần dân số có dữ liệu, ẩn khi < 50% |
| `housing` | `uk.price.*` trung vị 24 tháng (chung + theo loại), số giao dịch, thay đổi 5 năm, chuỗi 10 năm; ẩn khi < 5 giao dịch |
| `epc_match` | Ghép Price Paid ↔ EPC theo địa chỉ trong cùng postcode → `mkt_uk.ppd_epc_match`; `uk.price.per_sqm` (£/m²) và `uk.price.floor_area` trung vị 24 tháng |
| `access` | `uk.access.*`, `uk.schools.*`: khoảng cách tới GP/trường/ga/siêu thị/công viên, tiện ích quanh nhà, chất lượng trường gần nhất (theo postcode, trung bình theo dân số) |
| `exposure` | `uk.zone.*_share` + `core.area_zone_exposure`: % dân trong Flood Zone, conservation, green belt, AONB... |
| `rollup` | Đưa chỉ số LSOA/MSOA lên mọi cấp trang (trung bình theo dân số / tổng theo phần), kể cả ward |
| `census_shares` | 54 chỉ số % `uk.share.*` từ phân phối Census (NS-SeC 5 lớp, học vấn, tenure, tuổi 20 năm, loại hộ, dân tộc, tôn giáo) ở mọi cấp ≥ LSOA; kiểm tra tổng nhóm ≈ 100% và số ONS công bố |
| `scoring` | Phân vị theo cấp + phạm vi so sánh; `area_category_score` (8 nhóm), `area_overall_score` (6 vai trò), mô hình `uk.v1` |
| `streets` | `mkt_uk.postcode_street`: tên đường + post town cho mỗi postcode (cặp nhiều giao dịch nhất trong Price Paid) cho gợi ý tìm kiếm |

Mỗi bước có kiểm tra chéo với số liệu công bố (dân số Census, tỉ lệ tội phạm, giá trung vị, khoảng cách trung bình,
kiểm tra định hướng như Westminster kém an toàn hơn Rutland). Fail → rollback.

## Review cư dân

Web ghi review vào `mkt_uk.review` bằng role `zonecheck_review` (chỉ INSERT). Duyệt: `python -m uk.manual.reviews`
(liệt kê), `… approve <id>`, `… reject <id>`.

## Tải tay

Ofcom (broadband) và NHS Digital (số bệnh nhân GP) chặn mọi client tự động (Cloudflare) → `uk/manual/fetch.py` tải bằng Chrome thật
qua Playwright ở máy local, xem `uk/manual/README.md`.

## Chưa làm (lý do)

| Nguồn (PLAN §2.2) | Vướng |
|---|---|
| NRW flood (#24), noise (#26), HadUK-Grid (#27), radon, Coal Authority, Natural England, planning.data.gov.uk, BODS, VOA, council tax, OSM | Giai đoạn 2 theo PLAN |

## Dung lượng tham khảo (lần tải đầu, 11/10/2026)

ONSPD 254 MB · Open UPRN 619 MB · Open Names 103 MB · NaPTAN 102 MB · GIAS 67 MB · UK HPI 35 MB · JTS 317 MB · Price Paid complete khoảng 5 GB · police archive khoảng 2 GB.
