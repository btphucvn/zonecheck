# Theo dõi lấp khoảng trống dữ liệu so với đối thủ (UK)

> Bắt đầu: 2026-10-12. Nguồn khảo sát: CrystalRoof, PostcodeCheck, Home-Checker, PropertyData, HouseCheckup,
> Know My Postcode, HomeThink, Area360, Plumplot (xem phần "Khảo sát" cuối file).
> Quy trình mỗi nguồn: **tool tải** (`get-data/uk/sources`) → **tải về VPS** (`python -m uk <tool>`) → **loader nạp DB** → **derive chỉ số**.

**Tóm tắt (2026-10-13 19:10):** đợt 2 xong GPPS, UC, lũ nước mặt Wales, planning bổ sung, MP theo mã GSS; CCOD/OCOD đã nạp (19:25); còn Registered Leases chờ chọn licence → 37/40.

**Tóm tắt trước (2026-10-13 12:40):** 34/35 mục có thể làm đã tải và nạp DB xong (97%). Tính cả 5 mục cần tài khoản hoặc không làm: 34/40. Còn lại: GP Patient Survey (chưa có link CSV tự động); 3 mục cần bạn đăng ký tài khoản (CCOD/OCOD, Registered Leases, DWP Stat-Xplore). Toàn bộ chỉ số mới đã được rollup lên sector/district/town/LAD (55 metric, ~3,7 triệu giá trị).

Trạng thái: ⏳ chưa làm · 🔧 đang làm · ✅ xong · ⚠️ lỗi/vướng · 🔑 cần đăng ký tài khoản/API key · ➖ không làm

## Bảng tiến độ

| # | Dữ liệu | Đối thủ có | Nguồn | Tool | Tải | Nạp DB | Ghi chú |
|---|---|---|---|---|---|---|---|
| 1 | Tiếng ồn đường bộ / đường sắt / sân bay (Lden, Lnight) | CrystalRoof, PostcodeCheck, HouseCheckup, Area360, KnowMyPostcode | Defra Strategic Noise Round 4 (WCS raster) | `defra_noise` | ✅ | ✅ | 1,49 triệu postcode England → `mkt_uk.postcode_noise` + `uk.noise.*_share`: 31,3% dân ≥55 dB đường bộ, 5,3% ≥65 dB, 2,2% đường sắt, 2,0% máy bay ≥50 dB (Hounslow 75,7%) |
| 2 | Radon | PostcodeCheck (trả phí), HouseCheckup, HomeThink | BGS/UKHSA Indicative Atlas (OS Data Hub, OGL) | `bgs_radon` | ✅ | ✅ | 242.326 ô 1 km, lớp 1–6 ở `level_rank` |
| 3 | Mỏ than (vùng rủi ro cao/thấp) | PostcodeCheck (trả phí), HouseCheckup | Mining Remediation Authority (Coal Authority) | `coal_authority` | ✅ | ✅ | 40.186 vùng rủi ro cao + 28.401 vùng thấp |
| 4 | Mỏ khác (không phải than) | HouseCheckup | BGS Mining hazard 1 km hex | `bgs_mining_hazard` | ✅ | ✅ | 57.190 hex (bỏ ô 'NA') |
| 5 | Sụt lún / đất sét co ngót / sạt lở (GeoSure) | Home-Checker, HouseCheckup, PostcodeCheck (trả phí) | BGS GeoSure 5 km hex (OGL) | `bgs_geosure_hex` | ✅ | ✅ | 6 loại nguy cơ × ~4.230 hex |
| 6 | Bãi rác cũ + bãi rác đang cấp phép | Home-Checker, HouseCheckup | EA Historic Landfill + Authorised Landfill | `ea_landfill` | ✅ | ✅ | 19.853 bãi cũ + 1.652 bãi cấp phép → `core.zone` |
| 7 | Sự cố ô nhiễm môi trường | HouseCheckup | EA Environmental Pollution Incidents | `ea_pollution_incidents` | ✅ | ✅ | 17.408 sự cố mức 1–2 (2000–2026), đọc file Access bằng `access-parser` → `core.poi` environment.pollution_incident |
| 8 | Xói lở bờ biển | HouseCheckup | EA NCERM 2024 | `ea_coastal_erosion` | ✅ | ✅ | vùng xói lở 2055/2105 + 80 vùng mất ổn định |
| 9 | Lũ đã từng xảy ra | HouseCheckup | EA Recorded Flood Outlines + Historic Flood Map | `ea_flood_history` | ✅ | ✅ | 21.578 vùng lũ gộp + 31.744 đợt lũ |
| 10 | Đê / công trình chống lũ | HouseCheckup | EA AIMS Spatial Flood Defences | `ea_flood_defences` | ✅ | ✅ | 141.387 công trình, 57.936 km → `mkt_uk.flood_defence` (tình trạng, mức bảo vệ) |
| 11 | Lũ do vỡ hồ chứa | HouseCheckup | EA Reservoir Flood Extents (WMS, mặt nạ 10 m) | `ea_reservoir_flood` | ✅ | ✅ | Lấy theo ô WMS (file 3,4 GB không tải được): 1.142 ô có vùng ngập (khô 4.451 km², mưa 9.466 km²); 7,07% dân England trong vùng ngày mưa → `uk.zone.reservoir_{wet,dry}_share` |
| 12 | Rủi ro lũ sông/biển theo mức (NaFRA2) | Home-Checker, HouseCheckup | EA RoFRS – postcodes in areas at risk | `ea_rofrs_postcodes` | ✅ | ✅ | 163.810 postcode + 106 nghìn dòng gộp ẩn danh (chia đều theo tiền tố); 1,9 triệu nhà ở có rủi ro → `mkt_uk.postcode_rofrs` + `uk.zone.rs_*_share` |
| 13 | Xả tràn nước thải (storm overflow) | HouseCheckup | EA Event Duration Monitoring | `ea_storm_overflows` | ✅ | ✅ | 14.245 điểm xả, 290.754 lần xả / 133.872 giờ năm 2025 → `core.poi` environment.storm_overflow |
| 14 | Lũ ở Wales + bãi rác Wales | — | NRW DataMapWales (WFS) | `nrw_flood` | ✅ | ✅ | Flood Zone 3 (1.901 km²)/2, rủi ro sông/biển theo mức, 1.223 vùng lũ cũ, 1.502 bãi rác cũ, 354 khu cảnh báo → `core.zone`. Lớp nước mặt Wales: tool `nrw_rofsw` tải theo ô 10 km trên máy local (451 MB thay vì 5,6 GB), loader lấy mẫu 1,04 triệu nhà (vùng ngập trong 5 m quanh toạ độ UPRN, vì polygon NRW chừa khuôn nhà) → 9,7% nhà Wales có rủi ro (High 2,7%), LAD 3,3–18,4% → `uk.zone.sw_*_share` (E&W) đã rollup |
| 15 | Khí hậu (nhiệt độ, mưa, nắng, sương giá) | Home-Checker | Met Office Climate Data Portal (HadUK-Grid 1991–2020) | `haduk_grid` | ✅ | ✅ | CEDA đòi đăng nhập → dùng lớp ArcGIS mở của Met Office (1991–2020): 8 lớp → `core.zone` climate.*; chỉ số `uk.climate.*` sinh ở derive hazards; trung bình England theo dân: 10,5 °C, 774 mm mưa, 37 ngày sương giá, 14 ngày >25 °C |
| 16 | Di sản & quy hoạch bổ sung: scheduled monument, park & garden, battlefield, WHS, brownfield, đất ô nhiễm, COMAH, heritage at risk, ancient woodland, AQMA, SAC/SPA/Ramsar, đơn xin cấp phép, local plan | PostcodeCheck, HouseCheckup, PropertyData | planning.data.gov.uk | `planning_data_extra` | ✅ | ✅ | 16 lớp → `core.zone` (thêm heritage at risk 5.490, listed building outline 130.036, locally listed 448, open space 560, vùng local plan 364); brownfield 28.139 điểm (tối đa ~1,26 triệu nhà) → `core.poi` `planning.brownfield_site`; 959 local plan → `mkt_uk.local_plan` (96% có mã LPA). File thô đã xoá. Chưa có file tổng: contaminated-land, COMAH, planning-application… |
| 17 | Sóng di động 4G/5G | PostcodeCheck, KnowMyPostcode, HouseCheckup | Ofcom Connected Nations (đã tải tay) | `ofcom_connected_nations` | ✅ | ✅ | Đã có sẵn: 4 chỉ số di động theo LA (`uk.mobile.*`). Ofcom không phát hành sóng di động theo postcode trong gói tải |
| 18 | Nhà trẻ, người giữ trẻ | HouseCheckup | Ofsted childcare provider level data | `ofsted_childcare` | ✅ | ✅ | 27.918 nhà trẻ có địa chỉ công khai (người giữ trẻ tại nhà bị Ofsted ẩn), 98,8% Good/Outstanding → `core.poi` childcare.nursery |
| 19 | Xếp hạng CQC (GP, bệnh viện, nhà dưỡng lão) | PostcodeCheck, HouseCheckup | CQC directory + latest ratings | `cqc` | ✅ | ✅ | 57.097 cơ sở; xếp hạng CQC gắn cho 5.912 GP + nha khoa/NHS theo mã ODS; 14.794 nhà dưỡng lão (`health.care_home`) |
| 20 | Tai nạn giao thông | HouseCheckup | DfT STATS19 (5 năm) | `dft_stats19` | ✅ | ✅ | 513.801 vụ (1,47% tử vong) → `mkt_uk.road_collision` + `uk.road.*_per_1k` (LSOA) |
| 21 | Lưu lượng xe | HouseCheckup | DfT road traffic AADF | `dft_traffic` | ✅ | ✅ | 46.754 điểm đếm (năm mới nhất ≤ 2025, M25 tới 212.636 xe/ngày) → `core.poi` transport.traffic_count |
| 22 | PTAL London | CrystalRoof, Area360 | London Datastore | `london_ptal` | ✅ | ✅ | 4.659/4.835 LSOA khớp mã 2021 → `uk.london.ptai` |
| 23 | Ga TfL + travel zone | CrystalRoof | TfL Unified API | `tfl_stations` | ✅ | ✅ | 356/610 ga khớp POI NaPTAN, gắn `attrs.tfl_zone`/`tfl_lines` |
| 24 | Tiện ích OSM: pub, café, gym, bể bơi, thư viện, trạm sạc EV, đường điện cao thế… | CrystalRoof, KnowMyPostcode, HouseCheckup | OpenStreetMap (Geofabrik) | `osm_uk` | ✅ | ✅ | 41.481 POI: 9.418 bưu điện, 8.019 trung tâm thể thao, 7.446 trạm sạc EV, 4.866 gym, 3.877 thư viện, 2.110 cứu hoả, 1.851 cảnh sát, 1.598 nhà hát, 1.096 hộp đêm, 827 rạp, 373 bể bơi có tên; 12.805 đoạn đường điện ≥132 kV → `mkt_uk.power_line`. ODbL |
| 25 | Ward, khu bầu cử (tên) | KnowMyPostcode | OS Boundary-Line | `os_boundary_line` | ✅ | ✅ | 632 khu bầu cử Westminster (GB), 6.633 ward, 14.259 parish, 1.398 khu bầu cử hạt → `core.zone` admin.* (external_id = mã GSS) |
| 26 | MP theo khu bầu cử | KnowMyPostcode | UK Parliament Members API | `parliament_mps` | ✅ | ✅ | 650 MP → `mkt_uk.mp`; ghép với `admin.westminster_const` theo tên đã chuẩn hoá: 632/632 khu GB (18 khu Bắc Ireland không có ranh giới) |
| 27 | Quyết định tribunal nhà đất | PostcodeCheck, HouseCheckup | gov.uk Residential Property Tribunal decisions | `tribunal_decisions` | ✅ | ✅ | 18.293 quyết định, 17.663 có postcode → `mkt_uk.tribunal_decision` |
| 28 | Mức Local Housing Allowance | PropertyData | gov.uk (VOA) | `lha_rates` | ✅ | ✅ | 152 BRMA × 5 loại → `mkt_uk.lha_rate` |
| 29 | Tỷ lệ giá nhà / thu nhập | — | ONS affordability ratio | `ons_affordability` | ✅ | ✅ | 18.107 giá trị LA × 1997–2025 → `uk.afford.median_ratio`, `uk.afford.lq_ratio` |
| 30 | Dân số ước tính hằng năm theo LSOA | HouseCheckup | ONS mid-year estimates | `ons_lsoa_population` | ✅ | ✅ | Giữa năm 2022–2024 × 35.672 LSOA (E&W 2024: 61,8 triệu) + nhóm tuổi → `uk.pop.mid_year` |
| 31 | Vứt rác trái phép (fly-tipping) | HouseCheckup | Defra fly-tipping statistics | `fly_tipping` | ✅ | ✅ | 13 năm × LA → `uk.flytip.incidents`, `uk.flytip.per_1k` |
| 32 | Census bổ sung: nơi sinh, thời gian cư trú, tiếng Anh, khuyết tật, chăm sóc, nghề nghiệp | CrystalRoof (một phần) | Nomis Census 2021 | `census2021_extra` | ✅ | ✅ | 6 bảng × OA→LAD (nơi sinh = nhạy cảm, không tính điểm) |
| 33 | Đơn đăng ký / chỗ được nhận theo trường | — | DfE applications and offers (EES) | `dfe_school_offers` | ✅ | ✅ | 981 nghìn giá trị cấp trường (URN khớp 100%) → `core.poi_metric_value` uk.school.* |
| 34 | Khu đô thị (built-up areas) | — | OS Open Built Up Areas | `os_built_up_areas` | ✅ | ✅ | 8.716 khu đô thị → `core.zone` admin.built_up_area |
| 35 | Hài lòng của bệnh nhân với GP | HouseCheckup | GP Patient Survey 2026 (gp-patient.co.uk, CSV practice-level) | `gp_patient_survey` | ✅ | ✅ | Link CSV nằm ở `/latest-survey/results` (`/FileDownload/Download?fileRedirect=…practice-data-csv…`). 6.166 phòng khám, 6.154 khớp POI GP (ODS) → `core.poi_metric_value` `uk.gp.*` (7 chỉ số % tích cực + số phản hồi; bỏ ô < 10 phản hồi). TB theo phòng khám 78,1% đánh giá tổng thể tốt |
| 36 | Nhà thuộc sở hữu công ty (CCOD/OCOD) | PostcodeCheck, PropertyData | HM Land Registry 10/2026 | `hmlr_ccod`, `hmlr_ocod` | ✅ | ✅ | Đã ký licence 2026-10-13. CCOD 4.472.706 + OCOD 90.988 title (99,9% postcode khớp) → `mkt_uk.company_title` (KHÔNG lưu địa chỉ: licence điều 3.2 chỉ cho dùng địa chỉ PAF phi thương mại) + `uk.own.{company,overseas}_titles_per_1k_hh` (LSOA): Westminster 339,6/89,9, Cornwall 104,1/1,5 per 1.000 hộ. Licence: HMLR có quyền audit, phải giữ End-User Records, ghi nguồn "Information produced by HM Land Registry. © Crown copyright 2026" |
| 37 | Hợp đồng leasehold (Registered Leases) | PropertyData, HouseCheckup | HM Land Registry | `hmlr_leases` | 🔑 | ⏳ | Tool + loader sẵn sàng (cột khớp file mẫu). **Chờ bạn quyết loại licence**: Direct use miễn phí nhưng cấm đưa lên web/thương mại; Exploration miễn phí 3 tháng và Commercial £5.000+VAT/năm đều phải liên hệ HMLR |
| 38 | Người nhận trợ cấp (UC…) | HouseCheckup | DWP Stat-Xplore (People on UC, LSOA 2021) | `dwp_uc` | ✅ | ✅ | Tháng 04/2026 (tháng mới nhất đã tách việc làm; 05/2026 chưa có): 7,61 triệu người E&W = 19,6/100 dân 16–64 → `uk.benefit.uc_rate`, `uc_not_working_rate`, `uc_working_share` (LSOA). Blackpool 34,2 vs Wokingham 8,7 |
| 39 | Khu bắt buộc cấp phép cho thuê / HMO | PostcodeCheck, PropertyData | Từng LA | — | ➖ | ➖ | Không có dataset quốc gia |
| 40 | Giá chào bán / tin đăng | PropertyData | Portal | — | ➖ | ➖ | Scrape vi phạm điều khoản |

### Đợt khảo sát CrystalRoof 2026-10-14 (chi tiết: COMPETITOR_CRYSTALROOF.md)

| # | Dữ liệu | Đối thủ có | Nguồn | Tool | Tải | Nạp DB | Ghi chú |
|---|---|---|---|---|---|---|---|
| 41–44 | Học sinh: giới, EAL, FSM, dân tộc HS, sĩ số theo khối, SEN, vắng học, sĩ số lớp | CrystalRoof | DfE SPC (EES, file cấp trường) + Compare School Performance (census, absence) | `dfe_spc`, `dfe_school_profile` | ✅ | ✅ | 24.428 trường, `uk.pupils.*`, `uk.school.class_size_*`; TB LA/England → `mkt_uk.school_benchmark` |
| 45–46 | % entering EBacc, Best 3, AAB, TB LA/England mọi chỉ số thi; thêm trường đặc biệt/độc lập/consortium 16+ | CrystalRoof | Performance tables (RECTYPE 1/2/3; LA = 3/4, England trường công = 5/7) | `dfe_performance` | ✅ | ✅ | 402.694 giá trị, 8.839 dòng TB; khoảng progress nới [-30, 30] cho trường đặc biệt |
| 47 | Số bài thi KS4 theo môn + phân bố điểm | CrystalRoof | KS4 underlying entries & grades (xlsx) | `dfe_school_profile` | ✅ | ✅ | 4.862 trường → `uk.ks4.subject_entries` |
| 48 | Destinations KS4 / 16-18 / HE (top third) | CrystalRoof | Compare School Performance destinations | `dfe_school_profile` | ✅ | ✅ | `uk.dest.ks4`, `uk.dest.ks5`, `uk.dest.ks5_he` + TB LA/England |
| 49 | Tuyển sinh: đơn và offer nguyện vọng 1/2/3, từ LA khác | CrystalRoof | DfE applications & offers (cùng file) | `dfe_school_offers` | ✅ | ✅ | 3,19 triệu giá trị, kiểm tra offer ≤ đơn |
| 50 | 6 sub-domain IoD2025 | CrystalRoof | IoD2025 File 7 | `iod2025` | ✅ | ✅ | `uk.iod25.sub_*` + rollup |
| 51 | Output Area Classification 2021/22 + tên, mô tả | CrystalRoof | GeoDS/ONS (GitHub repo chính thức + API tra cứu GeoDS), OGL | `geods_oac` | ✅ | ✅ | 188.880 OA E&W khớp 100%, 21 group + 8 supergroup có mô tả → `mkt_uk.oac`, `mkt_uk.oac_label` |
| 52 | London OAC | CrystalRoof | CDRC | — | ➖ | ➖ | Dùng OAC UK 2021/22 thay (mới hơn, cùng nhà phát triển) |
| 53 | Lịch sử tội phạm 12/2010 → nay theo LSOA × năm × loại | CrystalRoof | data.police.uk archive 2013-11, 2016-11, 2019-11, 2022-11, 2023-08 + crime_incident | `police_history` + derive `crime_history` | ✅ | ✅ | 6,04 triệu dòng LSOA × năm × loại; độ phủ theo lực lượng (Police Force Area), GMP thiếu từ 07/2019 bị loại đúng; `mkt_uk.crime_area_year` 3,56 triệu dòng (2011–2025, mọi cấp) |
| 54 | Burglary / 1.000 nhà | CrystalRoof | VOA dwelling stock (`uk.ctax.stock`) | derive `crime` | ✅ | ✅ | `uk.crime.burglary_dw_rate`, England 8,1 |
| 55–60 | Census bổ sung (18 bảng: hôn nhân, hộ chiếu, giới, sống chung, năm đến UK, di cư, ngôn ngữ hộ, bản sắc, đa tôn giáo hộ, khuyết tật hộ, số phòng, mật độ ở, giờ làm, ngành, lịch sử việc làm, HS/SV) | CrystalRoof API | Nomis bulk | `census2021_more` | ✅ | ✅ | 18 bảng, rollup 1,77 triệu giá trị. Nhóm di cư/ngôn ngữ/bản sắc = sensitive, không tính điểm. File rỗng của Nomis (ts010 LSOA) được bỏ qua |
| 61 | Xu hướng tính dục, bản dạng giới | CrystalRoof API | Nomis | — | ➖ | ➖ | Không đưa lên trang |
| — | Tỷ lệ % từ Census (NS-SeC 5 lớp, 7 bậc học vấn, tenure, tuổi 20 năm, 7 loại hộ, 16 dân tộc, 9 tôn giáo) | CrystalRoof | derive từ bảng Census đã có | derive `census_shares` | ✅ | ✅ | 54 chỉ số `uk.share.*` (4,71 triệu giá trị) ở mọi cấp ≥ LSOA, có phân vị; England khớp ONS (bằng cấp 33,9%, White British 73,5%, sở hữu 62,3%, xã hội 17,1%) |
| — | Cấp ward (7.596 ward E&W, ranh giới 05/2026 khớp ONSPD 100%) | CrystalRoof | ONS Wards BGC | `boundaries_ward` + derive | ✅ | ✅ | membership, housing, crime, rollup, phân vị, điểm đã chạy lại cho ward |
| 62 | Đường lớn gần nhất (Motorway/A/B) | CrystalRoof API | OS Open Roads | `os_open_roads` | ✅ | ✅ | 463.035 đoạn Motorway/A/B, motorway 3.761 km (không tính slip road) → `mkt_uk.road` |
| 63 | Chuông nhà thờ | CrystalRoof | Dove's Guide | — | ➖ | ➖ | Chưa rõ giấy phép dùng thương mại; chưa làm |
| 64 | Trạm cứu thương, bệnh viện / A&E | CrystalRoof | OSM (`emergency=ambulance_station`, `amenity=hospital` + `emergency=yes`) | `osm_uk` | ✅ | ✅ | 43.974 POI OSM; nguồn ồn trong 483 m |
| 65 | % diện tích ward bị ồn | CrystalRoof | — | — | ➖ | ➖ | Ta dùng % dân (chính xác hơn với người ở), đã có |
| 66 | PTAL lưới 100 m tại địa chỉ | CrystalRoof | London Datastore (PTAL 2015) | `london_ptal` | ✅ | ✅ | 159.451 ô `mkt_uk.ptal_grid`; ô gần Bank = 6b |
| 67 | Hãng quản lý ga, điểm đi/đến chính | CrystalRoof | ORR Table 1410 | `orr_station_usage` | ✅ | ✅ | 2.575/2.589 ga, 30 hãng quản lý; attrs `operator`, `main_destination` |
| 68 | London: NO2/NOx/PM10/PM2.5 lưới 20 m + số ngày PM10 vượt ngưỡng | CrystalRoof | LAEI 2022 (GLA) | `laei` | ✅ | ✅ | 205.002 postcode → `mkt_uk.postcode_air`; NO2 TB trung tâm 27,9 vs rìa 17,8 µg/m³ |
| 69 | Tốc độ broadband theo postcode | CrystalRoof API | Ofcom | — | ➖ | ➖ | Giữ quyết định cũ: file performance theo OA không có tốc độ chung |
| 70 | Đơn xin cấp phép quy hoạch gần đây | CrystalRoof API | London Planning Datahub (GLA) | `london_planning` | ✅ | ✅ | 299.174 hồ sơ (268.982 có toạ độ), 3 năm; ngoài London chưa có nguồn mở đủ toạ độ |
| 71 | Review cư dân | CrystalRoof | Tự thu thập | web `/uk/review/new` | — | ✅ | `mkt_uk.review` (role `zonecheck_review` chỉ INSERT), duyệt: `python -m uk.manual.reviews` |
| 72 | Định giá tức thì | CrystalRoof | PPD + EPC + UK HPI | web `/uk/valuation` | — | ✅ | Diện tích EPC × £/m² sector 24 tháng (quy về hôm nay bằng HPI), khoảng = tứ phân vị |
| 73 | Council tax band theo từng địa chỉ | CrystalRoof API | VOA | — | ➖ | ➖ | Không có file tổng hợp lệ |
| 74 | Thu nhập dưới cấp MSOA | CrystalRoof | — | — | ➖ | ➖ | Dùng MSOA (LSOA nhận giá trị MSOA cha), ghi rõ trên trang |

## Nhật ký

- 2026-10-14 (tối): toàn bộ hàng đợi xong. Sửa trong lúc chạy: regex OpenRoads, Last-Modified ISO (London Datastore), file Census rỗng, độ phủ tội phạm đo theo lực lượng thay vì theo LAD (BTP vẫn báo vụ ở Manchester), xu hướng tội phạm tính sẵn (`crime_history`) vì truy vấn trực tiếp cho London mất 31 giây.
- 2026-10-14: triển khai kế hoạch khảo sát CrystalRoof (COMPETITOR_CRYSTALROOF.md). Nạp xong: IoD sub-domain, tuyển sinh đủ nguyện vọng, kết quả thi + TB LA/England, hồ sơ trường (SPC, SEN, vắng học, destinations, môn thi), ranh giới ward. Đang chạy trên VPS: derive ward/crime/rollup/census_shares/phân vị, OAC, OpenRoads, LAEI, OSM (cứu thương, bệnh viện), PTAL lưới, ORR hãng ga, Census bổ sung, London planning, lịch sử tội phạm.

- 2026-10-13 17:25 (giờ VPS): đợt 2 xong.
  - **GPPS:** link CSV practice-level ở `gp-patient.co.uk/latest-survey/results`. 6.154 phòng khám khớp POI GP → `uk.gp.*`.
  - **UC:** 04/2026 → `uk.benefit.*`.
  - **Wales nước mặt:** đã nạp, xem mục 14.
  - **Planning bổ sung:** 5 lớp vùng + brownfield + local plan.
  - **MP:** `mkt_uk.mp.gss_code` (632/632), web join theo mã.
  - **Rollup:** đã chạy cho `uk.benefit.%` và `uk.zone.%`.
  - **HMLR:** key hoạt động nhưng CCOD/OCOD chưa ký licence, Leases chưa được cấp quyền.
  - **Sự cố:** tunnel DB (~230 ms) đứt 2 lần khi COPY kéo dài → chuyển loader Wales lên VPS. Có lúc 2 job chạy trùng → đã dừng 1 bản theo PID.
  - **Bài học:** phần nặng CPU tính ở máy local, chỉ đẩy kết quả lên VPS.

- 2026-10-13 12:40: hoàn tất các hàng đợi trên VPS. Nạp thêm: tiếng ồn, OSM, lưu lượng xe, công trình chống lũ, khu đô thị; chạy lại derive `hazards` (784.780 giá trị) và rollup `uk.zone/noise/climate/road/london/pop/census`. File thô đã xoá sau khi nạp (`--cleanup`). Chưa xoá: `planning_data_extra` (còn brownfield, heritage-at-risk, local-plan, đơn xin quy hoạch chưa có loader).

- 2026-10-13 10:10: **Cách ghép MP ↔ khu bầu cử (cho web):** chuẩn hoá cả hai phía rồi so sánh: bỏ hậu tố `\s+(Boro|Co|Burgh)\s+Const$` (chỉ có ở tên OS), `&` → `and`, bỏ dấu phẩy và dấu chấm (OS ghi "St.", Parliament ghi "St"), `unaccent()` (OS ghi "Ynys Mon", Parliament ghi "Ynys Môn"), gộp khoảng trắng, `lower`. Nếu chỉ dùng 3 bước đầu thì khớp 622/650; 10 khu GB còn lại lệch vì "St." và dấu tiếng Wales; 18 khu Bắc Ireland không có trong Boundary-Line.

- 2026-10-13 06:09: số liệu kiểm tra derive `hazards` (theo dân, England): mỏ than (vùng báo cáo) 24,7%, rủi ro cao 4,7%; radon ≥1% nhà vượt ngưỡng 42,9% (atlas lấy mức cao nhất trong ô 1 km nên thiên cao), ≥5% 14,6%; đất sét co ngót mức "đáng kể" 30,6%; sạt lở ≥ trung bình 29,2%; trong 250 m bãi rác cũ 11,9%; vùng đã từng ngập 2,1%; AQMA 25,2%. Wales: Flood Zone 3 10,7%, Zone 2+3 13,5%.

- 2026-10-12 19:17: tải xong 29 nguồn mới (~6 GB). OSM UK 2,3 GB; Boundary-Line 0,8 GB; planning bổ sung 18 lớp (8 lớp chưa có file tổng trên planning.data: contaminated-land, COMAH, safety-hazard-area, public-safety-zone, local-green-space, planning-application, development-plan-boundary, hs2).
- Sự cố: HadUK-Grid trên CEDA trả trang đăng nhập (đã xoá, thêm kiểm tra chặn file HTML trong `common/http.py`); hồ chứa EA 3,4 GB/bản bị server cắt; NRW WFS lỗi đếm feature (đã sửa).
- Đã viết loader: `loaders/hazards.py` (bãi rác, lũ đã xảy ra, xói lở, mỏ than, radon, GeoSure, mỏ không than, di sản/thiên nhiên bổ sung, khí hậu → `core.zone`), `loaders/noise.py` (tiếng ồn tại postcode → `mkt_uk.postcode_noise` + `uk.noise.*_share`), `loaders/roads.py` (STATS19 → `mkt_uk.road_collision` + `uk.road.*_per_1k`), Census bổ sung; derive `hazards` (% dân trong vùng radon/mỏ/GeoSure/bãi rác ≤250 m/lũ cũ/xói lở/AQMA + khí hậu theo LSOA).
- Khí hậu: chuyển sang Met Office Climate Data Portal (ArcGIS, lưới 1991–2020: nhiệt độ TB/max/min, mưa, ngày sương giá, ngày hè, ngày mưa ≥10 mm, ngày đóng băng). Chưa có giờ nắng.
- Tiếng ồn: lớp sân bay chỉ phủ quanh sân bay → lọc ô theo phạm vi coverage (trước đó server trả HTTP 500 làm job đứng).
- VPS (3 GB RAM) quá tải khi chạy song song tải + nạp + phiên khác → SSH treo; chạy tuần tự từng nguồn.
- Sự cố pollution incidents: file là Microsoft Access (.accdb) → đọc bằng thư viện Python thuần `access-parser` (đã cài vào venv trên VPS; cần thêm vào requirements.txt).

- 2026-10-12: tạo file, dò endpoint cho toàn bộ nguồn.
