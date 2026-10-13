# Nguồn chặn client tự động (Cloudflare): tải bằng Chrome thật

Ofcom và NHS England Digital chặn mọi client HTTP thường. `fetch.py` mở Chrome đã cài trên máy (Playwright,
có giao diện), qua trang kiểm tra Cloudflare rồi tự tìm và tải bản mới nhất. **Chạy ở máy local**, vì VPS không có màn hình.

```bash
pip install playwright                     # dùng Chrome đã cài, không cần `playwright install`
python3 get-data/uk/manual/fetch.py        # hoặc: fetch.py ofcom / fetch.py nhs
```

| Thư mục | Nguồn | File |
|---|---|---|
| `ofcom/` | Ofcom Connected Nations (báo cáo năm hoặc bản cập nhật Spring/Summer mới nhất) | `YYYYMM_fixed_broadband_coverage*.zip`, `YYYYMM_mobile_coverage*.zip` (cùng kỳ) |
| `nhs_gp_patients/` | Patients Registered at a GP Practice, tháng mới nhất đã công bố | `gp-reg-pat-prac-all-YYYY-MM.zip` |

File đã có thì bỏ qua. Sau khi tải xong:

```bash
source auth_key/vps/vps.env
rsync -az -e "ssh -i auth_key/vps/id_ed25519 -o IdentitiesOnly=yes" get-data/uk/manual/ root@$VPS_HOST:/opt/zonecheck/get-data/uk/manual/
# trên VPS
.venv/bin/python -m uk all --only ofcom_connected_nations,nhs_gp_patients   # đóng gói thành release
.venv/bin/python -m uk load ofcom_connected_nations nhs_gp_patients --cleanup
ZC_METRICS="uk.bb.%" .venv/bin/python -m uk derive rollup && .venv/bin/python -m uk derive percentiles scoring
```

Không dùng file Ofcom "fixed performance": bản theo OA chỉ có tốc độ trung bình trong từng dải tốc độ, không có tốc độ chung.
