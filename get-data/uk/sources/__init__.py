"""Danh sách tool cào dữ liệu UK. Thứ tự = thứ tự chạy khi `python -m uk all`."""
from .epc import EpcDomestic
from .manual import NhsGpPatients, OfcomConnectedNations
from .rofsw import EaRofsw, NrwRofsw
from .extra2 import EXTRA2_SOURCES
from .schools_perf import DfePerformance, DfeSchoolProfile
from .wales import WalesSchools, Wimd
from .rail import OrrStationUsage
from .council_tax import CouncilTax
from .zones import ZONE_SOURCES, PlanningData, PlanningDataExtra
from .environment import BGS_SOURCES, COAL_SOURCES, EA_SOURCES, NRW_SOURCES
from .noise import DefraNoise
from .extra import EXTRA_SOURCES
from .classification import GeodsOac
from .police_history import PoliceHistory
from .planning_apps import LondonPlanning
from .amenities import DefraPcm, EaFloodAreas, Fsa, NhsOds, Naptan
from .geography import BOUNDARY_SOURCES, OS_SOURCES, Onspd
from .housing import ONS_SOURCES, PricePaid, UkHpi
from .social import GOVUK_SOURCES, Census2021, Gias, Ofsted, Police

SOURCES = [
    # Địa lý
    Onspd(), *OS_SOURCES, *BOUNDARY_SOURCES,
    # Nhà đất
    PricePaid(), UkHpi(), *ONS_SOURCES, EpcDomestic(), CouncilTax(),
    # An ninh, giáo dục, kinh tế xã hội
    Police(), Gias(), Ofsted(), DfePerformance(), DfeSchoolProfile(), WalesSchools(), Wimd(), Census2021(), *GOVUK_SOURCES,
    # Giao thông, tiện ích, môi trường
    Naptan(), OrrStationUsage(), Fsa(), NhsOds(), DefraPcm(), EaFloodAreas(),
    PlanningData(), *ZONE_SOURCES, EaRofsw(),
    # Lấp khoảng trống so với đối thủ (DATA_GAP_TRACKER.md)
    PlanningDataExtra(), *EA_SOURCES, *NRW_SOURCES, *COAL_SOURCES, *BGS_SOURCES, DefraNoise(), *EXTRA_SOURCES,
    NrwRofsw(), *EXTRA2_SOURCES, GeodsOac(), PoliceHistory(), LondonPlanning(),
    # Tải tay (Cloudflare): uk/manual/fetch.py
    OfcomConnectedNations(), NhsGpPatients(),
]

BY_NAME = {s.name: s for s in SOURCES}
assert len(BY_NAME) == len(SOURCES), "trùng tên source"
