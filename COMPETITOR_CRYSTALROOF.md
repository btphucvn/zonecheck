# Khảo sát CrystalRoof và kế hoạch lấp khoảng trống

> Ngày khảo sát: 2026-10-14. Mẫu: postcode **SE15 4DX** (Adys Road, Southwark), tài khoản **gói FREE** đã đăng nhập.
> Cách khảo sát: Playwright điều khiển Chrome. Đã bấm mọi nút "View …", mọi tab con, mọi dropdown, "Legend", "What does it mean", "Show more", "Show key judgements", "Filters".
> Phạm vi: 10 tab postcode, 2 trang trường, trang ga, ward, borough (overview và crime), trang định giá, review, pricing, 92 method API.
> Dữ liệu thô: [research/crystalroof-2026-10-14/raw/](research/crystalroof-2026-10-14/raw/) gồm 55 file text. Ảnh chụp nằm ở `screens/`, không commit.
> Đối chiếu với: DB trên VPS (278 metric `uk.*`, POI, zone, `mkt_uk.*`), [web/src](web/src), [DATA_GAP_TRACKER.md](DATA_GAP_TRACKER.md).

---

## 0. Tóm tắt

- **Dữ liệu nền ta đã ngang hoặc hơn CrystalRoof (CR) ở phần lớn chủ đề.** Ta hơn ở rủi ro môi trường: radon, mỏ than, GeoSure, bãi rác, hồ chứa, lũ cũ. Ta cũng có thêm giá nhà, giá thuê, EPC, quy hoạch, council tax, máy tính, so sánh, tìm ngược. Riêng so sánh khu thì CR vẫn đang ghi "Coming soon".
- **CR hơn ta ở 4 điểm:**
  1. **Độ sâu trang trường học.** Mỗi trường có 7 tab: học sinh, môn thi, lớp, nơi học sinh đi tiếp, tuyển sinh theo nguyện vọng.
  2. **Review cư dân.** Có 8 điểm con, tag, ưu/nhược điểm, cùng một bản tóm tắt AI cho cả borough, nêu khu hợp với ai và không hợp với ai.
  3. **Cách trình bày.** Mọi chỉ số có điểm 1–10 so với toàn quốc và câu kết luận dễ hiểu. Có nhận định so với khu lân cận ("Borders with low-income areas"). Mỗi lựa chọn trong dropdown là một lớp bản đồ có chú giải. Mỗi tab con có URL riêng.
  4. **Cấp địa lý và loại trang mà ta chưa có:** ward, ga (với báo cáo đầy đủ), quốc gia, cùng phân loại khu dân cư (ONS OAC).
- **Số liệu CR có mà ta chưa có: 24 nhóm** (mục 3). Khoảng 18 nhóm lấy được từ nguồn mở. Phần còn lại cần tự xây (review, AVM) hoặc không nên làm (council tax theo từng địa chỉ).
- **Kế hoạch: 6 đợt, khoảng 10–12 tuần** (mục 5). Ưu tiên những gì tạo nhiều trang SEO và giúp giữ người dùng: trang trường đầy đủ, trang ward, điểm 1–10 kèm câu kết luận, review.

---

## 1. Cấu trúc của CrystalRoof (cây mục đầy đủ)

Ký hiệu: 🔒 bị khoá ở gói FREE.

```
Postcode report  /report/postcode/{PC}/{tab}
├─ Overview         thanh "Data says": mỗi mục có kết luận + điểm X/10 + nút "View …"
│   ├─ Locals say: điểm review 8.0, 8 điểm con, tag (Urban, Diverse…), 4 câu trích nổi bật
│   ├─ Income 7/10 · "Borders with low-income areas"
│   ├─ Deprivation 5/10 · "The larger area Rye Lane contains a significant number of deprived areas"
│   ├─ Crime 6/10 · 4 loại tội nổi bật
│   ├─ Demographics: dân tộc chính, nhóm "relatively significant presence", tôn giáo, tuổi, loại hộ
│   ├─ Tenure (sở hữu/thuê tư/thuê xã hội) so với London · "Borders an area with a higher than average share of social housing"
│   ├─ Professional occupations 🔒 · Residents with degrees 🔒
│   ├─ Noise · Air quality · Flood risk (mỗi mục một câu kết luận)
│   ├─ Transport 6/9 (PTAL), số ga trong 1 dặm
│   ├─ Amenities: food stores 10+, 3 cửa hàng gần nhất…
│   ├─ Schools: 3 trường tiểu học + 3 trung học gần nhất, kèm Ofsted
│   └─ Classification: ONS OAC 2021 (Smaller area = subgroup, Wider area = supergroup), mỗi nhóm có đoạn mô tả dài
├─ Affluence
│   ├─ Household Income: £/năm, 7/10, so sánh neighbourhood/borough/London, bản đồ MSOA chia 10 lớp
│   ├─ Deprivation (?tab=deprivation): IMD 5/10 + 7 domain, mỗi domain có điểm 1–10 và đoạn giải thích
│   │    └─ dropdown "Type" (16 lớp bản đồ): IMD, 7 domain, IDACI, IDAOPI,
│   │       6 sub-domain (Children & Young People, Adult Skills, Geographical Barriers,
│   │       Wider Barriers, Indoors, Outdoors)
│   ├─ Occupation (?tab=occupation) 🔒 bản đồ: NS-SeC 5 nhóm, "Concentration of professionals 9/10",
│   │    bảng % so với borough/London, chuyển Immediate Area ↔ Borough
│   └─ Qualification (?tab=qualification) 🔒 bản đồ: 7 bậc đổi sang nhãn dễ hiểu (University degree,
│        College/A-levels, Trade training…), "Concentration of degree holders 9/10"
├─ Crime
│   ├─ chọn kỳ: 1 tháng / 3 tháng / 6 tháng / 1 năm
│   ├─ tỉ lệ / 1.000 "at-risk population" (burglary tính / 1.000 nhà), điểm 6/10
│   ├─ 14 loại tội × (tỉ lệ, điểm 1–10 toàn quốc), chuyển Local Area ↔ Borough
│   ├─ đoạn tự sinh: "Is … a safe place to live?", "Highest relative crime scores", "Most common by volume"
│   ├─ xu hướng 2011–2025 (khu / borough / London) + mô tả bằng chữ
│   └─ (cấp borough) tab Summary · Crime by type · Crime rates by year · Crime by ward,
│        ward an toàn nhất/kém nhất, biểu đồ riêng cho tội nghiêm trọng (bạo lực, cướp, vũ khí…), tải PNG
├─ Demographics
│   ├─ Ethnic Makeup: 16 nhóm, cao/thấp hơn TB London, dropdown bản đồ theo từng nhóm
│   ├─ Religion (?tab=religion): 9 nhóm, dropdown bản đồ
│   ├─ Residents Age (?tab=residents-age): 5 nhóm 20 năm, dropdown bản đồ
│   └─ Household Type (?tab=household-type): 7 loại (families with young children…), dropdown bản đồ
├─ Noise 🔒 (cấp postcode). Xem được ở cấp ward:
│   ├─ % diện tích bị ảnh hưởng: tiếng ồn đường bộ 48,9%, đường sắt 22,1% (Lden), máy bay
│   └─ nguồn khác: bar/pub/club (≤161 m), cứu hoả, A&E, bệnh viện, trạm cứu thương, chuông nhà thờ (≤483 m)
├─ Transport: PTAL 0–6b (heatmap), travel zone, 9 ga trong 1 dặm kèm hãng/tuyến (southern, thameslink…)
├─ Amenities: dropdown 5 loại; mỗi loại có số lượng + "Show N more"; GP có địa chỉ, SĐT, website
├─ Schools: danh sách 20/trang + bộ lọc (cấp học, Ofsted, tôn giáo, giới tính, công/tư, oversubscribed)
│   └─ /school/{URN}: General · Pupils · Exams (Primary / Secondary / 16 plus) · Subjects · Admissions · Class sizes · Destinations
├─ Environment
│   ├─ Air Quality: NO2, PM10, PM2.5, số ngày PM10 vượt ngưỡng (London: LAQN), dropdown 4 chất
│   └─ Flood Risk (?tab=flood-risk): sông/biển + nước mặt, 5 mức
└─ Reviews 🔒 một phần: điểm, 8 điểm con, tag, danh sách review, "Read pros & cons", /review/{id}, /review/create

Trang khác: /report/{country|uk-country|region|lad|ward|rail-station|overground-station}/{slug}/{tab}
            /valuation (định giá tức thì + đẩy lead cho môi giới) · /mortgage-brokers · /pricing · /products/api · /products/widgets
```

**Mô hình thu tiền của CR:** FREE (postcode bị làm mờ, cấp khu lớn đầy đủ), £7,99/tuần, £12,99/tháng, £29,99/3 tháng. "Coming soon": dán link Zoopla/Rightmove, so sánh khu, 10 PDF, Chrome extension. API từ £25 đến £2.000/tháng, 2,6 triệu postcode, "100+ data points".

---

## 2. So sánh từng mục (CR → ZoneCheck)

✅ ta đã có ngang hoặc hơn · ◐ có một phần · ❌ chưa có · ⭐ ta hơn CR

### 2.1 Overview

| Thành phần CR | ZoneCheck | Khoảng trống |
|---|---|---|
| Kết luận + điểm X/10 cho mỗi mục | ◐ có điểm 8 nhóm × 6 vai trò, thanh phân vị | Thiếu **câu kết luận ngắn kèm "X/10"** cho từng chỉ số gốc (Income 7/10, Crime 6/10…) |
| Nhận định so với khu lân cận ("Borders with low-income areas", "Borders an area with … social housing", "The larger area contains deprived areas") | ❌ | **Tính năng mới:** so sánh LSOA/MSOA với các khu kề bên và với ward/LAD |
| Tenure so với TB vùng | ◐ ts054 đã có, chưa đưa lên overview | Đưa lên overview, so với region |
| Classification (OAC) có đoạn mô tả | ❌ | **Thiếu dữ liệu** (mục 3) |
| Locals say (review) | ❌ | **Thiếu tính năng** (mục 4.5) |
| Mini-list ga, siêu thị, trường | ✅ | — |
| Rủi ro (radon, mỏ, lún…), giá nhà, thuê, EPC, quy hoạch, council tax, checklist trước khi trả giá | ⭐ | CR không có |

### 2.2 Affluence

| Tab con / chỉ số | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| Household income | MSOA, "partly modelled", 2020 | ✅ `uk.income.*` MSOA (thêm net, AHC, BHC) ⭐ | Thiếu điểm 7/10 kèm câu chữ; thiếu dòng so sánh với London/region |
| Bản đồ income chia 10 lớp | ✅ | ◐ có MetricMap | Kiểm tra chú giải 10 lớp |
| IMD + 7 domain có điểm và giải thích | ✅ | ◐ có đủ 7 domain trong DB, nhưng trang People chỉ hiện 5 decile | Hiện đủ 7 domain + IDACI + IDAOPI, mỗi cái có đoạn giải thích |
| **6 sub-domain IoD** (Children/Young People, Adult Skills, Geographical/Wider Barriers, Indoors/Outdoors) | ✅ | ❌ | **Thiếu dữ liệu**: nạp thêm file sub-domain của IoD2025 |
| Dropdown 16 lớp bản đồ deprivation | ✅ | ❌ | Bản đồ choropleth theo từng domain/sub-domain |
| Occupation NS-SeC 5 nhóm + "concentration of professionals X/10" | ✅ | ◐ ts062 có trong DB | Cần trang/tab riêng, gộp 5 nhóm như CR, điểm 1–10, so với borough/London |
| Qualification 7 bậc, nhãn dễ hiểu + "degree holders X/10" | ✅ | ◐ ts067 có trong DB | Như trên |
| Phân bố khu giàu/nghèo trong ward/LAD ("58% wealthy, 30% average, 12% low-income") | ✅ | ❌ | Tính từ phân phối MSOA/LSOA trong khu |
| UC, affordability ratio, nhà thuộc sở hữu công ty | — | ⭐ | — |

### 2.3 Crime

| Chỉ số / tính năng | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| 14 loại tội × tỉ lệ × điểm 1–10 toàn quốc | ✅ | ✅ có đủ 14 loại, xếp hạng toàn quốc và LAD | — |
| Chọn kỳ 1/3/6/12 tháng | ✅ | ❌ chỉ 12 tháng | Thêm bộ chọn (dữ liệu tháng đã có trong `crime_incident`) |
| Mẫu số: "at-risk population", burglary tính / nhà | ✅ | ◐ / 1.000 dân | Burglary nên chia theo số nhà (dwellings), dùng Census ts044 hoặc VOA stock |
| Xu hướng **2011–2025** | ✅ | ❌ chỉ có từ 2023-09 (36 tháng) | **Thiếu dữ liệu lịch sử**: data.police.uk có archive từ 12/2010. Chỉ cần lưu tổng theo LSOA × năm × loại, không lưu từng vụ |
| Đoạn chữ tự sinh ("Is X safe?", "highest relative scores", "most common by volume") | ✅ | ◐ có dek + verdict | Viết bộ sinh văn bản theo mẫu (tốt cho SEO) |
| **Crime by ward** trong LAD (ward an toàn nhất/kém nhất) | ✅ | ❌ | Cần cấp ward (mục 4.2) |
| Biểu đồ riêng cho tội nghiêm trọng (bạo lực, cướp, vũ khí) | ✅ | ❌ | Có thể làm khi có dữ liệu lịch sử |
| Tải biểu đồ PNG | ✅ | ❌ | Ưu tiên thấp |
| Phố có nhiều vụ nhất, kết quả xử lý, số vụ trong bán kính | — | ⭐ | — |

### 2.4 Demographics

| Tab con | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| Ethnic Makeup 16 nhóm, cao/thấp hơn TB region, dropdown bản đồ | ✅ | ◐ ts021 có, so với LAD | So sánh thêm với **region**; logic "relatively significant presence"; bản đồ theo từng nhóm |
| Religion 9 nhóm | ✅ | ◐ ts030 | Như trên |
| Residents Age 5 nhóm 20 năm | ✅ | ◐ ts007a (5 năm) | Gộp sang nhóm 20 năm; thêm tuổi theo từng năm (ts009) nếu cần |
| Household Type 7 loại, nhãn dễ hiểu | ✅ | ◐ ts003 | Đổi nhãn Census sang ngôn ngữ đời thường như CR |
| Chuyển Immediate Area ↔ Borough | ✅ | ◐ | — |
| **Bảng Census ở API của CR mà ta chưa nạp** | ✅ | ❌ | Xem mục 3, nhóm D |

### 2.5 Noise

| Chỉ số | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| Lden đường bộ, đường sắt, máy bay | ✅ (map overlay, % diện tích ward) | ⭐ tại tâm postcode + % dân (Lden 55/65, Lnight) | Thêm **% diện tích** cho ward/LAD (CR dùng để viết câu "48,9% of the area…") |
| Khoảng cách tới **đường gần nhất + cấp đường** (A/B/Motorway…) | ✅ (API) | ❌ | **Thiếu OS Open Roads** |
| Bar/pub/club ≤161 m | ✅ | ✅ (POI pub, nightclub) | Thêm luật "trong 161 m" ở mục tiếng ồn |
| Cứu hoả ≤483 m | ✅ | ✅ (2.110 POI) | — |
| **A&E, bệnh viện, trạm cứu thương** ≤483 m | ✅ | ◐ có `health.trust_site` nhưng chưa tách A&E/ambulance | Tách A&E (NHS ODS / NHS England) + trạm cứu thương (OSM `emergency=ambulance_station`) |
| **Chuông nhà thờ** ≤483 m | ✅ | ❌ | **Thiếu dữ liệu**: Dove's Guide (tháp có chuông kéo, khoảng 7.000 tháp) |

### 2.6 Environment: Air và Flood

| Chỉ số | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| NO2, PM10, PM2.5 so với ngưỡng | ✅ (London: LAQN/LAEI phân giải cao) | ◐ PCM 1 km toàn quốc | London: nạp **LAEI 20 m**; thêm so sánh ngưỡng EU/WHO |
| **Số ngày PM10 vượt 50 µg/m³** | ✅ | ❌ | Có trong LAEI (London). Ngoài London: bỏ qua |
| Flood sông/biển + nước mặt, 5 mức | ✅ | ⭐ có thêm hồ chứa, lũ cũ, đê, Wales | Scotland (SEPA) để giai đoạn sau |
| Khí hậu, AQMA, SSSI… | — | ⭐ | — |

### 2.7 Transport

| Chỉ số | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| PTAL 0–6b tại điểm + heatmap | ✅ | ◐ PTAI theo LSOA | **PTAL lưới 100 m** (London Datastore) để tra đúng điểm, kèm lớp heatmap |
| Travel zone | ✅ | ✅ 356 ga (`tfl_zone`) | Gán zone cho postcode (theo ga gần nhất hoặc polygon zone) |
| Ga trong 1 dặm **kèm hãng/tuyến** (southern, thameslink, overground) | ✅ | ◐ chỉ có tuyến TfL | **Thiếu hãng tàu (TOC)** cho mọi ga National Rail |
| Bus stops gần nhất (NaPTAN) | ✅ | ✅ 375.507 điểm | — |
| Connectivity tới việc/trường/y tế (TCM), lượt khách ga | — | ⭐ | — |

### 2.8 Amenities

| Chỉ số | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| 5 loại (siêu thị+tiện lợi, nhà hàng/café, pub/bar, GP, nhà thuốc), N gần nhất, "Show more" | ✅ | ✅ còn nhiều loại hơn ⭐ | — |
| GP: địa chỉ, SĐT, website | ✅ | ◐ (có CQC + GPPS ⭐) | Hiện SĐT/website nếu attrs có |
| Lọc theo điểm vệ sinh FSA | ✅ (API) | ✅ có FHRS 414.866 | Thêm bộ lọc trên UI |
| Green spaces 10 loại (API) | ✅ | ✅ zone `greenspace.*` | — |

### 2.9 Schools: danh sách và trang từng trường (khoảng trống lớn nhất)

| Tab trang trường CR | Chỉ số | ZoneCheck | Khoảng trống |
|---|---|---|---|
| General | Ofsted + **key judgements** (5–6 mục), giới tính, tuổi, loại, công/tư, admissions policy, tôn giáo, sixth form, LA, URN, địa chỉ, website | ✅ có đủ key judgements (`ofsted_oeif` theo aspect) + attrs GIAS | — |
| **Pupils** | số HS + % sức chứa, % nam/nữ, **% tiếng mẹ đẻ không phải tiếng Anh (EAL), % FSM, % vắng học thường xuyên, % SEN, cơ cấu dân tộc HS (16 nhóm)** | ◐ chỉ có NumberOfPupils, Capacity, %FSM (attrs) | **Thiếu**: EAL, giới tính, dân tộc HS (DfE *Schools, pupils and their characteristics*), SEN (DfE *SEN in England*), vắng học (DfE *Pupil absence*) |
| Exams: Primary | % đạt chuẩn, % đạt cao RWM, điểm đọc/toán **so với LA và England** | ◐ có điểm trường (`uk.ks2.*`) | **Thiếu TB của LA và England** |
| Exams: Secondary | % EBacc entering, Grade 5+ Eng & maths, Attainment 8, EBacc APS, so với LA/England | ◐ có A8, P8, 4+/5+, EBacc APS | Thiếu % **entering EBacc**, TB LA/England |
| Exams: 16 plus | A-level APS + grade, **Best 3**, **% AAB+**, so với LA/England | ◐ có APS + grade | Thiếu Best 3, AAB%, TB so sánh |
| **Subjects** | số bài thi GCSE/Technical Award theo môn | ❌ | KS4 subject-level entries (performance tables) |
| Admissions | chỉ tiêu, oversubscribed, đơn nguyện vọng **1/2/3 + từ LA khác**, offer theo nguyện vọng | ◐ chỉ có nguyện vọng 1 | Nạp đủ các cột nguyện vọng 2/3, LA khác (cùng file EES đã tải) |
| **Class sizes** | sĩ số TB lớp một giáo viên, KS1/KS2; **sĩ số theo khối × giới tính** | ❌ | DfE class size + headcount theo NC year (school census) |
| **Destinations** | sau GCSE (9 hướng) và sau A-level (đại học, top-third HEI, level 4/5, học nghề bậc cao), so với LA/England | ❌ | DfE *KS4 & 16–18 destination measures* (theo trường) |
| Bộ lọc danh sách trường | phase, Ofsted, religious, gender, funding, oversubscribed | ◐ | Thêm bộ lọc + phân trang |

### 2.10 Reviews

| Thành phần | CR | ZoneCheck |
|---|---|---|
| Điểm tổng + 8 điểm con (Architecture, Green spaces, Prosperity, Safety, High street, Transport, Community, Schools) | ✅ | ❌ |
| Tag (Urban, Residential, Diverse, New, Lively, Peaceful) | ✅ | ❌ |
| Review: tiêu đề, nội dung, "Things to improve" (pros/cons), tác giả, ngày, phố + postcode | ✅ | ❌ |
| **Tóm tắt AI cấp borough**: Overall character, Transport, Amenities, Green, Safety, Schools, Community, Atmosphere, Housing & cost, **Best for / Less ideal for**, Bottom line | ✅ | ❌ |
| Câu trích nổi bật trên overview | ✅ | ❌ |

### 2.11 Cấp địa lý, loại trang, sản phẩm

| Thành phần | CR | ZoneCheck | Khoảng trống |
|---|---|---|---|
| Postcode unit, LAD, region | ✅ | ✅ (+ sector, district, town ⭐) | Ta để `noindex` cho postcode unit; CR index mọi tab của postcode |
| **Ward** (6.633) đủ 10 tab | ✅ | ❌ (chỉ có zone `admin.ward`) | Thêm cấp `ward` vào `geo_area` |
| **Country** (UK, England) | ✅ | ◐ | Trang quốc gia |
| **Ga = một báo cáo khu đầy đủ** | ✅ | ◐ trang ga chỉ có lượt khách | Gắn báo cáo khu (tâm = ga) vào trang ga |
| URL riêng cho mỗi tab con (`?tab=`) | ✅ | ◐ có topic page, chưa có tab con | Tab con thành URL riêng, mỗi URL có title/H1 riêng |
| "Explore … in nearby locations" (7 postcode kề bên) trên mọi trang | ✅ | ◐ có `Nearby` | Thêm link kề bên cho từng topic |
| Định giá tức thì + đẩy lead cho môi giới | ✅ | ❌ (`mkt_uk.avm_estimate` rỗng) | AVM (PLAN, giai đoạn 3) |
| Giới thiệu môi giới vay | ✅ | ❌ | Không hợp mô hình AdSense; có thể làm affiliate sau |
| API trả phí, widget cho trang môi giới | ✅ | ❌ | Giai đoạn sau; widget miễn phí kèm backlink giúp SEO |
| So sánh khu, PDF, Chrome extension | "Coming soon" | ⭐ so sánh đã có; PDF/extension có trong PLAN | Đi trước CR, nên đẩy nhanh |

---

## 3. Số liệu CR có mà ta chưa có

Mã A–F dùng ở kế hoạch (mục 5). Số `#` nối tiếp [DATA_GAP_TRACKER.md](DATA_GAP_TRACKER.md).

| # | Số liệu | CR dùng ở đâu | Nguồn mở đề xuất | Lấy được? | Độ khó |
|---|---|---|---|---|---|
| **A. Trường học** |||||
| 41 | Đặc điểm HS: % EAL, giới tính, dân tộc HS, headcount theo khối | Pupils, Class sizes | DfE EES *Schools, pupils and their characteristics* (file cấp trường) | ✅ | Thấp |
| 42 | % SEN (EHC plan + SEN support) | Pupils | DfE EES *Special educational needs in England* (cấp trường) | ✅ | Thấp |
| 43 | % vắng học thường xuyên | Pupils | DfE EES *Pupil absence in schools* (cấp trường) | ✅ | Thấp |
| 44 | Sĩ số lớp TB, KS1/KS2 | Class sizes | DfE EES *Class sizes* (cấp trường) | ✅ | Thấp |
| 45 | % entering EBacc, A-level Best 3, % AAB+ | Exams | Performance tables KS4/KS5 (file đầy đủ, cùng nguồn `schools_perf`) | ✅ | Thấp |
| 46 | TB của LA và England cho mọi chỉ số thi | Exams | Tính từ dữ liệu cấp trường, hoặc dòng LA/national trong file DfE | ✅ | Thấp |
| 47 | Số bài thi theo môn (GCSE, Technical Award) | Subjects | Performance tables, file KS4 subject-level | ✅ | Trung bình |
| 48 | Nơi HS đi tiếp sau KS4/KS5 | Destinations | DfE EES *Key stage 4 & 16–18 destination measures* (cấp trường) | ✅ | Trung bình |
| 49 | Đơn nguyện vọng 2/3, từ LA khác, offer theo nguyện vọng | Admissions | File EES applications & offers đã có (mục #33), nạp thêm cột | ✅ | Rất thấp |
| **B. Deprivation, phân loại khu** |||||
| 50 | 6 sub-domain IoD2025 | Deprivation dropdown | Bộ file IoD2025 của MHCLG (file chứa scores/ranks sub-domain, cần xác định đúng file) | ✅ | Rất thấp |
| 51 | **ONS Output Area Classification 2021** (supergroup/group/subgroup + mô tả) | Overview Classification | ONS *2021 Residential-based Area Classifications* (OA, OGL) | ✅ | Thấp |
| 52 | London OAC (LOAC) | Classification (London) | CDRC (kiểm tra giấy phép) | ◐ | Thấp |
| **C. Tội phạm** |||||
| 53 | Lịch sử tội phạm 2011–2025 theo LSOA × năm × loại | Crime trend | data.police.uk archive (từ 12/2010). Chỉ lưu tổng hợp, chạy trên máy local | ✅ | Trung bình (dữ liệu khoảng 15 năm) |
| 54 | Mẫu số "at-risk": số nhà cho burglary | Crime rate | Census ts044/ts041 hoặc VOA dwelling stock (đã có) | ✅ | Rất thấp |
| **D. Census 2021: bảng CR có trong API, ta chưa nạp** |||||
| 55 | Hộ, gia đình: ts002 tình trạng hôn nhân, ts010 sống chung, ts040 số người khuyết tật trong hộ, ts048 cơ sở tập thể | API | Nomis (cùng tool `census2021_extra`) | ✅ | Rất thấp |
| 56 | Di cư: ts005 hộ chiếu, ts012/013 nơi sinh chi tiết, ts015 năm đến UK, ts018 tuổi khi đến, ts019 di cư 1 năm qua | API | Nomis | ✅ | Rất thấp (nhạy cảm, không tính điểm) |
| 57 | Ngôn ngữ, bản sắc: ts022/023 dân tộc chi tiết/đa dân tộc, ts024 ngôn ngữ chính chi tiết, ts025 ngôn ngữ hộ, ts026 nhiều ngôn ngữ trong hộ, ts027/028 bản sắc quốc gia, ts031/032 tôn giáo chi tiết/đa tôn giáo | API | Nomis | ✅ | Rất thấp (nhạy cảm) |
| 58 | Nhà ở: ts051 số phòng, ts052/053 mật độ ở (occupancy rating), địa chỉ thứ hai và mục đích | API | Nomis | ✅ | Rất thấp |
| 59 | Việc làm: ts059 giờ làm, ts060 ngành, ts064 nghề nhóm nhỏ, ts065 lịch sử việc làm, ts068 học sinh/sinh viên toàn thời gian | API | Nomis | ✅ | Rất thấp |
| 60 | Tuổi chi tiết: ts008 giới tính, ts009 giới tính × tuổi từng năm | API | Nomis | ✅ | Rất thấp |
| 61 | Xu hướng tính dục, bản dạng giới (ts077–079, ts070) | API | Nomis | ✅ | **Không khuyến nghị đưa lên trang** (nhạy cảm, AdSense) |
| **E. Môi trường, tiếng ồn, giao thông** |||||
| 62 | Đường gần nhất + cấp đường (Motorway/A/B…) | Noise, API Roads | OS Open Roads (OGL) | ✅ | Thấp |
| 63 | Chuông nhà thờ | Noise | Dove's Guide for Church Bell Ringers (kiểm tra giấy phép) | ◐ | Thấp |
| 64 | A&E, trạm cứu thương, bệnh viện | Noise | NHS ODS/NHS England (A&E) + OSM `emergency=ambulance_station` | ✅ | Thấp |
| 65 | % **diện tích** ward/LAD bị ồn (Lden ≥55) | Noise ward | Tính lại từ raster Defra đã có | ✅ | Thấp |
| 66 | PTAL lưới 100 m (tra tại điểm) + heatmap | Transport | London Datastore PTAL grid | ✅ | Thấp |
| 67 | Hãng tàu, tuyến của mỗi ga National Rail | Transport | ORR *Estimates of station usage* (station facility owner) + OSM route relations / NaPTAN | ◐ | Trung bình |
| 68 | London: NO2/PM 20 m + số ngày PM10 vượt ngưỡng | Air | LAEI (London Datastore) | ✅ | Trung bình |
| 69 | Tốc độ broadband TB tải xuống/lên theo postcode | API Broadband | Ofcom Connected Nations, file fixed performance theo postcode | ✅ | Thấp |
| **F. Quy hoạch, nhà ở, khác** |||||
| 70 | Đơn xin cấp phép quy hoạch gần đây (loại, trạng thái) | API Planning | London Planning Datahub (GLA, mở) + planning.data.gov.uk `planning-application` (độ phủ chưa đều). Ngoài 2 nguồn này phải scrape portal → **không làm** | ◐ | Trung bình |
| 71 | Review cư dân | Reviews | **Tự thu thập** | ◐ (cần thời gian) | Cao |
| 72 | Định giá tức thì (AVM) | Valuation | Tự xây từ PPD + EPC + HPI (bảng `avm_estimate` đã có) | ✅ | Cao |
| 73 | Council tax band **theo từng địa chỉ** | API | VOA không có file tổng; CR có thể đã scrape. Giữ phân bố band theo LSOA + band D | ❌ (rủi ro điều khoản) | — |
| 74 | Mức thu nhập hộ "partly modelled" ở cấp nhỏ hơn MSOA | Income | Có thể mô hình hoá xuống LSOA từ IMD income + Census NS-SeC (gắn nhãn "ước tính") | ◐ | Trung bình |

---

## 4. Tính năng và trình bày cần bổ sung (không cần dữ liệu mới)

1. **Điểm 1–10 kèm câu kết luận cho mọi chỉ số gốc.** Ví dụ: "Wealthy area 7/10", "Concentration of professionals 9/10". Điểm là decile toàn quốc theo cùng cấp so sánh (`comparison_scope`). Đã có `metric_value.percentile`, chỉ cần đổi sang decile và chọn câu chữ.
2. **Cấp ward.** Đưa 6.633 ward vào `core.geo_area` (level `ward`) kèm liên kết OA/LSOA → ward (ONS lookup), rồi rollup toàn bộ chỉ số. Việc này mở thêm khoảng 6.600 trang và mọi topic, cho phép "Crime by ward" và "ward an toàn nhất/kém nhất" trong LAD.
3. **Nhận định so với khu lân cận.** Với mỗi LSOA/MSOA, tìm các khu kề bên (`ST_Touches`) và khu cha (ward/LAD). Sinh các câu như: "giáp khu thu nhập thấp", "khu lớn chứa nhiều LSOA thiếu thốn (≥X% decile 1–3)", "giáp khu có tỷ lệ nhà xã hội cao hơn TB". Phân bố trong khu: "58% khu giàu / 30% trung bình / 12% thu nhập thấp".
4. **Tab con có URL riêng + dropdown bản đồ cho từng biến.** Affluence (Income/Deprivation/Occupation/Qualification), People (Ethnicity/Religion/Age/Household), Environment (Air/Flood), Crime (theo loại). Mỗi lựa chọn trong dropdown là một lớp choropleth có chú giải 10 lớp; route `/api/uk/map/{layer}` đã có sẵn khung.
5. **Review cư dân.** Form gồm 8 điểm con, tag, nội dung, "things to improve", phố/postcode (xác minh bằng email). Có kiểm duyệt, chống spam. Hiển thị ở mọi cấp, tổng hợp lên LAD. Khi đủ dữ liệu thì có **tóm tắt AI theo LAD** (nêu nguồn là review; tách khỏi phần dữ liệu chính thức).
   - **Trong lúc chưa có review:** sinh mục "**Best for / Less ideal for**" **từ dữ liệu** (điểm theo vai trò đã có). Đây là lợi thế: CR chỉ có mục này khi khu có review.
6. **Trang ga thành báo cáo khu đầy đủ** (tâm = ga), kèm hãng/tuyến (#67).
7. **Bộ sinh văn bản theo mẫu cho từng topic.** Ví dụ: "Is X a safe place to live?", "highest relative scores", "most common by volume", mô tả xu hướng bằng chữ ("falls from … then climbs to …"). Trang được thêm nội dung riêng cho SEO và trả lời đúng câu người dùng hay tìm.
8. **Crime:** chọn kỳ 1/3/6/12 tháng; burglary chia theo số nhà; sau #53 thì thêm biểu đồ tội nghiêm trọng và xu hướng 15 năm.
9. **Trường học:** bộ lọc 6 tiêu chí + phân trang; trang trường có 7 tab (sau nhóm A); luôn so với LA/England.
10. **Liên kết nội bộ "Explore … in nearby locations"** cho từng topic (7 postcode/sector kề bên).
11. **Cân nhắc lại chiến lược `noindex` postcode unit.** CR index mọi tab của 2,6 triệu postcode. Ta đang dồn canonical về sector. Đề xuất: giữ `noindex` cho postcode, nhưng **index tab con của sector/district/ward**. Theo dõi Search Console rồi mới quyết định mở rộng.
12. **Tải biểu đồ PNG, widget nhúng miễn phí cho môi giới kèm backlink.** Ưu tiên thấp.

---

## 5. Kế hoạch triển khai

Nguyên tắc (theo memory dự án): mỗi nguồn đi theo luồng tool tải → loader → kiểm tra số dòng, khoảng giá trị, mã lạ (fail thì rollback) → xoá file thô → ghi `ops.etl_run`. Việc nặng (archive police 15 năm, raster, LAEI) chạy ở máy local, chỉ đẩy kết quả tổng hợp lên VPS.

### Đợt 1 (tuần 1–2): "Rẻ mà thấy ngay". Dữ liệu sẵn hoặc chỉ cần nạp thêm cột

| Việc | Loại | Mã |
|---|---|---|
| Nạp 6 sub-domain IoD2025; trang People hiện đủ 7 domain + IDACI/IDAOPI + 6 sub-domain, có đoạn giải thích | ETL + web | #50 |
| Admissions: thêm nguyện vọng 2/3, LA khác, offer theo nguyện vọng | ETL + web | #49 |
| Burglary / 1.000 nhà; bộ chọn kỳ 1/3/6/12 tháng | derive + web | #54 |
| Điểm 1–10 + câu kết luận cho mọi chỉ số gốc (decile từ percentile) | web | §4.1 |
| Tách Affluence: Occupation (NS-SeC 5 nhóm) + Qualification (7 bậc, nhãn dễ hiểu) + điểm "professionals/degree X/10" | web | §2.2 |
| Demographics: so với region, logic "relatively significant presence", nhãn hộ gia đình dễ hiểu, tuổi gộp 20 năm | web | §2.4 |
| Tenure lên overview | web | §2.1 |

### Đợt 2 (tuần 3–4): Trường học ngang CR

| Việc | Mã |
|---|---|
| Tool + loader DfE: pupils characteristics (EAL, giới tính, dân tộc, headcount theo khối), SEN, absence, class sizes | #41–44 |
| Performance tables đầy đủ: % entering EBacc, Best 3, AAB%, dòng TB LA/England; KS4 subject entries | #45–47 |
| Destination measures KS4/16–18 | #48 |
| Trang trường 7 tab (General, Pupils, Exams, Subjects, Admissions, Class sizes, Destinations), luôn so với LA/England | web |
| Danh sách trường: bộ lọc 6 tiêu chí, phân trang, URL có tham số lọc | web |

### Đợt 3 (tuần 5–6): Cấp ward + nhận định so với khu lân cận + tab con có URL

| Việc | Mã |
|---|---|
| Thêm level `ward` vào `geo_area` (lookup OA→ward 2024/2025), rollup toàn bộ metric, sitemap | §4.2 |
| LAD: "Crime by ward", ward an toàn nhất/kém nhất; phân bố khu giàu/nghèo, thiếu thốn trong ward/LAD | §4.2, §4.3 |
| Bộ nhận định so với khu lân cận (income, deprivation, social housing, crime) | §4.3 |
| Tab con có URL riêng + dropdown choropleth 10 lớp cho mọi biến (deprivation 16 lớp, ethnicity, religion, age, household, pollutant, crime type) | §4.4 |
| Bộ sinh văn bản theo mẫu cho crime, demographics, affluence, transport | §4.7 |
| "Explore … in nearby locations" cho từng topic | §4.10 |

### Đợt 4 (tuần 7–8): Tiếng ồn, giao thông, không khí, phân loại khu

| Việc | Mã |
|---|---|
| OS Open Roads → đường gần nhất + cấp đường | #62 |
| A&E, trạm cứu thương; chuông nhà thờ (sau khi xác nhận giấy phép); luật "nguồn ồn trong 161/483 m" | #63, #64 |
| % diện tích ward/LAD bị ồn | #65 |
| PTAL 100 m + lớp heatmap; gán travel zone cho postcode | #66 |
| Hãng/tuyến cho mọi ga National Rail; trang ga thành báo cáo khu đầy đủ | #67, §4.6 |
| LAEI London (NO2/PM 20 m, ngày PM10 vượt) | #68 |
| Tốc độ broadband theo postcode | #69 |
| ONS OAC 2021 (+ LOAC nếu giấy phép cho phép), kèm đoạn mô tả từng nhóm trên overview | #51, #52 |

### Đợt 5 (tuần 9–10): Lịch sử tội phạm + Census mở rộng + quy hoạch

| Việc | Mã |
|---|---|
| Archive police 12/2010→nay, tổng hợp LSOA × năm × loại (local), xu hướng 15 năm, biểu đồ tội nghiêm trọng | #53 |
| Census bổ sung: hộ/gia đình, nhà ở (số phòng, mật độ ở), việc làm (ngành, giờ làm), tuổi chi tiết. Nhóm di cư/ngôn ngữ/bản sắc chỉ hiển thị, không tính điểm, gắn nhãn nhạy cảm. **Bỏ** SOGI | #55–60 |
| Đơn xin cấp phép quy hoạch: London Planning Datahub + planning.data.gov.uk | #70 |

### Đợt 6 (tuần 11–12, sau đó chạy liên tục): Review + AVM

| Việc | Mã |
|---|---|
| Review cư dân: form, 8 điểm con, tag, kiểm duyệt, xác minh email, trang `/review/{id}`, tổng hợp lên LAD/ward | #71 |
| "Best for / Less ideal for" sinh từ dữ liệu, có ngay cho mọi khu. Tóm tắt AI theo LAD khi ≥20 review | §4.5 |
| AVM: mô hình hedonic + repeat-sales (PPD + EPC + HPI), khoảng giá + độ tin cậy, trang `/valuation`, chạy trên máy local rồi đẩy `avm_estimate` | #72 |

### Không làm / để sau

- Council tax band theo từng địa chỉ (#73): không có nguồn bulk hợp lệ.
- Xu hướng tính dục, bản dạng giới (#61): không đưa lên trang.
- Giới thiệu môi giới vay, API trả phí: ngoài mô hình AdSense hiện tại, xem lại khi có traffic.
- Scotland (SEPA flood, SIMD…): theo PLAN giai đoạn 3.

---

## 6. Chỉ số theo dõi sau khi làm

- Số trang index được (Search Console): kỳ vọng tăng mạnh sau đợt 3 (ward + tab con).
- Tỉ lệ trang trường có đủ 7 tab có dữ liệu, mục tiêu ≥90% trường đang mở.
- Mỗi loader mới đạt kiểm tra chéo: tổng HS khớp GIAS ±2%, số ward khớp lookup ONS của năm ranh giới đã chọn (Boundary-Line hiện có 6.633), tổng tội phạm theo năm khớp ONS ±5%.
- Thời gian tải trang topic < 1 s (cache), không vượt `statement_timeout`.

## 7. Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Giấy phép Dove's Guide, LOAC (CDRC) | Kiểm tra trước khi tải; không có giấy phép thì bỏ lớp đó |
| Archive police nặng (khoảng 15 năm × 43 lực lượng) | Xử lý theo tháng ở máy local, chỉ đẩy bảng tổng hợp; không lưu điểm từng vụ trước 2023 |
| Review spam, nội dung bôi nhọ | Kiểm duyệt trước khi hiện, xác minh email, không cho nêu tên người hoặc số nhà |
| Nội dung nhạy cảm (dân tộc, tôn giáo, di cư) ảnh hưởng AdSense | Không tính điểm, trình bày trung tính, không xếp hạng "khu nhiều/ít nhóm X" |
| Cấp ward đổi ranh giới hằng năm | Gắn năm ranh giới (WD24/WD25), rollup lại khi ONS phát hành |

---

## 8. Tiến độ triển khai (cập nhật 2026-10-14)

✅ xong · 🔧 đang nạp trên VPS · ➖ không làm / để sau (có lý do)

| Hạng mục | Trạng thái | Ở đâu |
|---|---|---|
| IoD 6 sub-domain, tab Deprivation 16 lớp bản đồ (Wales: WIMD) | ✅ | `iod2025`; web `…/affluence/deprivation` |
| Tuyển sinh nguyện vọng 1/2/3, LA khác | ✅ | `dfe_school_offers`; trang trường |
| Burglary / 1.000 nhà, chọn kỳ 1/3/6/12 tháng | ✅ | derive `crime`; topic crime |
| Điểm 1–10 + câu kết luận, khối "Data says", nhận định so với khu lân cận, phân bố khu giàu/nghèo | ✅ | `DataSays`, `server/insights.ts` |
| Affluence (Income, Deprivation, Occupation, Qualification), Demographics (Ethnicity, Religion, Age, Households, Background): tab con có URL riêng, bản đồ theo từng nhóm, so với TB vùng | ✅ | `affluence.tsx`, `demographics.tsx`, route `[topic]/[tab]` |
| Trang trường 7 phần + TB LA/England, bộ lọc 6 tiêu chí + phân trang | ✅ | `dfe_spc`, `dfe_school_profile`, `SchoolDetail`, `SchoolTable` |
| Cấp ward (7.596), Crime by ward trong LAD | ✅ | `boundaries_ward` + derive |
| Câu văn tự sinh crime ("Is X safe?"), link "nearby areas" mọi topic | ✅ | topics.tsx, TopicPage |
| OAC 2021/22 + mô tả | ✅ | `geods_oac`; khối Classification |
| Đường lớn gần nhất, nguồn ồn (cứu hoả, cứu thương, A&E, pub/club) | ✅ | `os_open_roads`, `osm_uk`; topic Environment |
| PTAL tại địa chỉ, hãng quản lý ga, LAEI (London) | ✅ | `london_ptal`, `orr_station_usage`, `laei` |
| Trang ga có tóm tắt khu xung quanh | ✅ | `/uk/station/…` |
| Census bổ sung 18 bảng | ✅ | `census2021_more` |
| Lịch sử tội phạm 2011–2025 + tội nghiêm trọng | ✅ | `police_history`; topic crime |
| Đơn xin cấp phép quy hoạch gần đây (London) | ✅ | `london_planning`; topic Planning |
| Review cư dân (form, chống spam, duyệt tay, Locals say) | ✅ | `/uk/review/new`, `mkt_uk.review`, `python -m uk.manual.reviews` |
| "Best for / Less ideal for" từ dữ liệu | ✅ | `DataSays` |
| Định giá tức thì | ✅ | `/uk/valuation` |
| Tóm tắt AI review theo LAD | ➖ | Chờ đủ review (≥ 20/LAD) |
| Chuông nhà thờ | ➖ | Chưa rõ giấy phép Dove's Guide |
| Tốc độ broadband theo postcode | ➖ | File Ofcom performance theo OA không có tốc độ chung |
| Council tax theo địa chỉ, SOGI, LOAC | ➖ | Xem mục 3 |
| Index tab con sector/ward hay postcode | Chờ quyết định của bạn | §4.11 |
| PDF, widget nhúng | ➖ | Ưu tiên thấp, để sau |
