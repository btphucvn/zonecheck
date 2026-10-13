# ZoneCheck — Kế hoạch toàn diện (bản 3: UK-first)

> Nền tảng báo cáo khu vực **miễn phí 100%**, kiếm tiền bằng **Google AdSense**.
> Thứ tự thị trường: **🇬🇧 Anh → 🇺🇸 Mỹ → 🇫🇷 Pháp**. Kiến trúc đa quốc gia, đa ngôn ngữ ngay từ đầu.
> Stack: Next.js (fullstack) + PostgreSQL/PostGIS.
> Cập nhật: 2026-10-11 · Thay thế bản 2 (France-first). Lý do chọn UK: xem Phụ lục D.

---

## 0. Tóm tắt điều hành

- **Mô hình kinh doanh:** web miễn phí, doanh thu từ quảng cáo hiển thị. Chỉ số sống còn là **pageview organic × RPM**.
- **Vì sao Anh trước** (bảng chấm điểm 10 nước ở Phụ lục D):
  - **Dữ liệu ngang được mọi đối thủ:** khoảng 90% dữ liệu của đối thủ lấy được từ nguồn mở. Phần thiếu phần lớn **tự xây được** (định giá, ước tính giá thuê).
  - **RPM cao** (traffic tiếng Anh, thị trường nhà đất giá trị cao).
  - **ETL rẻ và nhanh nhất:** nguồn dữ liệu tập trung, giấy phép OGL thống nhất.
  - **Nội dung tiếng Anh:** dễ kiểm soát chất lượng. Nền tảng dùng lại được cho Mỹ, Canada, Úc.
- **Thách thức chính:** cạnh tranh mạnh. CrystalRoof khoảng 300.000 lượt/tháng và đã mua lại StreetCheck. Ngoài ra có PostcodeCheck, Home-Checker, PropertyData và hàng loạt trang mới. **Ta không thể thắng bằng dữ liệu** (ai cũng lấy được), mà phải thắng bằng:
  1. **Đủ dữ liệu như tất cả đối thủ cộng lại, và miễn phí toàn bộ.** Đối thủ đang thu tiền cho radon, mỏ than, định giá, PDF, so sánh, cảnh báo.
  2. **Chất lượng trang:** nhanh, đẹp trên di động, mỗi con số có nguồn, phương pháp minh bạch.
  3. **Công cụ tương tác mà AI Overviews không thay được:** so sánh, điểm theo vai trò, tìm ngược, bản đồ, máy tính chi phí.
  4. **Trang đích có RPM cao:** máy tính stamp duty/mortgage, chi phí chuyển nhà, trường học.
  5. **Đa ngôn ngữ** (giai đoạn 2) cho người mới đến UK.
- **Phạm vi MVP:** England & Wales trong khoảng 10 tuần. Scotland và Bắc Ireland ở giai đoạn 3.

---

## 1. Thị trường và đối thủ UK

### 1.1 Lưu lượng tham chiếu (ước tính Semrush/Similarweb, 2026)

| Trang | Lượt truy cập/tháng | Ghi chú |
|---|---|---|
| CrystalRoof | khoảng 300.000 | Đã mua StreetCheck (3/2026), StreetCheck chuyển hướng 301 về CrystalRoof |
| StreetCheck (trước khi sáp nhập) | khoảng 150.000–270.000 | Đang chuyển dần sang CrystalRoof |
| PropertyData | (chưa có số) | Thuê bao cho nhà đầu tư |
| Rightmove, Zoopla | Hàng chục triệu | Portal, mục tiêu khác |

**Ý nghĩa:** trang dẫn đầu mảng báo cáo khu vực ở UK có khoảng 300.000 lượt/tháng. Mục tiêu thực tế trong 18–24 tháng là đạt **100.000–300.000 lượt/tháng**.

### 1.2 Danh sách đối thủ

| Đối thủ | Mô hình | Điểm mạnh | Điểm yếu (cơ hội của ta) |
|---|---|---|---|
| **CrystalRoof** (+StreetCheck) | Miễn phí cơ bản + subscription, API, widget, giới thiệu môi giới vay | 10 nhóm dữ liệu, chi tiết theo đường phố (khoảng 2,6 triệu postcode), TfL, định giá nhanh, review, school guide | Phần sâu phải trả tiền. Mạnh nhất ở London. Không so sánh, không tìm ngược, chỉ tiếng Anh |
| **PostcodeCheck** | Freemium, report £2,99–6,99 | Area Score, recommender, so sánh, radon, mỏ than, listed/conservation, chủ sở hữu là công ty, máy tính chi phí | Thu tiền lẻ, phương pháp chấm điểm không rõ, một số số liệu là ước tính |
| **Home-Checker** | Report £24,99–29,99 | Lũ, EPC, khí hậu, SSSI/AONB, đất ô nhiễm, sụt lún, tóm tắt dễ hiểu | Đắt, chỉ England, report hết hạn sau 30 ngày |
| **PropertyData** | £15–60/tháng | Giá chào bán, giá thuê, yield, Plot Map (ranh giới thửa, chủ sở hữu), quy hoạch, định giá, HMO | Dành cho nhà đầu tư, đắt |
| **Locrating** | Thuê bao | Khu tuyển sinh trường học, extension cho portal | Hẹp, giao diện cũ |
| **Area360** | Extension miễn phí | Lớp dữ liệu phủ lên tin đăng Rightmove/Zoopla | Không có trang khu vực riêng |
| **Chimnie** | B2B, trang cho mọi địa chỉ | Rủi ro, chi phí xây lại, định giá | Bị phàn nàn về quyền riêng tư |
| **Nhóm mới** (HouseCheckup, AreaView, Know My Postcode, NestScope, MoveCompass, Postcode Explorer của Homethink, postcodecheck.online…) | Freemium / quảng cáo | Ra mắt nhanh | Mỏng, phần lớn do một người làm, chưa có uy tín |
| **Rightmove / Zoopla / OnTheMarket** | Phí từ môi giới | Thương hiệu, giá đã bán | Dữ liệu khu vực nông |

### 1.3 Ma trận tính năng

✅ có · ◐ một phần hoặc phải trả tiền · — không có

| Tính năng | CrystalRoof | PostcodeCheck | Home-Checker | PropertyData | **ZoneCheck (miễn phí)** |
|---|---|---|---|---|---|
| Giá đã bán, xu hướng | ✅ | ✅ | ✅ | ✅ | ✅ MVP |
| £/m² (giá bán ghép diện tích EPC) | ◐ | — | — | ✅ | ✅ MVP |
| Định giá nhanh (AVM) | ✅ | — | — | ✅ | ✅ Giai đoạn 3 |
| Giá thuê | ◐ | ◐ | — | ✅ | ✅ MVP (LA) → Giai đoạn 2 (MSOA ước tính) |
| Tội phạm (bản đồ, loại, xu hướng) | ✅ | ✅ | ✅ | — | ✅ MVP |
| Trường học (Ofsted cũ + report card, kết quả thi) | ✅ | ✅ | ✅ | — | ✅ MVP + trang riêng từng trường |
| Khu tuyển sinh | — | — | — | — | ◐ Giai đoạn 3 (khoảng cách tuyển sinh, các LA lớn) |
| Nhà trẻ (Ofsted early years) | — | — | — | — | ✅ Giai đoạn 2 |
| Lũ (sông/biển, nước mặt, cảnh báo) | ✅ | ✅ | ✅ | — | ✅ MVP |
| Radon | — | ◐ (trả phí) | ✅ (trả phí) | — | ◐ Giai đoạn 2 (*kiểm tra giấy phép UKHSA/BGS*) |
| Mỏ than | — | ◐ (trả phí) | ◐ | — | ✅ Giai đoạn 2 (Coal Authority, *kiểm tra giấy phép*) |
| Sụt lún, nền đất (GeoSure) | — | ◐ | ✅ | — | ❌ (BGS trả phí). Ghi rõ là không có |
| Broadband, di động | ◐ | ✅ | ✅ | — | ✅ MVP / Giai đoạn 2 |
| Không khí | ✅ | ✅ | ✅ | — | ✅ MVP |
| Tiếng ồn | ✅ | ✅ | — | — | ✅ Giai đoạn 2 |
| Khí hậu | — | — | ✅ | — | ✅ Giai đoạn 2 (Met Office HadUK-Grid) |
| Nhân khẩu, thu nhập, IoD 2025 | ✅ | ✅ | — | ✅ | ✅ MVP |
| Giao thông (ga, xe buýt, PTAL London, hiệu suất tàu điện ngầm) | ✅ | ✅ | ✅ | — | ✅ MVP (+ PTAL) |
| Tiện ích (GP, siêu thị, công viên) | ✅ | ✅ | ✅ | — | ✅ MVP |
| EPC khu vực | — | ✅ | ✅ | ◐ | ✅ MVP |
| Council tax | — | ✅ | ✅ | ✅ | ✅ Giai đoạn 2 |
| Listed, conservation, Article 4, green belt | — | ◐ (trả phí) | — | ✅ (trả phí) | ✅ Giai đoạn 2 (planning.data.gov.uk) |
| Khu bảo tồn (SSSI, AONB, National Park) | — | — | ✅ | — | ✅ Giai đoạn 2 |
| Nhà thuộc sở hữu công ty | — | ◐ (trả phí) | — | ✅ | ◐ Giai đoạn 3 (CCOD/OCOD, cấp khu vực) |
| Đơn xin cấp phép quy hoạch | — | ◐ | — | ✅ | ◐ Giai đoạn 3 (độ phủ chưa đều) |
| Review cư dân | ✅ | — | — | — | ◐ Giai đoạn 3 |
| Điểm khu | — | ✅ | ◐ | — | ✅ MVP, **cá nhân hóa theo vai trò** |
| So sánh khu | — | ◐ (trả phí) | ◐ (trả phí) | — | ✅ MVP, miễn phí, tối đa 4 khu |
| Tìm ngược ("tôi nên sống ở đâu") | — | ◐ (trả phí) | — | ◐ | ✅ Giai đoạn 2, miễn phí |
| Máy tính stamp duty, mortgage, chi phí sinh hoạt | — | ✅ | — | ✅ | ✅ MVP (trang RPM cao) |
| PDF, link chia sẻ | — | ◐ | ✅ (trả phí) | ✅ (trả phí) | ✅ Giai đoạn 2, miễn phí |
| Cảnh báo theo dõi khu | — | — | — | ✅ (trả phí) | ✅ Giai đoạn 2 |
| Isochrone đi làm | ◐ (TfL) | ◐ | — | — | ✅ Giai đoạn 3 |
| Extension cho portal | — | — | — | ✅ | ✅ Giai đoạn 3 |
| Đa ngôn ngữ | — | — | — | — | ✅ Giai đoạn 2 |
| Nguồn + kỳ dữ liệu trên từng chỉ số | ◐ | ◐ | ◐ | ◐ | ✅ MVP |

---

## 2. Dữ liệu: đạt ngang mọi đối thủ

### 2.1 Khoảng trống so với đối thủ và cách lấp

| Dữ liệu đối thủ có | Ai có | Ta lấp bằng cách nào | Lấp được? | Giai đoạn |
|---|---|---|---|---|
| Định giá nhanh (AVM) | CrystalRoof, PropertyData, Chimnie | Mô hình từ Land Registry PPD + diện tích/số phòng từ EPC + điều chỉnh theo HPI (hedonic + repeat-sales). Hiển thị **khoảng giá + độ tin cậy**, ghi rõ là ước tính | ✅ | 3 |
| £/m² | PropertyData | Ghép PPD ↔ EPC theo địa chỉ (khớp mờ trên số nhà, đường, postcode) | ✅ | 1 |
| Giá thuê dưới cấp LA | PropertyData, CrystalRoof (một phần) | Ước tính MSOA = giá thuê PIPR của LA × hệ số giá nhà MSOA/LA, hiệu chỉnh theo tỷ lệ thuê (Census) + loại nhà. Gắn nhãn "ước tính". Về sau thêm dữ liệu người dùng đóng góp | ◐ | 2 |
| Giá chào bán / tin đăng | PropertyData, portal | Không lấy được (scrape vi phạm điều khoản). **Không làm** | ❌ | — |
| Chi tiết theo đường phố (2,6 triệu postcode) | CrystalRoof | Trang theo postcode unit, chỉ số theo bán kính quanh tâm postcode | ✅ | 1 |
| Hiệu suất tàu điện ngầm, PTAL | CrystalRoof | TfL open data + London Datastore (PTAL) | ✅ | 2 |
| Review cư dân | CrystalRoof | Tự thu thập (có kiểm duyệt) | ◐ (cần thời gian) | 3 |
| Radon | PostcodeCheck, Home-Checker | UKHSA/BGS radon indicative atlas: **kiểm tra giấy phép** (bản 1 km có thể dùng được, bản chi tiết trả phí) | ◐ | 2 |
| Mỏ than | PostcodeCheck | Coal Authority open data (Coal Mining Reporting Area, khu khai thác): *kiểm tra giấy phép* | ✅ (dự kiến) | 2 |
| Sụt lún, nền đất | Home-Checker, PostcodeCheck | BGS GeoSure trả phí. Có thể dùng **dữ liệu đất sét co ngót / sạt lở bản mở của BGS** nếu có, còn lại **ghi rõ là không có** | ❌ / ◐ | — |
| Đất ô nhiễm | Home-Checker | Không có dữ liệu quốc gia mở. Hiển thị bãi rác lịch sử (EA Historic Landfill, OGL) thay thế | ◐ | 2 |
| Khí hậu | Home-Checker | Met Office HadUK-Grid (1 km, OGL) | ✅ | 2 |
| SSSI, AONB, National Park | Home-Checker | Natural England open data | ✅ | 2 |
| Listed, conservation, Article 4, green belt, TPO | PostcodeCheck, PropertyData | planning.data.gov.uk + Historic England (Listed Buildings) | ✅ (độ phủ conservation còn chưa đều) | 2 |
| Council tax | PostcodeCheck, Home-Checker | Mức thuế theo băng của LA + phân bố băng theo LSOA (thống kê VOA). Không scrape VOA theo từng nhà | ✅ | 2 |
| Nhà thuộc sở hữu công ty | PostcodeCheck, PropertyData | Land Registry CCOD/OCOD (miễn phí, cần đăng ký và chấp nhận điều khoản). Chỉ hiển thị tổng hợp theo khu | ◐ | 3 |
| Ranh giới thửa đất | PropertyData | INSPIRE Index Polygons (miễn phí kèm điều kiện). Không cần cho người mua/thuê | Bỏ qua | — |
| Đơn xin cấp phép quy hoạch | PropertyData | Không có nguồn quốc gia. Thử dữ liệu planning.data.gov.uk | ◐ | 3 |
| Khu tuyển sinh | Locrating | Khoảng cách tuyển sinh xa nhất do từng LA công bố. Làm thủ công cho khoảng 30 LA lớn | ◐ | 3 |
| HMO register | PropertyData | Rải rác theo từng LA | Bỏ qua | — |

**Kết quả:** sau giai đoạn 2, ta có khoảng **95% dữ liệu của toàn bộ đối thủ cộng lại**, trừ giá chào bán, sụt lún chi tiết và các dữ liệu chỉ phục vụ nhà đầu tư. Toàn bộ **miễn phí**, trong khi đối thủ thu tiền cho phần lớn các mục trên.

### 2.2 Danh mục nguồn dữ liệu UK

OGL = Open Government Licence v3.0 (dùng thương mại được, bắt buộc ghi nguồn).

| # | Dữ liệu | Nguồn | Phạm vi | Cấp chi tiết | Tần suất | Giấy phép | Ghi chú |
|---|---|---|---|---|---|---|---|
| **Địa lý** ||||||||
| 1 | Postcode → tọa độ, OA/LSOA/MSOA/LAD | ONS Postcode Directory (ONSPD) | UK | Postcode | Theo quý | **Có quyền Royal Mail/OS: phải đọc kỹ điều khoản** | Dự phòng: OS Code-Point Open (OGL) |
| 2 | Ranh giới OA, LSOA, MSOA, LAD (2021) | ONS Open Geography | E&W | Polygon | Theo đợt | OGL | |
| 3 | Địa danh, tên thị trấn | OS Open Names | GB | Điểm | Theo quý | OGL | Tìm kiếm theo tên |
| 4 | UPRN | OS Open UPRN | GB | Điểm | Theo quý | OGL | Ghép PPD/EPC |
| **Nhà đất** ||||||||
| 5 | Giá đã bán | **HM Land Registry Price Paid Data** | E&W | Giao dịch | Hằng tháng | OGL (ghi nguồn bắt buộc) | Khoảng 30 triệu dòng từ 1995. Lọc category B |
| 6 | Chỉ số giá nhà | UK HPI | UK | LA | Hằng tháng | OGL | |
| 7 | EPC (hạng, diện tích, loại nhà, năm xây, sưởi) | MHCLG EPC open data | E&W | Chứng chỉ | Hằng tháng | OGL **có ngoại lệ (trường địa chỉ)** | Đăng ký API. Chỉ công bố số liệu tổng hợp |
| 8 | Giá thuê | ONS Price Index of Private Rents (PIPR) | UK | LA × số phòng ngủ | Hằng tháng | OGL | |
| 9 | Council tax (mức theo băng) | Các LA / MHCLG | England, Wales | LA | Hằng năm | OGL | |
| 10 | Phân bố băng council tax | VOA Council Tax stock | E&W | LSOA | Hằng năm | OGL | |
| 11 | Nhà thuộc sở hữu công ty | Land Registry CCOD/OCOD | E&W | Tài sản | Hằng tháng | Điều khoản riêng, cần đăng ký | Giai đoạn 3 |
| **An ninh** ||||||||
| 12 | Tội phạm | **data.police.uk** (archive hằng tháng) | E&W + NI | Điểm ẩn danh + LSOA | Hằng tháng | OGL | Dùng file archive, không dùng API. Theo dõi khoảng trống dữ liệu (ví dụ GMP 2019–2020) |
| **Giáo dục** ||||||||
| 13 | Danh sách trường | DfE GIAS | England | Trường | Hằng ngày | OGL | |
| 14 | Đánh giá Ofsted | Ofsted management information | England | Trường | Hằng tháng | OGL | **Từ 10/11/2025 dùng report card 5 mức theo từng hạng mục**, chuyển dần trong khoảng 4–5 năm. Phải hỗ trợ cả mô hình cũ và mới |
| 15 | Kết quả thi (KS2, KS4, KS5) | DfE Compare School Performance | England | Trường | Hằng năm | OGL | |
| 16 | Nhà trẻ | Ofsted childcare providers | England | Cơ sở | Hằng quý | OGL | Giai đoạn 2 |
| 17 | Trường ở Wales | Welsh Government (danh sách), Estyn (báo cáo thanh tra) | Wales | Trường | Hằng năm | OGL | Estyn không còn xếp hạng tổng |
| **Kinh tế xã hội** ||||||||
| 18 | Mức thiếu thốn | **IoD 2025** (England) · WIMD (Wales) | | LSOA | Khoảng 5 năm | OGL | Không so sánh chéo England ↔ Wales |
| 19 | Nhân khẩu | Census 2021 (Nomis bulk) | E&W | OA/LSOA | 10 năm | OGL | |
| 20 | Thu nhập hộ | ONS small area income | E&W | MSOA | Khoảng 2–3 năm | OGL | |
| **Môi trường và rủi ro** ||||||||
| 21 | Lũ sông/biển | EA NaFRA2 (1/2025), Flood Zones (3/2025) | England | Polygon / lưới | Theo đợt | *Kiểm tra giấy phép* | Không so sánh với dữ liệu 2017 |
| 22 | Lũ nước mặt | EA RoFSW | England | Lưới | Theo đợt | *Kiểm tra* | |
| 23 | Cảnh báo lũ trực tiếp | EA Flood Monitoring API | England | Khu cảnh báo | Thời gian thực | OGL | Cache khoảng 15 phút |
| 24 | Lũ ở Wales | Natural Resources Wales | Wales | Polygon | Theo đợt | OGL | |
| 25 | Không khí | Defra PCM | UK | Lưới 1 km | Hằng năm | OGL | |
| 26 | Tiếng ồn | Defra Strategic Noise Mapping Round 4 | England | Contour | Khoảng 5 năm | OGL | Giai đoạn 2 |
| 27 | Khí hậu | Met Office HadUK-Grid | UK | 1 km | Hằng năm | OGL | Giai đoạn 2 |
| 28 | Radon | UKHSA/BGS indicative atlas | GB | 1 km | | *Kiểm tra giấy phép* | Giai đoạn 2 |
| 29 | Mỏ than | Coal Authority open data | GB | Polygon | | *Kiểm tra giấy phép* | Giai đoạn 2 |
| 30 | Bãi rác lịch sử | EA Historic Landfill | England | Polygon | | OGL | Giai đoạn 2 |
| 31 | Khu bảo tồn | Natural England (SSSI, AONB/National Landscapes, National Parks) | England | Polygon | | OGL | Giai đoạn 2 |
| **Quy hoạch** ||||||||
| 32 | Conservation, Article 4, listed, TPO, green belt | planning.data.gov.uk + Historic England | England | Polygon / điểm | Liên tục | OGL | Không có kết quả không có nghĩa là không có ràng buộc |
| **Giao thông và kết nối** ||||||||
| 33 | Ga, điểm dừng | DfT NaPTAN | GB | Điểm | Hằng ngày | OGL | |
| 34 | Lịch trình xe buýt, tàu | BODS (GTFS), rail timetable | England | Tuyến | Liên tục | OGL | Isochrone giai đoạn 3 |
| 35 | Thời gian tới dịch vụ | DfT Journey Time Statistics | England | LSOA | Hằng năm | OGL | |
| 36 | PTAL, TfL | London Datastore, TfL open data | London | Lưới / tuyến | | OGL / TfL terms | Giai đoạn 2 |
| 37 | Broadband, di động | Ofcom Connected Nations (Spring 2026, bản v2) | UK | Postcode / lưới | 2 lần/năm | OGL | |
| **Tiện ích** ||||||||
| 38 | GP, nhà thuốc, nha sĩ, bệnh viện + số bệnh nhân/GP | NHS ODS, NHS Digital | England | Điểm | Hằng tuần / hằng tháng | OGL | |
| 39 | Điểm vệ sinh nhà hàng | FSA Food Hygiene API | UK | Điểm | Hằng ngày | OGL | |
| 40 | Công viên | OS Open Greenspace | GB | Polygon | | OGL | |
| 41 | Siêu thị, gym, tiện ích khác | OpenStreetMap (+ Geolytix retail points, *kiểm tra giấy phép*) | | Điểm | Liên tục | ODbL | Chỉ hiển thị |

**Ghi nguồn** ở footer và `/sources`: *"Contains HM Land Registry data © Crown copyright and database right [năm]. Contains public sector information licensed under the Open Government Licence v3.0. Contains OS data © Crown copyright and database right [năm]. Contains Royal Mail data © Royal Mail copyright and database right [năm]. © OpenStreetMap contributors."*, kèm ngày cập nhật của từng nguồn.

### 2.3 Dung lượng ước tính

| Bảng | Số dòng | Dung lượng |
|---|---|---|
| Postcode (bao gồm postcode đã ngừng dùng) | khoảng 2,7 triệu | khoảng 1 GB |
| Price Paid | khoảng 30 triệu | khoảng 6–8 GB |
| Tội phạm (36 tháng) | khoảng 18–20 triệu | khoảng 4 GB |
| EPC (bản mới nhất mỗi địa chỉ) | khoảng 25 triệu | khoảng 6 GB |
| Metric values | khoảng 50–100 triệu | khoảng 10 GB |
| **Tổng** | | **khoảng 30–50 GB** |

---

## 3. Sản phẩm

### 3.1 Chân dung người dùng

| Vai trò | Chỉ số ưu tiên |
|---|---|
| **Người mua lần đầu** | Giá, £/m², xu hướng, định giá, tội phạm, lũ, EPC, stamp duty |
| **Người thuê** | Giá thuê, giao thông, tội phạm, broadband, tiện ích, council tax |
| **Gia đình** | Trường (Ofsted, kết quả, khoảng cách, tuyển sinh), nhà trẻ, công viên, an ninh, không khí |
| **Người đi làm** | Ga, tần suất, thời gian tới các trung tâm việc làm, PTAL |
| **Người mới đến UK** (giai đoạn 2) | Tóm tắt dễ hiểu, giải thích thuật ngữ, giá thuê, giao thông, cộng đồng |
| **Người về hưu** | Y tế (GP), yên tĩnh, khí hậu, tiện ích |

### 3.2 Trang và URL

```
/{locale}/{market}/...        locale 'en' mặc định, không có tiền tố (as-needed)

/uk/postcode/sw1a-1aa          Postcode unit
/uk/sector/sw1a-1              Postcode sector
/uk/district/sw1a              Postcode district
/uk/town/{slug}                Thị trấn / thành phố
/uk/area/{lad-slug}            Local authority
/uk/region/{slug}
/uk/school/{urn}-{slug}        Trường học
/uk/station/{crs}-{slug}       Ga tàu
/uk/compare?a=..&b=..          So sánh tối đa 4 khu
/uk/where-to-live              Tìm ngược
/uk/rankings/{metric}/{scope}  Xếp hạng
/uk/tools/stamp-duty · mortgage-affordability · moving-costs · rent-vs-buy
/sources · /methodology · /glossary · /account/*
(Giai đoạn 2: /pl/uk/..., /zh/uk/..., /vi/uk/... có đường dẫn dịch nếu cần)
```

### 3.3 Chiến lược index (chống trang mỏng)

| Loại | Số trang | Chính sách index |
|---|---|---|
| District | khoảng 3.000 | ✅ Index ngay |
| Sector | khoảng 11.000–12.000 | ✅ Index ngay |
| Town / thành phố | khoảng 1.500–2.000 | ✅ |
| LAD, region | khoảng 330 | ✅ |
| Trường học (England + Wales) | khoảng 28.000 | ✅ (trường cấp 2 và trường lớn trước) |
| Ga | khoảng 2.600 | ✅ |
| Xếp hạng | khoảng 300–1.000 | ✅ |
| Công cụ | khoảng 10–20 | ✅ |
| **Postcode unit** | khoảng 1,4 triệu (E&W) | **Mở index dần:** chỉ postcode có dữ liệu riêng đủ khác biệt (có giao dịch trong 5 năm, tội phạm trong bán kính khác sector, trường gần khác…). Các postcode còn lại `noindex` + canonical lên sector. Tăng dần theo dữ liệu Search Console |

Tổng index ban đầu khoảng **50.000 trang**, mở rộng tới vài trăm nghìn khi Google đã tin tưởng domain.

### 3.4 Cấu trúc trang báo cáo (postcode / sector / district / town)

1. **Phần đầu:** tên, bản đồ, **điểm khu 0–100 theo vai trò** (đổi ngay trên trang), 3 điểm mạnh và 3 điểm cần lưu ý, tóm tắt ngắn.
2. **Nhà đất:** giá trung vị theo loại nhà, £/m², xu hướng 10 năm, giao dịch gần đây, định giá (giai đoạn 3), so với district/LA/quốc gia.
3. **Giá thuê:** theo số phòng ngủ, tỷ lệ giá thuê/thu nhập, so sánh thuê với mua.
4. **An toàn:** tỷ lệ trên 1.000 dân, theo loại, xu hướng 12/36 tháng, heatmap.
5. **Trường học:** gần nhất theo cấp, Ofsted (cũ hoặc report card), kết quả, khoảng cách, nhà trẻ.
6. **Giao thông:** ga, điểm dừng, thời gian tới các trung tâm, PTAL ở London.
7. **Tiện ích:** GP (độ quá tải), siêu thị, công viên, nhà hàng (điểm FSA).
8. **Môi trường và rủi ro:** lũ, không khí, tiếng ồn, radon, mỏ than, bãi rác cũ, khí hậu.
9. **Kết nối:** broadband, di động.
10. **Con người:** tuổi, hộ gia đình, sở hữu/thuê, trình độ, thu nhập, IoD.
11. **Nhà ở và năng lượng:** EPC, loại nhà, tuổi nhà, sưởi.
12. **Quy hoạch và bảo tồn:** conservation, listed, Article 4, green belt, SSSI/AONB.
13. **Chi phí:** council tax, ước tính chi phí sinh hoạt, liên kết sang máy tính stamp duty.
14. **Khu lân cận**, rồi **nguồn và kỳ dữ liệu**, nút báo lỗi.

Mỗi chỉ số hiển thị: **giá trị · phân vị so với quốc gia ("an toàn hơn 72% các khu ở England") · kỳ dữ liệu · nguồn · số mẫu**.

### 3.5 Phương pháp tính điểm

- Mỗi chỉ số → phân vị trong `comparable_scope` (England, Wales, hoặc E&W). Đổi chiều cho chỉ số "càng thấp càng tốt".
- **8 nhóm:** Giá cả phải chăng · An toàn · Trường học · Giao thông · Tiện ích & Y tế · Môi trường & Rủi ro · Kết nối · Kinh tế.
- **Điểm tổng = trung bình có trọng số.** Mỗi vai trò có trọng số mặc định, chỉnh được bằng thanh trượt. Thiếu dữ liệu thì chia lại trọng số và hiển thị cảnh báo.
- **Không đưa vào điểm số và không dùng làm bộ lọc:** dân tộc, tôn giáo, quốc tịch.
- Công bố đầy đủ tại `/methodology`.

---

## 4. Kiến trúc đa quốc gia, đa ngôn ngữ

### 4.1 Nguyên tắc

1. **Market** (quốc gia của dữ liệu: `uk`, `us`, `fr`) tách biệt với **Locale** (ngôn ngữ giao diện). Mọi locale xem được mọi market.
2. **Lõi không biết tới quốc gia cụ thể.** Logic riêng nằm trong **market adapter**.
3. **Cấp bậc địa lý tổng quát**, mỗi nước tự khai báo. Ánh xạ giữa các cấp không lồng nhau dùng bảng có trọng số.
4. **Danh mục chỉ số dạng dữ liệu.** Thêm nước hay thêm chỉ số không cần migration.
5. Mỗi chỉ số có `comparable_scope`. Không so sánh chéo giữa các nước hay giữa các phương pháp.

### 4.2 Cấp bậc địa lý

| Market | Cấp | Tìm kiếm |
|---|---|---|
| **uk** | `postcode_unit` → `sector` → `district` → `area`, song song `oa` → `lsoa` → `msoa` → `lad` → `region` → `nation`; thêm `town` | Postcode, tên địa danh |
| us (market 2) | `zcta`, song song `block_group` → `tract` → `county` → `state`; thêm `place` (thành phố) | ZIP, tên thành phố |
| fr (market 3) | `grid_200m`/`address` → `iris` → `commune` (+ `arrondissement`) → `epci` → `departement` → `region` | Commune, mã bưu chính, địa chỉ |

### 4.3 Market adapter

```ts
// packages/core/src/market.ts
export interface MarketAdapter {
  code: 'uk' | 'us' | 'fr';
  defaultLocale: string;          // 'en-GB'
  currency: string;               // 'GBP'
  units: 'imperial' | 'metric';   // UK: khoảng cách theo dặm/phút đi bộ, diện tích m²
  geoLevels: GeoLevelDef[];
  searchableLevels: string[];
  parseQuery(q: string): ParsedQuery;      // postcode / tên địa danh
  normalizeCode(level: string, raw: string): string;
  slugify(level: string, code: string): string;
  metrics: MetricDef[];
  scoreCategories: CategoryDef[];
  personas: PersonaDef[];
  indexPolicy: IndexPolicy;       // quy tắc index/noindex theo cấp và độ đầy đủ dữ liệu
  compliance: ComplianceRules;    // ví dụ FR: ngưỡng DVF; UK: ngoại lệ địa chỉ trong EPC
  attributions: Attribution[];
  tools: ToolDef[];               // UK: stamp duty (khác nhau giữa England, Wales, Scotland), mortgage
}
```

```
packages/markets/uk/   geo.ts, metrics.ts, scoring.ts, personas.ts, index-policy.ts, tools/*, sections/*
etl/markets/uk/sources/ onspd.py, boundaries.py, open_names.py, ppd.py, hpi.py, epc.py, pipr.py,
                        police.py, gias.py, ofsted.py, dfe_results.py, iod.py, census.py, income.py,
                        ea_flood.py, defra_air.py, noise.py, hadukgrid.py, radon.py, coal.py,
                        natural_england.py, planning_data.py, naptan.py, bods.py, ofcom.py,
                        nhs.py, fsa.py, greenspace.py, osm.py, voa_ctax.py
```

### 4.4 Đa ngôn ngữ

- **next-intl:** App Router, Server Components, ICU message format, `localePrefix: 'as-needed'` (tiếng Anh không có tiền tố), có thể dịch đường dẫn.
- **Lộ trình ngôn ngữ cho UK:**
  - **MVP: chỉ EN** (tập trung doanh thu và chất lượng).
  - **Giai đoạn 2:** mở 2–3 ngôn ngữ, chọn theo dữ liệu Search Console và nhu cầu thực tế. Ứng viên: **PL, RO, ZH, HI/UR, AR, VI, PT, ES** (cộng đồng nhập cư và sinh viên quốc tế lớn ở UK).
- **Kiến trúc i18n đầy đủ ngay từ ngày đầu,** dù MVP chỉ có EN:
  - mọi chuỗi giao diện nằm trong `messages/`,
  - tên và mô tả chỉ số dùng i18n key,
  - cột `name_i18n` trong DB,
  - CSS logical properties để hỗ trợ RTL,
  - định dạng số, ngày, tiền qua `Intl`.
- **Trang ngôn ngữ khác phải có giá trị riêng,** không chỉ là bản dịch máy: glossary (council tax, leasehold, freehold, Ofsted, EPC, stamp duty), mục "điều người mới đến UK cần biết", tóm tắt AI theo ngôn ngữ. Có `hreflang` + `x-default`.
- Tiền tệ và đơn vị theo market, định dạng theo locale.

---

## 5. Kiến trúc kỹ thuật

### 5.1 Stack

| Lớp | Lựa chọn | Lý do |
|---|---|---|
| Framework | **Next.js 16 (App Router)**, TypeScript, RSC | Fullstack, ISR cho SEO programmatic |
| UI | Tailwind CSS v4 + shadcn/ui | |
| Biểu đồ | Recharts / visx | |
| Bản đồ | **MapLibre GL** + **PMTiles** trên R2, basemap OpenFreeMap/Protomaps | Không mất phí theo lượt xem |
| DB | **PostgreSQL 16+ / PostGIS**, `pg_trgm` | Truy vấn không gian, tìm kiếm mờ |
| ORM | Drizzle + raw SQL cho truy vấn không gian | |
| ETL | **Python 3.12 + DuckDB + Polars + GeoPandas** → Postgres `COPY` | Xử lý hàng chục triệu dòng nhanh |
| Ghép địa chỉ PPD ↔ EPC | Chuẩn hóa địa chỉ + khớp mờ (rapidfuzz) trong cùng postcode, ghép thêm qua UPRN khi EPC có UPRN | Cần cho £/m² và AVM |
| AVM (giai đoạn 3) | LightGBM / mô hình hedonic, huấn luyện offline, xuất bảng ước tính theo postcode × loại nhà × số phòng | Không suy luận realtime |
| Điều phối job | GitHub Actions cron → Dagster | |
| Cache | ISR + CDN; Upstash Redis | |
| Auth | Better Auth (magic link + Google), chỉ cho watchlist | |
| Email | Resend | |
| AI | Claude API (`claude-haiku-5-5`) cho tóm tắt và nội dung đa ngôn ngữ, có cache | |
| Quảng cáo | **AdSense + CMP chứng nhận IAB TCF v2.2** (bắt buộc với traffic UK/EEA) | |
| Analytics | Plausible/Umami + Google Search Console | |
| Giám sát | Sentry + giám sát lịch chạy ETL | |
| Hosting | Web: Vercel hoặc Coolify trên Hetzner. DB: Hetzner (tự quản) hoặc Supabase/Neon | |

### 5.2 Monorepo

```
zonecheck/
├── apps/web/
│   ├── app/[locale]/[market]/[level]/[slug]/page.tsx     # trang khu vực
│   ├── app/[locale]/[market]/school/[id]/ · station/[id]/
│   ├── app/[locale]/[market]/compare/ · where-to-live/ · rankings/ · tools/
│   ├── app/api/search · api/tiles · api/watchlist
│   ├── messages/en.json (+ các ngôn ngữ sau)
│   └── components/{report, map, ads, tools}/*
├── packages/core · db · ui · markets/uk · (markets/us, markets/fr về sau)
├── etl/{common, markets/uk, transforms, models/avm, tiles}
├── infra/ (docker-compose: postgis, redis)
└── PLAN.md
```

### 5.3 Schema

> **Bản chi tiết và chính thức:** [erd/schema.sql](erd/schema.sql) (80 bảng, 7 schema, comment đầy đủ) và sơ đồ [erd/index.html](erd/index.html). Phần dưới đây chỉ là tóm tắt ban đầu.

```sql
-- ===== Danh mục =====
market(code PK, currency, default_locale, config jsonb)
geo_level(market, code, rank, searchable, PK(market, code))
data_source(id PK, market, name, url, licence, attribution, last_fetched_at,
            data_period_end, terms_notes)

-- ===== Địa lý =====
geo_area(id PK, market, level, code, slug, name, name_i18n jsonb,
         geom MultiPolygon 4326, centroid Point 4326, population int,
         active bool, replaced_by bigint, index_status text, attrs jsonb,
         UNIQUE(market, level, code))            -- GiST(geom), GiST(centroid), GIN(trgm name)
geo_area_link(child_id, parent_id, weight real, PK(child_id, parent_id))
geo_alias(market, kind, value, area_id)          -- postcode đã ngừng dùng → postcode/sector mới

-- ===== Chỉ số =====
metric(id PK, market, category, unit, direction smallint, native_level,
       comparable_scope, source_id, i18n_key, is_estimate bool, sensitive bool, min_sample int)
metric_value(area_id, metric_id, period date, value float8, sample_size int,
             percentile real, suppressed bool,
             PK(area_id, metric_id, period)) PARTITION BY LIST (metric_id)
metric_latest                                    -- materialized view
area_score(area_id, persona, category, score, coverage, computed_at)

-- ===== Điểm và vùng =====
poi(id PK, market, type, external_id, name, name_i18n, geom Point, attrs jsonb, source_id,
    UNIQUE(market, type, external_id))           -- trường (URN), ga (CRS), GP (ODS)...
hazard_zone(id PK, market, type, level, geom MultiPolygon, attrs jsonb, source_id)
                                                 -- lũ, radon, mỏ than, conservation, SSSI...

-- ===== Bảng riêng của UK =====
uk_price_paid(tx_id uuid PK, price int, date date, postcode text, property_type char(1),
              new_build bool, tenure char(1), paon text, saon text, street text,
              ppd_category char(1), uprn bigint, epc_floor_area real, epc_rooms int,
              geom Point)
uk_crime(id text, month date, crime_type text, lsoa_code text, geom Point, outcome text)
              PARTITION BY RANGE (month)
uk_epc_agg(area_id, period, band_dist jsonb, median_floor_area, heating_mix jsonb)
uk_avm(postcode, property_type, bedrooms, estimate_low, estimate_mid, estimate_high,
       confidence, model_version)

-- ===== Người dùng và nội dung =====
watchlist(user_id, area_id, persona, alert_prefs, created_at)
alert_event(id, area_id, kind, payload, period, created_at)
area_summary(area_id, locale, persona, data_version, body, created_at)
user_review(...)                                 -- giai đoạn 3, có kiểm duyệt
data_feedback(...)
```

### 5.4 Pipeline ETL

```
fetch (lưu bản gốc + checksum lên R2) → validate (schema, số dòng ±20%, khoảng giá trị)
→ stage (Parquet/DuckDB) → transform (chuẩn hóa postcode, gắn LSOA, ghép PPD↔EPC)
→ load (COPY vào staging) → aggregate (mọi cấp, ẩn khi mẫu nhỏ: ví dụ giá trung vị cần ít nhất 5 giao dịch)
→ percentile/score → swap staging ↔ live → refresh MV → revalidateTag('market:uk')
→ cập nhật index_status → sinh alert_event → sitemap
```

**Lịch:**

| Tần suất | Nguồn |
|---|---|
| Hằng ngày | GIAS, NaPTAN, FSA, cảnh báo lũ (live, cache) |
| Hằng tháng | Price Paid, police.uk, EPC, Ofsted, UK HPI, PIPR, NHS |
| Theo quý / 2 lần năm | ONSPD, OS Open Names/UPRN, Ofcom, nhà trẻ |
| Hằng năm | Kết quả thi DfE, Census/IoD (khi có bản mới), income, PCM, HadUK-Grid, VOA, council tax, Journey Time |
| Theo đợt | EA flood, noise, radon, mỏ than, Natural England, planning data |

### 5.5 Hiệu năng, SEO, quảng cáo

- **ISR:** build sẵn district, sector, town, LAD, các trường lớn (khoảng 20.000 trang). Phần còn lại render khi có yêu cầu đầu tiên rồi cache. Revalidate theo tag khi ETL chạy xong.
- **Một truy vấn mỗi trang:** hàm SQL `get_area_report(area_id, persona)` trả về JSON. Mục tiêu dưới 50 ms.
- **Bản đồ:** PMTiles tĩnh cho choropleth (LSOA/MSOA/LAD), điểm tội phạm, POI, vùng rủi ro.
- **SEO:**
  - Sitemap chia theo market × locale × level, `lastmod` theo ngày cập nhật dữ liệu.
  - JSON-LD: `Place`, `BreadcrumbList`, `Dataset`, `FAQPage`, `School`.
  - Liên kết nội bộ: postcode → sector → district → town → LAD. Trường ↔ khu. Khu ↔ khu lân cận.
  - Chính sách index dần (mục 3.3). Postcode đã ngừng dùng: 301 sang postcode thay thế hoặc sector.
  - Nội dung có thể dẫn link: xếp hạng hằng tháng ("10 khu an toàn nhất Manchester"), báo cáo dữ liệu theo quý gửi cho báo địa phương.
  - **Chống AI Overviews:** ưu tiên công cụ tương tác (so sánh, tìm ngược, máy tính, bản đồ). Trình bày dữ liệu có cấu trúc rõ, dễ được AI trích dẫn (có thương hiệu + link).
- **AdSense:**
  - CMP chứng nhận TCF v2.2 (ví dụ CMP "Privacy & messaging" của Google), tuân thủ UK GDPR/PECR (nút từ chối ngang hàng).
  - Vị trí: 1 sau phần đầu, 1 giữa mỗi 2–3 section, 1 sticky sidebar trên desktop. Không đặt sát bản đồ hay nút bấm.
  - **Đặt sẵn khung kích thước** cho quảng cáo, lazy-load quảng cáo dưới màn hình đầu. Giữ Core Web Vitals: LCP dưới 2,5 giây, CLS dưới 0,1, INP dưới 200 ms.
  - **Trang RPM cao:** máy tính stamp duty, khả năng vay, chi phí chuyển nhà, thuê hay mua, EPC/chi phí năng lượng. Liên kết nội bộ mạnh từ trang khu vực sang các trang này.
  - Đo RPM theo loại trang và vai trò để tối ưu bố cục.

---

## 6. Lộ trình

> Giả định 1–2 developer full-time. Thời gian là ước lượng.

### Giai đoạn 0: Nền tảng (tuần 1–2)
- [ ] Monorepo (pnpm + Turborepo), Next.js 16, Tailwind, shadcn, next-intl (EN, kiến trúc sẵn đa ngôn ngữ)
- [ ] Docker Compose: PostGIS + Redis. Drizzle schema lớp chung. `MarketAdapter` + market `uk`
- [ ] ETL khung: fetch, checksum, validate, COPY, đăng ký nguồn (`terms_notes`)
- [ ] Nạp ONSPD (hoặc Code-Point Open), ranh giới OA/LSOA/MSOA/LAD, OS Open Names → tìm kiếm postcode và địa danh chạy end-to-end
- [ ] **Rà soát giấy phép:** ONSPD, EPC, EA NaFRA2, radon, Coal Authority, CCOD/OCOD, Geolytix

### Giai đoạn 1: MVP England & Wales (tuần 3–10)
- [ ] ETL: Price Paid, UK HPI, EPC (+ ghép PPD↔EPC → £/m²), PIPR, police.uk, GIAS + Ofsted (cả 2 mô hình) + DfE results, IoD 2025 + WIMD, Census 2021, income MSOA, EA flood (+ NRW), Defra PCM, NaPTAN, Journey Time, Ofcom broadband, NHS, FSA, OS Greenspace
- [ ] Metric mọi cấp, ẩn khi mẫu nhỏ, percentile, 8 nhóm điểm × 6 vai trò
- [ ] Trang: postcode, sector, district, town, LAD, region, trường học, ga, so sánh, xếp hạng
- [ ] Công cụ: stamp duty (England/Wales), khả năng vay, chi phí chuyển nhà
- [ ] Bản đồ MapLibre + PMTiles
- [ ] `/sources`, `/methodology`, `/glossary`, nút báo lỗi dữ liệu
- [ ] SEO: sitemap, JSON-LD, chính sách index dần, chuyển hướng postcode đã ngừng dùng
- [ ] **AdSense + CMP**, Plausible, Search Console, Sentry
- [ ] Trang pháp lý: privacy, cookies, terms, disclaimer
- **Tiêu chí ra mắt:** mọi postcode ở E&W có trang (index có chọn lọc), mọi chỉ số có nguồn và ngày, LCP dưới 2,5 giây kể cả có quảng cáo

### Giai đoạn 2: Lấp khoảng trống dữ liệu + tăng traffic (tháng 3–4)
- [ ] Radon, mỏ than, bãi rác lịch sử, SSSI/AONB/National Park, khí hậu (HadUK-Grid), tiếng ồn, di động
- [ ] Ràng buộc quy hoạch (planning.data.gov.uk + Historic England), council tax, PTAL/TfL, nhà trẻ
- [ ] Ước tính giá thuê theo MSOA (gắn nhãn ước tính)
- [ ] Tìm ngược: ngân sách mua/thuê + ưu tiên → bản đồ mức phù hợp
- [ ] Tài khoản, watchlist, email cảnh báo hằng tháng (giao dịch mới, tội phạm, Ofsted)
- [ ] Tóm tắt AI theo khu × vai trò (gắn nhãn, chỉ dựa trên số liệu)
- [ ] PDF, link chia sẻ, ảnh OG động
- [ ] **Mở 2–3 ngôn ngữ đầu tiên** (chọn theo dữ liệu) + glossary và nội dung "moving to the UK"

### Giai đoạn 3: Khác biệt sâu (tháng 5–8)
- [ ] **AVM** (định giá nhanh, có khoảng tin cậy)
- [ ] Isochrone / thời gian đi làm (BODS GTFS + rail, r5/OpenTripPlanner, tính sẵn ma trận LSOA → các trung tâm)
- [ ] Review cư dân (kiểm duyệt), khu tuyển sinh (khoảng 30 LA lớn), nhà thuộc sở hữu công ty (cấp khu), đơn xin cấp phép quy hoạch (độ phủ có sẵn)
- [ ] Extension cho Rightmove, Zoopla, OnTheMarket
- [ ] **Scotland** (Police Scotland, SIMD, Census 2022, RoS small-area stats, SEPA) và **Bắc Ireland**
- [ ] Thêm ngôn ngữ

### Giai đoạn 4: Market 2 là 🇺🇸 Mỹ (tháng 9+)
- [ ] `markets/us` + ETL (Phụ lục B). Dùng lại toàn bộ giao diện, hạ tầng, quảng cáo
- [ ] Trang theo place (thành phố), ZIP, county. Tự tính điểm trường từ EdFacts

### Giai đoạn 5: Market 3 là 🇫🇷 Pháp (khi có người kiểm tra nội dung tiếng Pháp)
- [ ] Phụ lục C (DVF, SSMSI, IVAL/IVAC, Géorisques…) + tuân thủ điều kiện DVF

---

## 7. Pháp lý và tuân thủ (UK)

- **OGL:** ghi nguồn đúng cú pháp trên mỗi trang và ở `/sources`. Không ngụ ý được nhà nước bảo trợ.
- **Quyền bên thứ ba:** ONSPD và các trường địa chỉ trong EPC/PPD có thể có quyền Royal Mail/OS. Đọc kỹ điều khoản, ưu tiên hiển thị số liệu tổng hợp.
- **ODbL (OSM):** ghi "© OpenStreetMap contributors". Không phát hành lại database dẫn xuất.
- **UK GDPR / PECR (ICO):**
  - CMP có nút từ chối ngang hàng. Quảng cáo cá nhân hóa chỉ khi người dùng đồng ý.
  - Chính sách bảo mật. Quy trình xử lý yêu cầu xóa hoặc ẩn dữ liệu trong 1 ngày làm việc.
  - **Không làm trang cho từng ngôi nhà.** Cấp nhỏ nhất là postcode. Giao dịch chỉ hiển thị số nhà và đường, không có tên người.
- **AVM:** ghi rõ "ước tính tự động, không phải định giá chuyên nghiệp (RICS)", hiển thị khoảng giá và độ tin cậy.
- **Không phân biệt đối xử (Equality Act):** dữ liệu dân tộc, tôn giáo chỉ hiển thị dạng mô tả, **không đưa vào điểm số và bộ lọc**.
- **Tội phạm:** ghi chú vị trí đã được ẩn danh, không gắn tội phạm với một địa chỉ cụ thể.
- **Miễn trừ trách nhiệm:** không thay thế conveyancing search, khảo sát nhà, tư vấn tài chính hay bảo hiểm.
- **Nội dung AI:** gắn nhãn, chỉ dựa trên số liệu trong DB, có nút báo sai.

---

## 8. Doanh thu (AdSense)

### 8.1 Kịch bản (ước tính rất thô, chỉ để tham chiếu)

| Mốc | Trang được index | Lượt truy cập/tháng | Pageview/tháng | RPM UK (giả định) | Doanh thu/tháng |
|---|---|---|---|---|---|
| Tháng 6 | khoảng 50.000 | 20.000–50.000 | 60.000–150.000 | $6–12 | $400–1.800 |
| Tháng 12 | khoảng 150.000 | 60.000–150.000 | 180.000–450.000 | $6–15 | $1.100–6.800 |
| Tháng 24 (UK + US) | 500.000+ | 300.000–700.000 | 0,9–2 triệu | $8–15 | $7.000–30.000 |

*Mốc tham chiếu từ lưu lượng đối thủ: CrystalRoof khoảng 300.000 lượt/tháng. AI Overviews làm CTR giảm khoảng 35–60% với truy vấn tìm thông tin, nên công cụ tương tác là yếu tố sống còn.*

### 8.2 Tăng RPM
- Máy tính tài chính (stamp duty, mortgage) và trang thuê hay mua: quảng cáo ngành tài chính và nhà đất trả giá cao.
- Khi đủ traffic: chuyển sang Ezoic / Mediavine / Raptive.
- Affiliate gắn nhãn rõ (môi giới vay, bảo hiểm nhà, chuyển nhà, broadband), không ảnh hưởng điểm số.

### 8.3 Nguồn thu tương lai
API/widget B2B cho môi giới và trang tin đăng, gói không quảng cáo, report PDF nâng cao. Thiết kế sẵn bảng `plan`/`entitlement` + feature flags.

---

## 9. Chi phí vận hành

| Hạng mục | Tiết kiệm | Managed |
|---|---|---|
| Web | Vercel $0–20 hoặc Coolify trên Hetzner | Vercel Pro $20+ |
| Postgres/PostGIS (khoảng 50 GB) | Hetzner khoảng €30–40 | Supabase/Neon $50–100 |
| R2 (bản gốc + PMTiles) | khoảng $2–5 | |
| Redis, email | Free tier | $20 |
| AI | Haiku: tóm tắt tính sẵn khoảng 20.000 trang lớn (chi phí một lần thấp), còn lại sinh khi có yêu cầu | |
| CMP | Google CMP miễn phí | |
| **Tổng** | **khoảng $40–80/tháng** | **khoảng $120–200/tháng** |

---

## 10. KPI

- **SEO:** số trang được index, lượt hiển thị và click (Search Console), số từ khóa top 10, CTR theo loại trang.
- **Doanh thu:** pageview, RPM theo loại trang, số trang/phiên, thời gian trên trang.
- **Sản phẩm:** tỷ lệ dùng so sánh, tìm ngược, công cụ, đổi vai trò; số đăng ký watchlist.
- **Dữ liệu:** độ trễ so với nguồn, độ phủ chỉ số theo khu, số báo lỗi, **tỷ lệ đạt ngang ma trận đối thủ** (mục 1.3).
- **Mục tiêu 6 tháng:** 50.000 trang được index, 50.000 lượt truy cập/tháng, Core Web Vitals đạt chuẩn ở mọi template.

---

## 11. Rủi ro

| Rủi ro | Mức độ | Cách giảm thiểu |
|---|---|---|
| CrystalRoof và các trang khác đã chiếm SEO | Cao | Miễn phí mọi thứ đối thủ thu tiền, công cụ tương tác, trang trường/ga/công cụ, chất lượng trang, index dần |
| AI Overviews giảm click | Cao | Công cụ tương tác, nội dung có cấu trúc để được AI trích dẫn, xây kênh ngoài Google (báo địa phương, Reddit, cộng đồng) |
| Trang mỏng (1,4 triệu postcode) | Cao | Chính sách index dần theo độ khác biệt dữ liệu |
| Giấy phép (ONSPD, EA NaFRA2, radon, Coal Authority) | Trung bình | Rà soát ở giai đoạn 0. Dự phòng bằng Code-Point Open. Ghi kết quả vào `terms_notes` |
| Nguồn dữ liệu thay đổi (định dạng, Ofsted đổi mô hình) | Trung bình | Validate, lưu bản gốc, cảnh báo khi ETL lỗi, model linh hoạt |
| AVM sai lệch | Trung bình | Hiển thị khoảng giá + độ tin cậy, backtest, ẩn khi độ tin cậy thấp |
| RPM thấp hơn giả định | Trung bình | Trang công cụ tài chính, tối ưu bố cục, chuyển sang mạng quảng cáo cao cấp |

---

## 12. Việc cần làm ngay

1. **Kiểm tra lượng tìm kiếm** (bản dùng thử Semrush/Ahrefs) cho các mẫu: "{postcode} crime", "is {town} a nice place to live", "{town} house prices", "{school} ofsted", "stamp duty calculator" → ưu tiên template.
2. Chọn tên miền (`.co.uk` cho UK hoặc `.com` cho đa quốc gia), kiểm tra trùng thương hiệu (UKIPO).
3. Rà soát giấy phép: ONSPD, EPC, EA NaFRA2, radon, Coal Authority.
4. Đăng ký API key cho EPC.
5. Dựng monorepo + PostGIS, nạp ONSPD + ranh giới, tìm kiếm postcode end-to-end.
6. Wireframe trang postcode/sector + trang trường (mobile-first, có khung quảng cáo).
7. Viết bản đầu `/methodology`.

---

## 13. Câu hỏi còn mở

- Một domain `.com` đa quốc gia hay domain riêng cho từng nước (`.co.uk`)? Đề xuất: `.com` + đường dẫn `/uk`, `/us`, `/fr` để gom uy tín SEO về một chỗ.
- 2–3 ngôn ngữ đầu tiên cho UK là gì? (Quyết định ở giai đoạn 2 theo dữ liệu.)
- Có làm review cư dân không? (Rủi ro kiểm duyệt, phỉ báng.)
- Tự host DB hay dùng managed?

---

## Phụ lục A: Nguồn tham khảo (UK)

**Đối thủ**
- CrystalRoof: https://crystalroof.co.uk/ · lưu lượng: https://www.similarweb.com/website/crystalroof.co.uk/
- StreetCheck (đã sáp nhập): https://www.semrush.com/website/streetcheck.co.uk/overview/ · https://housecheckup.co.uk/answers/what-happened-to-streetcheck
- PostcodeCheck: https://postcodecheck.co.uk/ · Home-Checker: https://home-checker.uk/
- PropertyData: https://propertydata.co.uk/pricing · https://propertydata.co.uk/data-fields
- Area360: https://chromewebstore.google.com/detail/fmkcdnhkhfnbaomihadamoendclmjglb
- Chimnie: https://digitalplanningdirectory.org/providers/chimnie
- Nhóm mới: https://housecheckup.co.uk/ · https://areaview.co.uk/faq · https://www.knowmypostcode.co.uk/ · https://www.nestscope.uk/ · https://movecompass.co.uk/tools · https://www.homethink.co.uk/tools/postcode-explorer

**Dữ liệu**
- Price Paid: https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads
- data.police.uk: https://data.police.uk/docs/method/crime-street/ · https://data.police.uk/about
- ONSPD: https://ckan.publishing.service.gov.uk/dataset/ons-postcode-directory-may-2026
- EPC: https://epc.opendatacommunities.org
- IoD 2025: https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025
- Ofcom: https://www.ofcom.org.uk/phones-and-broadband/coverage-and-speeds/data
- Ofsted report cards: https://thirdspacelearning.com/blog/ofsted-report-cards/
- EA NaFRA2: https://www.unda.co.uk/news/understanding-and-managing-flood-risk-with-nafra2/
- Noise Round 4: https://www.gov.uk/government/publications/strategic-noise-mapping-2022
- Defra PCM: https://www.data.gov.uk/dataset/defra-national-pollution-climate-mapping-pcm-modelled-background-concentrations
- Planning data: https://www.planning.data.gov.uk/docs

---

## Phụ lục B: Market 2 là 🇺🇸 Mỹ (tóm tắt)

- **Dữ liệu (public domain liên bang):**
  - Census ACS (block group/tract/ZCTA/place)
  - FBI Crime Data Explorer (theo sở cảnh sát, năm 2024 phủ 95,6% dân số; NIBRS 87%)
  - NCES CCD + EdFacts (điểm thi theo trường)
  - FEMA National Risk Index + NFHL (lũ), EPA National Walkability Index (block group), EPA AirNow
  - FCC National Broadband Map, HUD Fair Market Rents/SAFMR (ZIP)
  - FHFA HPI (ZIP), BEA Regional Price Parities, NOAA (khí hậu)
  - GTFS, open data tội phạm theo điểm của khoảng 100 thành phố lớn
  - Zillow ZHVI/ZORI, Redfin Data Center: *điều khoản dùng thương mại chưa rõ, cần kiểm tra*
- **Thiếu so với đối thủ:** xếp hạng GreatSchools (tự tính điểm từ EdFacts), mô hình tội phạm cấp khu của NeighborhoodScout, review Niche, chỉ số chi phí sinh hoạt C2ER, giá giao dịch ở khoảng 12 bang không công khai giá.
- **Đối thủ:** Niche (khoảng 7 triệu lượt/tháng), City-Data (khoảng 2 triệu), NeighborhoodScout (khoảng 600.000), BestPlaces (khoảng 330.000), AreaVibes (khoảng 170.000), cùng nhóm mới (ZipScore, StreetScore, NeighborScope, BestNeighborhood.org), Zillow/Redfin/Realtor.
- **Mục tiêu:** vượt nhóm trang sống bằng quảng cáo (BestPlaces, AreaVibes) bằng nền tảng đã kiểm chứng ở UK.

## Phụ lục C: Market 3 là 🇫🇷 Pháp (tóm tắt từ bản 2)

- **Dữ liệu:**
  - DVF (từng giao dịch, Licence Ouverte; **cấm nhận diện và cấm index dữ liệu giao dịch**; thiếu Alsace-Moselle và Mayotte)
  - Carte des loyers (commune), SSMSI (commune, khoảng 46% ô bị ẩn)
  - IPS/IVAL/IVAC, INSEE IRIS + Filosofi 200 m, BPE
  - Géorisques (có radon), ARCEP, DPE ADEME, REI, APL DREES, BAN/Géoplateforme
- **Đối thủ:** Habity (107 chỉ số, mới), bien-dans-ma-ville (khoảng 35.000 commune + 2.000 khu phố, khoảng 250.000 lượt/tháng), ville-ideale (khoảng 300.000–380.000), JDN/L'Internaute, Ville de Rêve, GoodPlaceTo.Live, MeilleursAgents/SeLoger.
- **Bối cảnh:** AI Overviews ra mắt ở Pháp ngày 22/7/2026. Lợi thế khi vào Pháp: tiếng Anh cho người nước ngoài mua nhà, chi tiết dưới cấp commune.

## Phụ lục D: Chấm điểm 10 thị trường

Thang 1–5, 5 là tốt nhất. Các cột "Cạnh tranh", "Chi phí ETL", "SEO dễ chiếm" cho điểm cao khi việc đó **dễ** hoặc **rẻ**. **Dữ liệu so với đối thủ tính hệ số 2.**

| Nước | Dữ liệu so với đối thủ (×2) | Giấy phép | Cạnh tranh | RPM × quy mô | Chi phí ETL | SEO dễ chiếm | Ngôn ngữ phù hợp đội ngũ | **Tổng** |
|---|---|---|---|---|---|---|---|---|
| 🇬🇧 **Anh** | 4 (8) | 4 | 2 | 4 | 5 | 2 | 5 | **30** |
| 🇺🇸 Mỹ | 3 (6) | 5 | 2 | 5 | 2 | 2 | 5 | **27** |
| 🇫🇷 Pháp | 4 (8) | 3 | 3 | 3 | 4 | 3 | 2 | **26** |
| 🇳🇱 Hà Lan | 4 (8) | 4 | 1 | 2 | 5 | 2 | 2 | **24** |
| 🇨🇦 Canada | 2 (4) | 3 | 3 | 3 | 2 | 3 | 5 | **23** |
| 🇦🇺 Úc | 2 (4) | 3 | 2 | 3 | 2 | 2 | 5 | **21** |
| 🇯🇵 Nhật | 3 (6) | 3 | 2 | 3 | 3 | 2 | 1 | **20** |
| 🇰🇷 Hàn | 3 (6) | 3 | 1 | 2 | 4 | 1 | 1 | **18** |
| 🇩🇪 Đức | 2 (4) | 2 | 3 | 3 | 1 | 3 | 2 | **18** |
| 🇮🇹 Ý | 1 (2) | 3 | 3 | 2 | 3 | 3 | 2 | **18** |

**Độ vững:** nếu tính RPM × quy mô hệ số 2 hoặc 3, Anh vẫn đứng đầu (34 so với Mỹ 32; 38 so với Mỹ 37).

**Lưu lượng tham chiếu** của các trang dẫn đầu mảng báo cáo khu vực (ước tính Semrush/Similarweb, 2026): CrystalRoof khoảng 300.000 · ville-ideale khoảng 300.000–380.000 · bien-dans-ma-ville khoảng 250.000 · AlleCijfers khoảng 300.000 · BestPlaces khoảng 330.000 · AreaVibes khoảng 170.000 · NeighborhoodScout khoảng 600.000 · City-Data khoảng 2 triệu · Niche khoảng 7 triệu.

*Điểm số là đánh giá dựa trên nghiên cứu trong phiên làm việc này. Lượng tìm kiếm theo từ khóa chưa được đo. Nếu (lượng tìm kiếm × RPM) của Mỹ vượt Anh hơn khoảng 3 lần, nên cân nhắc đảo thứ tự Anh và Mỹ.*
