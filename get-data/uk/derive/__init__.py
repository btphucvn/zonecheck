"""Bước tính toán từ dữ liệu đã nạp (tổng hợp, phân vị, điểm). Thứ tự trong STEPS = thứ tự chạy khi `derive all`."""
from .access import Access
from .census_shares import CensusShares
from .crime import Crime
from .crime_history import CrimeHistory
from .epc_match import EpcMatch
from .exposure import Exposure
from .hazards import Hazards
from .housing import Housing
from .membership import Membership
from .rollup import Rollup
from .scoring import Percentiles, Scoring
from .streets import Streets

STEPS = [Membership(), Crime(), CrimeHistory(), Housing(), EpcMatch(), Access(), Exposure(), Hazards(), Rollup(), CensusShares(), Percentiles(), Scoring(), Streets()]
STEP_BY_NAME = {s.name: s for s in STEPS}
