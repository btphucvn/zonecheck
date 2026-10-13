"""Bước tính toán từ dữ liệu đã nạp (tổng hợp, phân vị, điểm). Thứ tự trong STEPS = thứ tự chạy khi `derive all`."""
from .access import Access
from .crime import Crime
from .epc_match import EpcMatch
from .exposure import Exposure
from .hazards import Hazards
from .housing import Housing
from .membership import Membership
from .rollup import Rollup
from .scoring import Percentiles, Scoring
from .streets import Streets

STEPS = [Membership(), Crime(), Housing(), EpcMatch(), Access(), Exposure(), Hazards(), Rollup(), Percentiles(), Scoring(), Streets()]
STEP_BY_NAME = {s.name: s for s in STEPS}
