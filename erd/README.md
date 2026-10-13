# erd/: Mô hình dữ liệu ZoneCheck

| File | Vai trò |
|---|---|
| `schema.sql` | **Nguồn chuẩn** của database: DDL đầy đủ (PostgreSQL 16+ / PostGIS 3.4+), mọi schema/bảng/cột đều có `COMMENT ON`. |
| `index.html` | Sơ đồ ERD theo nhóm + tài liệu từng bảng/cột. **Sinh tự động**, không sửa tay. Mở trực tiếp bằng trình duyệt (cần Internet để tải Mermaid từ CDN). |
| `build_erd.py` | Đọc `schema.sql` và sinh `index.html`. Báo lỗi nếu bảng/cột thiếu comment hoặc khoá ngoại trỏ tới bảng không tồn tại. |
| `erd_template.html` | Giao diện của `index.html` (CSS/JS). |

## Cập nhật

```bash
# 1. Sửa erd/schema.sql
# 2. Sinh lại trang
python3 erd/build_erd.py
# 3. Kiểm tra trên database thật (cần PostGIS)
createdb zonecheck_dev && psql -v ON_ERROR_STOP=1 -f erd/schema.sql zonecheck_dev
```

## Quy ước khi sửa `schema.sql` (để script đọc được)

- Nhóm bảng trên sơ đồ: `-- @domain <key> | <Tiêu đề> | <mô tả>` đặt trước các bảng của nhóm.
- `CREATE TABLE schema.ten (` trên một dòng, **mỗi cột một dòng**, dấu `)` đóng bảng ở **đầu dòng**.
- Ràng buộc cấp bảng (`PRIMARY KEY (...)`, `FOREIGN KEY (...) REFERENCES ...`, `UNIQUE (...)`, `CHECK (...)`) mỗi cái một dòng.
- Mỗi bảng và mỗi cột phải có `COMMENT ON TABLE/COLUMN ... IS '...';`. Script sẽ dừng nếu thiếu.
- Index một dòng: `CREATE [UNIQUE] INDEX ten ON schema.bang [USING method] (...) [WHERE ...];`. Không đặt tên index trùng tên bảng trong cùng schema, và không dùng từ khoá dành riêng (ví dụ `session_user`).

## Mở rộng

- **Thêm market mới (ví dụ US):** thêm dòng vào `core.market`, `core.geo_level`, `ops.data_source`/`ops.dataset`, `core.metric` (là dữ liệu, không phải migration). Tạo `CREATE TABLE core.metric_value_us PARTITION OF core.metric_value FOR VALUES IN ('us');` và schema `mkt_us` cho dữ liệu thô đặc thù.
- **Thêm chỉ số:** chỉ cần thêm dòng vào `core.metric` + `core.metric_translation`. Không đổi schema.
- **Thêm ngôn ngữ:** thêm dòng vào `core.locale`, `core.market_locale` và các bảng `*_translation`.
- **Năm mới cho dữ liệu tội phạm:** ETL tạo partition `mkt_uk.crime_incident_<năm>` trước tháng 1. Partition `_default` phải luôn rỗng.
- **Migration:** khi bắt đầu code, chuyển `schema.sql` thành migration đầu tiên (Drizzle/dbmate). Từ đó mỗi thay đổi là một migration mới, đồng thời cập nhật `schema.sql` và chạy lại `build_erd.py`.
