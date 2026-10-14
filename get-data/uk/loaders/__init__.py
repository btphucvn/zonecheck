"""Loader nạp dữ liệu UK vào DB. Thứ tự trong LOADERS = thứ tự phụ thuộc khi `python -m uk load all`."""
from .geography import BOUNDARY_LOADERS, WARD_LOADER, OnspdLoader
from .metrics import CensusExtraLoader, CensusLoader, CensusMoreLoader, HpiLoader, IncomeLoader, IodLoader, PcmLoader, PiprLoader
from .places import GreenspaceLoader, OpenNamesLoader
from .poi import FsaLoader, GiasLoader, NaptanLoader, NhsOdsLoader, OfstedLoader
from .schools import DfePerformanceLoader
from .school_profile import SCHOOL_PROFILE_LOADERS
from .wales import WalesSchoolsLoader, WimdLoader
from .rail import OrrStationUsageLoader
from .connectivity import ConnectivityLoader
from .council_tax import CouncilTaxLoader
from .epc import EpcLoader
from .manual import GpPatientsLoader, OfcomLoader
from .rofsw import NrwRofswLoader, OpenUprnLoader, RofswLoader
from .extra2 import EXTRA2_LOADERS
from .zones import ZONE_LOADERS
from .hazards import HAZARD_LOADERS
from .noise import NoiseLoader
from .roads import Stats19Loader
from .gap_tables import GAP_TABLE_LOADERS
from .osm import OsmLoader
from .classification import OacLoader
from .open_roads import OpenRoadsLoader
from .laei import LaeiLoader
from .police_history import PoliceHistoryLoader
from .planning_apps import LondonPlanningLoader
from .property_crime import PoliceLoader, PricePaidLoader

LOADERS = [
    *BOUNDARY_LOADERS, OnspdLoader(), WARD_LOADER,
    GiasLoader(), OfstedLoader(), DfePerformanceLoader(), *SCHOOL_PROFILE_LOADERS, WalesSchoolsLoader(), NaptanLoader(), OrrStationUsageLoader(), NhsOdsLoader(), GpPatientsLoader(), FsaLoader(),
    OpenNamesLoader(), GreenspaceLoader(), *ZONE_LOADERS,
    IodLoader(), WimdLoader(), ConnectivityLoader(), OfcomLoader(), CensusLoader(), HpiLoader(), PiprLoader(), CouncilTaxLoader(), IncomeLoader(), PcmLoader(),
    PoliceLoader(), PricePaidLoader(), EpcLoader(), OpenUprnLoader(), RofswLoader(),
    # lấp khoảng trống so với đối thủ (DATA_GAP_TRACKER.md)
    CensusExtraLoader(), CensusMoreLoader(), *HAZARD_LOADERS, NoiseLoader(), Stats19Loader(), *GAP_TABLE_LOADERS, OsmLoader(),
    NrwRofswLoader(), *EXTRA2_LOADERS, OacLoader(), OpenRoadsLoader(), LaeiLoader(), PoliceHistoryLoader(), LondonPlanningLoader(),
]
LOADER_BY_SOURCE = {l.source: l for l in LOADERS}
assert len(LOADER_BY_SOURCE) == len(LOADERS)
