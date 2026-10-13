# get-data: tool cào dữ liệu mở

Mỗi nước một thư mục (`uk/`, sau này `us/`, `fr/`). Code dùng chung nằm ở `common/`.

```
get-data/
├── common/              # dùng chung mọi market
│   ├── config.py        # đọc .env / auth_key/vps/vps.env, thư mục dữ liệu
│   ├── http.py          # session có retry, tải file lớn có resume + sha256, lỗi HTTP có đủ ngữ cảnh
│   ├── release.py       # một phiên bản dataset = một thư mục + manifest.json
│   ├── db.py            # ghi ops.etl_run, ops.dataset_release
│   ├── logs.py          # log ra màn hình + file
│   └── sources.py       # helper: gov.uk Content API, ONS, ArcGIS (ONS Geography), OS Downloads API
├── uk/
│   ├── __main__.py      # CLI: python -m uk ...
│   ├── seed.sql         # đăng ký market/licence/data_source/dataset vào DB
│   ├── sources/         # mỗi class = một tool
│   └── data/            # dữ liệu thô tải về (không commit)
├── logs/                # log (không commit)
└── requirements.txt
```

## Chạy

Nên chạy trên VPS (mạng nhanh, đĩa 290 GB). Code đã được triển khai ở `/opt/zonecheck/get-data`.

```bash
./auth_key/vps/ssh.sh
cd /opt/zonecheck/get-data

.venv/bin/python -m uk list                     # các tool + bản mới nhất đã tải
.venv/bin/python -m uk all --dry-run            # chỉ xem phiên bản mới nhất của mọi nguồn
.venv/bin/python -m uk all                      # tải mọi nguồn (bản đã có thì bỏ qua)
.venv/bin/python -m uk police --month 2026-08   # một nguồn, có tuỳ chọn riêng (xem --help)
.venv/bin/python -m uk ppd --mode monthly       # Price Paid: file cập nhật tháng
.venv/bin/python -m uk all --only gias,naptan --force
```

Đồng bộ code từ máy local lên VPS:

```bash
source auth_key/vps/vps.env
rsync -az --exclude data/ --exclude logs/ --exclude __pycache__ --exclude .env --exclude .venv \
  -e "ssh -i auth_key/vps/id_ed25519 -o IdentitiesOnly=yes" get-data/ root@$VPS_HOST:/opt/zonecheck/get-data/
```

Chạy ở local: `pip install -r requirements.txt`, mở `./auth_key/vps/tunnel.sh -f` để ghi DB, rồi `cd get-data && python3 -m uk ...` (Python ≥ 3.9).

## Cách hoạt động

1. `plan()`: hỏi nguồn xem phiên bản mới nhất là gì (rẻ, không tải file lớn).
2. Nếu `uk/data/<source>/<version>/manifest.json` đã có → bỏ qua. `--force` để tải lại.
3. `download()`: tải vào thư mục phiên bản. File lớn tải vào `*.part` và **resume** được nếu đứt.
4. Ghi `manifest.json` (file, url, bytes, sha256) và một dòng `ops.dataset_release`. Mỗi lần chạy có một dòng `ops.etl_run`.

## Nạp vào database

```bash
.venv/bin/python -m uk load all --cleanup      # nạp mọi nguồn theo thứ tự phụ thuộc, xoá file thô SAU KHI commit
.venv/bin/python -m uk load ppd police          # chỉ vài nguồn (vẫn theo thứ tự phụ thuộc)
.venv/bin/python -m uk load gias --force        # nạp lại dù release đã loaded
```

Mỗi nguồn được nạp như sau:
1. Lấy bản tải mới nhất.
2. Kiểm tra các nguồn phụ thuộc đã `loaded` (ví dụ PPD cần ONSPD).
3. Nạp trong **một transaction**, kèm kiểm tra số dòng: lệch là rollback toàn bộ và giữ nguyên file thô.
4. Thành công thì `ops.dataset_release.status = 'loaded'` rồi commit.
5. Chỉ sau bước 4 mới xoá file thô (nếu có `--cleanup`), và giữ lại `manifest.json`.

Dữ liệu trung gian nằm trong schema `stage_uk` (bảng UNLOGGED, xoá sau khi nạp). Log từng bước SQL kèm số dòng và thời gian.
Lỗi khi nạp được ghi ở `uk/data/<source>/<version>/last_load_error.txt` và `ops.etl_run` (`job_name = 'load:<source>'`).

Lưu ý hiệu năng (đã gặp): bảng stage phải được `ANALYZE` và có index trên cột join. Tránh `NOT EXISTS` lồng trên bảng stage lớn,
và join `core.metric_value` luôn kèm `market_code` để dùng được khoá chính.
**Không `UPDATE` bảng rồi `CREATE INDEX` trong cùng transaction**: index bị đánh dấu `indcheckxmin` nên transaction đó
không dùng được nó. Thay bằng `CREATE TABLE ... AS SELECT` (đã gặp ở PCM: 432 giây, sau khi sửa còn 10 giây).
**Nạp hàng chục triệu dòng**: tạm bỏ khoá ngoại rồi thêm lại (`ctx.without_fks`). Kiểm tra FK theo từng dòng chạy hàng giờ.
**Giao cắt điểm–polygon với polygon lớn** (vùng lũ dọc sông): `ST_Subdivide(geom, 255)` vào bảng tạm có GiST trước, nhanh hơn ~180 lần.
**`ST_DWithin` trên geography không dùng index geometry**: lọc thô bằng geometry (độ) trước rồi mới lọc chính xác bằng geography.
**Diện tích**: dùng `ST_Area(ST_Transform(geom, 27700))` (BNG). `ST_Area(geography)` lỗi "area < 0" với vài polygon.

Lưu ý kiểm tra hình học: kiểm tra "trong khung UK" phải dùng `ST_CoveredBy`, không dùng `ST_Intersects`. Đã gặp một polygon EA
hỏng có khung bao 360° × 180° (trùm cả địa cầu) lọt qua `ST_Intersects`, làm "100% dân nằm trong Flood Zone 2".
Mọi tỉ lệ hoặc tổng nên có **cả cận dưới và cận trên** hợp lý.

## Dọn file thô sau khi nạp DB

```bash
.venv/bin/python -m uk cleanup         # liệt kê bản có thể xoá
.venv/bin/python -m uk cleanup --yes   # xoá thật
```

Chỉ xoá file của release mà `ops.dataset_release.status` là `loaded` hoặc `published`. Bản còn `fetched`, tức chưa nạp, không bị đụng tới.
`manifest.json` (sha256 + URL nguồn + `raw_deleted_at`) được giữ lại để truy vết và để không tải lại cùng phiên bản. Muốn tải lại thì dùng `--force`.
Bước nạp (loader, sẽ viết sau) đặt status `loaded` khi nạp xong rồi gọi cleanup.

## Log và xử lý lỗi

| Nơi | Nội dung |
|---|---|
| màn hình | INFO: tiến độ |
| `logs/uk-YYYY-MM-DD.log` | DEBUG: mọi request, status, retry, traceback đầy đủ |
| `logs/uk-errors.log` | chỉ ERROR, cộng dồn qua các lần chạy |
| `uk/data/<source>/<version>/last_error.txt` | lỗi gần nhất của phiên bản đó: args, file đã tải xong, traceback. Tự xoá khi chạy lại thành công |
| `ops.etl_run` | `status = failed`, `error_message` = traceback |

Lỗi HTTP ghi kèm method, URL (và chuỗi redirect), status, vài header và đoạn body (HTML đã bỏ tag).
4xx không retry. 5xx/429/lỗi mạng retry có backoff. Lỗi ở một nguồn không dừng `all`. Exit code khác 0 nếu có nguồn lỗi.

```bash
tail -50 logs/uk-errors.log
./auth_key/vps/psql.sh -c "select id, job_name, status, started_at, left(error_message, 300) from ops.etl_run where status <> 'succeeded' order by id desc limit 10"
```

## Thêm nguồn mới

1. Viết class kế thừa `Source` trong `uk/sources/*.py` (`name`, `dataset_id`, `plan`, `download`, tuỳ chọn `add_arguments`).
2. Thêm vào `SOURCES` trong `uk/sources/__init__.py`.
3. Thêm dòng `ops.dataset` (và `ops.data_source` nếu là nhà cung cấp mới) vào `uk/seed.sql`, chạy `./auth_key/vps/psql.sh < get-data/uk/seed.sql`.
