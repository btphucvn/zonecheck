"""Vùng rủi ro/di sản/khí hậu bổ sung → core.zone (lấp khoảng trống so với đối thủ, xem DATA_GAP_TRACKER.md).

Mức rủi ro lưu ở core.zone.level_rank (số càng lớn càng nguy hiểm) để bước derive `hazards` tính % dân theo ngưỡng.
"""
from __future__ import annotations

from .zones import ACTIVE, ZoneLoader, ZoneSpec

NRW_RISK_RANK = "CASE s.risk WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 1 ELSE 0 END"
MINING_RANK = "CASE s.class WHEN 'Low' THEN 1 WHEN 'Moderate' THEN 2 WHEN 'Significant' THEN 3 ELSE 0 END"
GEOSURE = {  # layer → zone type
    "ShrinkSwell": "geo.shrink_swell", "Landslides": "geo.landslides", "SolubleRocks": "geo.soluble_rocks",
    "CompressibleGround": "geo.compressible_ground", "CollapsibleDeposits": "geo.collapsible_deposits",
    "RunningSand": "geo.running_sand",
}
CLIMATE = {  # file → (zone type, cột giá trị)
    "annual_temperature_observations_1991_2020": ("climate.tas", "tas"),
    "annual_max_temperature_observations_1991_2020": ("climate.tasmax", "tmax"),
    "annual_min_temperature_observations_1991_2020": ("climate.tasmin", "tmin"),
    "annual_precipitation_observations_1991_2020": ("climate.rainfall", "pr"),
    "annual_count_of_airfrost_days_1991_2020": ("climate.airfrost_days", "airfrostdays"),
    "annual_count_of_summer_days_1991_2020": ("climate.summer_days", "summerdays"),
    "annual_count_of_10mm_rain_days_1991_2020": ("climate.rain10mm_days", "rain10mmdays"),
    "annual_count_of_icing_days_1991_2020": ("climate.icing_days", "icingdays"),
}

HAZARD_LOADERS = [
    ZoneLoader("ea_landfill", [
        ZoneSpec(r"Historic_Landfill_Sites\.geojson\.zip", "risk.landfill_historic", member=r"\.geojson$",
                 name_fields=("site_name",), ext_fields=("hld_ref",), min_count=15000, max_count=25000,
                 area_km2=(300, 3000)),
        ZoneSpec(r"Permitted_Waste_Sites_Authorised_Landfill_Site_Boundaries\.geojson\.zip", "risk.landfill_authorised",
                 member=r"\.geojson$", name_fields=("site_name", "lic_name"), ext_fields=("lic_nmbr",),
                 min_count=1000, max_count=3000),
    ], description="EA bãi rác cũ + bãi rác đang cấp phép → core.zone risk.landfill_*"),
    ZoneLoader("ea_flood_history", [
        ZoneSpec(r"Historic_Flood_Map\.geojson\.zip", "flood.historic", member=r"\.geojson$", name_fields=("layer",),
                 ext_fields=("objectid",), min_count=10000, area_km2=(3000, 30000)),
        ZoneSpec(r"Recorded_Flood_Outlines\.geojson\.zip", "flood.recorded", member=r"\.geojson$",
                 name_fields=("name",), ext_fields=("rec_out_id",), min_count=20000),
    ], description="EA lũ đã xảy ra (Historic Flood Map gộp + từng đợt Recorded Flood Outlines) → core.zone flood.*"),
    ZoneLoader("ea_coastal_erosion", [
        ZoneSpec(r".*NCERM.*\.geojson\.zip", "coast.erosion_2055", member=r"NCERM_SMP_2055_70CC\.geojson$",
                 name_fields=("smp_name",), ext_fields=("frontageid",), min_count=5000, nlt="MULTIPOLYGON"),
        ZoneSpec(r".*NCERM.*\.geojson\.zip", "coast.erosion_2105", member=r"NCERM_SMP_2105_70CC\.geojson$",
                 name_fields=("smp_name",), ext_fields=("frontageid",), min_count=5000, nlt="MULTIPOLYGON"),
        ZoneSpec(r".*NCERM.*\.geojson\.zip", "coast.ground_instability", member=r"NCERM_Ground_Instability_Zone\.geojson$",
                 name_fields=("location",), ext_fields=("location",), min_count=50, nlt="MULTIPOLYGON"),
    ], description="EA NCERM 2024: vùng xói lở dự báo 2055/2105 (theo kế hoạch quản lý bờ biển, 70th pct) → core.zone coast.*"),
    ZoneLoader("coal_authority", [
        ZoneSpec(r"development_high_risk_area\.geojson", "coal.high_risk", name_fields=("FEATURE_TY",),
                 ext_fields=("FID",), min_count=20000, area_km2=(1000, 20000)),
        ZoneSpec(r"development_low_risk_area\.geojson", "coal.low_risk", name_fields=("FEATURE_TY",),
                 ext_fields=("FID",), min_count=10000, area_km2=(5000, 40000)),
    ], description="Coal Authority: vùng rủi ro mỏ than cao/thấp (cao ∪ thấp ≈ Coal Mining Reporting Area) → core.zone coal.*"),
    ZoneLoader("bgs_radon", [
        ZoneSpec(r"Radon_indicative_atlas_GB.*gpkg\.zip", "radon.atlas", member=r"\.gpkg$",
                 name_fields=("CLASS_MAX",), ext_fields=("TILE",), level_rank="s.class_max::smallint", layer="Radon_Indicative_Atlas_v3",
                 min_count=200000, max_count=300000, area_km2=(200000, 260000)),
    ], description="BGS/UKHSA radon atlas 1 km: lớp 1–6 (% nhà vượt ngưỡng hành động) → core.zone radon.atlas level_rank"),
    ZoneLoader("bgs_geosure_hex", [
        ZoneSpec(r"GB_Hex_5km_GeoSure_All\.zip", zt, member=r"\.gpkg$", layer=f"GB_Hex_5km_GS_{lyr}_v8",
                 name_fields=("Legend",), ext_fields=("CLASS",), level_rank="s.class::smallint",
                 min_count=1000, area_km2=(20000, 330000))  # ô hex phủ cả biển ven bờ
        for lyr, zt in GEOSURE.items()
    ], description="BGS GeoSure hex 5 km: co ngót đất sét, sạt lở, hoà tan, đất lún, cát chảy, đất sập → core.zone geo.*"),
    ZoneLoader("bgs_mining_hazard", [
        ZoneSpec(r"Hex_1km_MiningHazard.*\.zip", "geo.mining_non_coal", member=r"\.gpkg$", name_fields=("Legend",),
                 ext_fields=("Class",), level_rank=MINING_RANK, where="s.class <> 'NA'", min_count=10000,
                 layer="Hex_1km_MiningHazardNotIncludingCoalGB_v8"),
    ], description="BGS mỏ không phải than, hex 1 km → core.zone geo.mining_non_coal level_rank 1–3"),
    ZoneLoader("planning_data_extra", [
        ZoneSpec(r"scheduled-monument\.geojson", "heritage.scheduled_monument", where=ACTIVE, min_count=15000),
        ZoneSpec(r"park-and-garden\.geojson", "heritage.park_garden", where=ACTIVE, min_count=1000),
        ZoneSpec(r"battlefield\.geojson", "heritage.battlefield", where=ACTIVE, min_count=30),
        ZoneSpec(r"world-heritage-site\.geojson", "heritage.world_heritage_site", where=ACTIVE, min_count=10),
        ZoneSpec(r"world-heritage-site-buffer-zone\.geojson", "heritage.world_heritage_buffer", where=ACTIVE, min_count=5),
        ZoneSpec(r"heritage-coast\.geojson", "nature.heritage_coast", where=ACTIVE, min_count=20, max_outside=50),
        ZoneSpec(r"ancient-woodland\.geojson", "nature.ancient_woodland", where=ACTIVE, min_count=10000),
        ZoneSpec(r"special-area-of-conservation\.geojson", "nature.sac", where=ACTIVE, min_count=100, max_outside=50),
        ZoneSpec(r"special-protection-area\.geojson", "nature.spa", where=ACTIVE, min_count=50, max_outside=50),
        ZoneSpec(r"ramsar\.geojson", "nature.ramsar", where=ACTIVE, min_count=50, max_outside=50),
        ZoneSpec(r"air-quality-management-area\.geojson", "env.aqma", where=ACTIVE, min_count=200),
        ZoneSpec(r"heritage-at-risk\.geojson", "heritage.at_risk", where=ACTIVE, min_count=3000),
        ZoneSpec(r"listed-building-outline\.geojson", "heritage.listed_outline", where=ACTIVE, min_count=80000),
        ZoneSpec(r"locally-listed-building\.geojson", "heritage.locally_listed", where=ACTIVE, min_count=200),
        ZoneSpec(r"open-space\.geojson", "planning.open_space", where=ACTIVE, min_count=200),
        # local-plan-area phải nạp trước bảng local plan (kiểm tra độ phủ dùng nó)
        ZoneSpec(r"local-plan-boundary\.geojson", "planning.local_plan_area", where=ACTIVE, ext_fields=("reference",),
                 min_count=250, max_count=500, area_km2=(90_000, 200_000)),
    ], description="planning.data.gov.uk bổ sung → core.zone heritage.*, nature.*, env.aqma, planning.open_space/"
                   "local_plan_area + brownfield → core.poi + mkt_uk.local_plan"),
    ZoneLoader("nrw_flood", [
        ZoneSpec(r"floodzone_rivers_seas\.geojson", "flood.wales_zone3", name_fields=("risk",), ext_fields=("mm_id",),
                 where="s.risk = 'Flood Zone 3'", min_count=1000),
        ZoneSpec(r"floodzone_rivers_seas\.geojson", "flood.wales_zone2", name_fields=("risk",), ext_fields=("mm_id",),
                 where="s.risk = 'Flood Zone 2'", min_count=1000),
        ZoneSpec(r"flood_risk_rivers\.geojson", "flood.wales_rivers", name_fields=("risk",), ext_fields=("objectid", "mm_id"),
                 level_rank=NRW_RISK_RANK, min_count=50000),
        ZoneSpec(r"flood_risk_sea\.geojson", "flood.wales_sea", name_fields=("risk",), ext_fields=("mm_id",),
                 level_rank=NRW_RISK_RANK, min_count=10000),
        ZoneSpec(r"historic_floodmap\.geojson", "flood.wales_historic", name_fields=("name",), ext_fields=("name",),
                 min_count=500),
        ZoneSpec(r"historic_landfill\.geojson", "risk.landfill_historic_wales", name_fields=("site_name",),
                 ext_fields=("hld_ref",), min_count=1000),
        ZoneSpec(r"flood_warning_areas\.geojson", "flood.wales_warning_area", name_fields=("fwa_name",),
                 ext_fields=("fwd_tacode",), min_count=200),
    ], description="NRW (Wales): Flood Map for Planning zone 2/3, rủi ro sông/biển theo mức, lũ đã xảy ra, bãi rác cũ, khu cảnh báo → core.zone"),
    ZoneLoader("os_boundary_line", [
        ZoneSpec(r"bdline_gpkg_gb\.zip", "admin.westminster_const", member=r"bdline_gb\.gpkg$", layer="westminster_const",
                 name_fields=("name",), ext_fields=("code", "census_code"), min_count=600, max_count=700,
                 area_km2=(200_000, 240_000)),
        ZoneSpec(r"bdline_gpkg_gb\.zip", "admin.ward", member=r"bdline_gb\.gpkg$", layer="district_borough_unitary_ward",
                 name_fields=("name",), ext_fields=("code", "census_code"), min_count=6000),
        ZoneSpec(r"bdline_gpkg_gb\.zip", "admin.parish", member=r"bdline_gb\.gpkg$", layer="parish",
                 name_fields=("name",), ext_fields=("code", "census_code"), min_count=9000),
        ZoneSpec(r"bdline_gpkg_gb\.zip", "admin.county_division", member=r"bdline_gb\.gpkg$", layer="county_electoral_division",
                 name_fields=("name",), ext_fields=("code", "census_code"), min_count=1000),
    ], description="OS Boundary-Line: khu bầu cử Westminster, ward, parish, khu bầu cử hạt (kèm tên, mã GSS) → core.zone admin.*"),
    ZoneLoader("os_built_up_areas", [
        ZoneSpec(r"OS_Open_Built_Up_Areas_GeoPackage\.zip", "admin.built_up_area", member=r"\.gpkg$",
                 layer="os_open_built_up_areas", name_fields=("name1_text", "name"), ext_fields=("gsscode", "id"),
                 min_count=5000, area_km2=(10_000, 30_000)),
    ], description="OS Open Built Up Areas → core.zone admin.built_up_area (khu đô thị, kèm tên)"),
    ZoneLoader("haduk_grid", [
        ZoneSpec(rf"{f}\.geojson", zt, name_fields=(col,), ext_fields=("GRID_ID", "OBJECTID"), min_count=1000)
        for f, (zt, col) in CLIMATE.items()
    ], description="Met Office HadUK-Grid trung bình 1991–2020 (ô lưới, giá trị ở name + attrs) → core.zone climate.*"),
]
