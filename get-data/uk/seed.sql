-- Seed danh mục cho market UK: locale, market, licence, data_source, dataset.
-- Idempotent: chạy lại nhiều lần được. Mỗi tool trong get-data/uk/sources ứng với một dòng ops.dataset.
--   ./auth_key/vps/psql.sh < get-data/uk/seed.sql

BEGIN;

INSERT INTO core.locale (code, name_native, name_en, is_enabled) VALUES
    ('en', 'English', 'English', true),
    ('en-GB', 'English (UK)', 'English (UK)', true)
ON CONFLICT (code) DO NOTHING;
UPDATE core.locale SET fallback_locale = 'en' WHERE code = 'en-GB' AND fallback_locale IS NULL;

INSERT INTO core.market (code, name, country_codes, currency_code, default_locale, distance_unit, area_unit, timezone, status)
VALUES ('uk', 'United Kingdom', ARRAY['GB-ENG', 'GB-WLS', 'GB-SCT', 'GB-NIR'], 'GBP', 'en-GB', 'mi', 'm2', 'Europe/London', 'planned')
ON CONFLICT (code) DO NOTHING;

INSERT INTO core.market_locale (market_code, locale_code, status, is_default) VALUES ('uk', 'en-GB', 'draft', true)
ON CONFLICT DO NOTHING;

INSERT INTO ops.licence (code, name, url, allows_commercial, requires_attribution, is_share_alike, notes) VALUES
    ('OGL-UK-3.0', 'Open Government Licence v3.0', 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/', true, true, false, NULL),
    ('ODbL-1.0', 'Open Database License 1.0', 'https://opendatacommons.org/licenses/odbl/1-0/', true, true, true, 'OSM: không phát hành lại database dẫn xuất'),
    ('ONSPD', 'ONS licences (OGL + Royal Mail/OS third-party rights)', 'https://www.ons.gov.uk/methodology/geography/licences', true, true, false,
     'Toạ độ và một số trường có quyền Royal Mail/OS. Đọc kỹ điều khoản trước khi công bố; dự phòng Code-Point Open (OGL).'),
    ('OGL-UK-3.0-EXCEPT', 'OGL v3.0 có ngoại lệ', NULL, true, true, false, 'Một phần dữ liệu (ví dụ trường địa chỉ) không thuộc OGL')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, notes = EXCLUDED.notes;

INSERT INTO ops.data_source (id, market_code, name, publisher, homepage_url, licence_code, attribution_text, terms_url, terms_notes) VALUES
    ('uk.ons', 'uk', 'Office for National Statistics', 'ONS', 'https://geoportal.statistics.gov.uk/', 'OGL-UK-3.0',
     'Source: Office for National Statistics licensed under the Open Government Licence v3.0. Contains OS data © Crown copyright and database right [year].', NULL, NULL),
    ('uk.ons.onspd', 'uk', 'ONS Postcode Directory', 'ONS', 'https://geoportal.statistics.gov.uk/', 'ONSPD',
     'Contains OS data © Crown copyright and database right [year]. Contains Royal Mail data © Royal Mail copyright and database right [year]. Source: Office for National Statistics licensed under the Open Government Licence v3.0.',
     'https://www.ons.gov.uk/methodology/geography/licences', 'PLAN §7: kiểm tra quyền Royal Mail/OS trước khi công bố toạ độ'),
    ('uk.os', 'uk', 'Ordnance Survey OpenData', 'Ordnance Survey', 'https://osdatahub.os.uk/downloads/open', 'OGL-UK-3.0',
     'Contains OS data © Crown copyright and database right [year].', NULL, NULL),
    ('uk.land_registry', 'uk', 'HM Land Registry', 'HM Land Registry', 'https://www.gov.uk/government/organisations/land-registry', 'OGL-UK-3.0',
     'Contains HM Land Registry data © Crown copyright and database right [year]. This data is licensed under the Open Government Licence v3.0.',
     'https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads', 'Ghi nguồn bắt buộc. Không hiển thị tên người.'),
    ('uk.police', 'uk', 'data.police.uk', 'Home Office / police forces', 'https://data.police.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', 'https://data.police.uk/about/', 'Toạ độ đã ẩn danh'),
    ('uk.dfe', 'uk', 'Department for Education', 'DfE', 'https://get-information-schools.service.gov.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.ofsted', 'uk', 'Ofsted', 'Ofsted', 'https://www.gov.uk/government/organisations/ofsted', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, 'Report card 5 mức từ 10/11/2025'),
    ('uk.mhclg', 'uk', 'Ministry of Housing, Communities and Local Government', 'MHCLG', 'https://www.gov.uk/government/organisations/ministry-of-housing-communities-local-government', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.dft', 'uk', 'Department for Transport', 'DfT', 'https://www.gov.uk/government/organisations/department-for-transport', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.fsa', 'uk', 'Food Standards Agency', 'FSA', 'https://ratings.food.gov.uk/open-data', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.nhs', 'uk', 'NHS Organisation Data Service', 'NHS England', 'https://www.odsdatasearchandexport.nhs.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.defra', 'uk', 'Defra UK-AIR', 'Defra', 'https://uk-air.defra.gov.uk/data/pcm-data', 'OGL-UK-3.0',
     '© Crown copyright [year], Defra, licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.mhclg.epc', 'uk', 'Energy Performance of Buildings Register', 'MHCLG', 'https://get-energy-performance-data.communities.gov.uk/', 'OGL-UK-3.0-EXCEPT',
     'Contains public sector information licensed under the Open Government Licence v3.0. Address data: Royal Mail and OS copyright.',
     'https://get-energy-performance-data.communities.gov.uk/guidance/licensing-restrictions',
     'Trường địa chỉ có quyền Royal Mail/OS: chỉ dùng để ghép, chỉ công bố số liệu tổng hợp (PLAN §2.2 #7)'),
    ('uk.welsh_gov', 'uk', 'Welsh Government', 'Welsh Government', 'https://www.gov.wales/statistics-and-research', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, 'WIMD không so sánh chéo với IoD England'),
    ('uk.orr', 'uk', 'Office of Rail and Road', 'ORR', 'https://dataportal.orr.gov.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.ne', 'uk', 'Natural England', 'Natural England', 'https://naturalengland-defra.opendata.arcgis.com/', 'OGL-UK-3.0',
     '© Natural England copyright. Contains Ordnance Survey data © Crown copyright and database right [year].', NULL, NULL),
    ('uk.planning', 'uk', 'Planning Data (MHCLG)', 'MHCLG', 'https://www.planning.data.gov.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL,
     'Dữ liệu do từng LA cung cấp: độ phủ chưa đều. Không có kết quả ≠ không có ràng buộc (PLAN §2.2 #32)'),
    ('uk.ofcom', 'uk', 'Ofcom', 'Ofcom', 'https://www.ofcom.org.uk/phones-and-broadband/coverage-and-speeds', 'OGL-UK-3.0',
     'Contains Ofcom data © Ofcom copyright [year], licensed under the Open Government Licence v3.0.', NULL,
     'Trang dùng Cloudflare: tải bằng uk/manual/fetch.py (Chrome thật)'),
    ('uk.nhs_england', 'uk', 'NHS England Digital', 'NHS England', 'https://digital.nhs.uk/data-and-information/publications/statistical/patients-registered-at-a-gp-practice', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL,
     'Trang dùng Cloudflare: tải bằng uk/manual/fetch.py (Chrome thật)'),
    ('uk.ea', 'uk', 'Environment Agency', 'Environment Agency', 'https://environment.data.gov.uk/', 'OGL-UK-3.0',
     'This uses Environment Agency flood and river level data from the real-time data API (Beta).', NULL, 'NaFRA2/Flood Zones: kiểm tra giấy phép riêng')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, homepage_url = EXCLUDED.homepage_url, licence_code = EXCLUDED.licence_code,
    attribution_text = EXCLUDED.attribution_text, terms_url = EXCLUDED.terms_url, terms_notes = EXCLUDED.terms_notes;

INSERT INTO ops.dataset (id, source_id, name, update_frequency, native_level, coverage, loader_module) VALUES
    ('uk.ons.onspd',              'uk.ons.onspd',     'ONS Postcode Directory',                  'quarterly',  'postcode_unit', 'UK',  'get-data/uk/sources/geography.py:Onspd'),
    ('uk.os.codepoint_open',      'uk.os',            'OS Code-Point Open',                      'quarterly',  'postcode_unit', 'GB',  'get-data/uk/sources/geography.py:OsOpenData'),
    ('uk.os.open_names',          'uk.os',            'OS Open Names',                           'quarterly',  NULL,            'GB',  'get-data/uk/sources/geography.py:OsOpenData'),
    ('uk.os.open_uprn',           'uk.os',            'OS Open UPRN',                            'quarterly',  NULL,            'GB',  'get-data/uk/sources/geography.py:OsOpenData'),
    ('uk.os.open_greenspace',     'uk.os',            'OS Open Greenspace',                      'semiannual', NULL,            'GB',  'get-data/uk/sources/geography.py:OsOpenData'),
    ('uk.ons.boundaries_oa21',    'uk.ons',           'Output Areas 2021 boundaries (BGC)',      'irregular',  'oa',            'E&W', 'get-data/uk/sources/geography.py:OnsBoundary'),
    ('uk.ons.boundaries_lsoa21',  'uk.ons',           'LSOA 2021 boundaries (BGC)',              'irregular',  'lsoa',          'E&W', 'get-data/uk/sources/geography.py:OnsBoundary'),
    ('uk.ons.boundaries_msoa21',  'uk.ons',           'MSOA 2021 boundaries (BGC)',              'irregular',  'msoa',          'E&W', 'get-data/uk/sources/geography.py:OnsBoundary'),
    ('uk.ons.boundaries_lad',     'uk.ons',           'Local Authority District boundaries (BGC)', 'annual',   'lad',           'UK',  'get-data/uk/sources/geography.py:OnsBoundary'),
    ('uk.ons.boundaries_rgn',     'uk.ons',           'Region boundaries (BGC)',                 'irregular',  'region',        'England', 'get-data/uk/sources/geography.py:OnsBoundary'),
    ('uk.land_registry.ppd',      'uk.land_registry', 'Price Paid Data',                         'monthly',    'postcode_unit', 'E&W', 'get-data/uk/sources/housing.py:PricePaid'),
    ('uk.land_registry.hpi',      'uk.land_registry', 'UK House Price Index',                    'monthly',    'lad',           'UK',  'get-data/uk/sources/housing.py:UkHpi'),
    ('uk.ons.pipr',               'uk.ons',           'Price Index of Private Rents',            'monthly',    'lad',           'UK',  'get-data/uk/sources/housing.py:OnsDataset'),
    ('uk.ons.income_msoa',        'uk.ons',           'Small area income estimates (MSOA)',      'irregular',  'msoa',          'E&W', 'get-data/uk/sources/housing.py:OnsDataset'),
    ('uk.police.street_crime',    'uk.police',        'Street-level crime archive',              'monthly',    'lsoa',          'E&W+NI', 'get-data/uk/sources/social.py:Police'),
    ('uk.dfe.gias',               'uk.dfe',           'Get Information About Schools',           'daily',      NULL,            'England', 'get-data/uk/sources/social.py:Gias'),
    ('uk.ofsted.schools_mi',      'uk.ofsted',        'Ofsted school inspections MI',            'monthly',    NULL,            'England', 'get-data/uk/sources/social.py:Ofsted'),
    ('uk.ons.census2021',         'uk.ons',           'Census 2021 bulk (Nomis)',                'irregular',  'oa',            'E&W', 'get-data/uk/sources/social.py:Census2021'),
    ('uk.mhclg.iod2025',          'uk.mhclg',         'English Indices of Deprivation 2025',     'irregular',  'lsoa',          'England', 'get-data/uk/sources/social.py:GovukAttachments'),
    ('uk.dft.journey_time',       'uk.dft',           'Journey Time Statistics',                 'annual',     'lsoa',          'England', 'get-data/uk/sources/social.py:GovukAttachments'),
    ('uk.dft.naptan',             'uk.dft',           'NaPTAN stops',                            'daily',      NULL,            'GB',  'get-data/uk/sources/amenities.py:Naptan'),
    ('uk.fsa.food_hygiene',       'uk.fsa',           'Food Hygiene Rating Scheme',              'daily',      NULL,            'UK',  'get-data/uk/sources/amenities.py:Fsa'),
    ('uk.ea.rofsw',               'uk.ea',            'Risk of Flooding from Surface Water (NaFRA2)', 'irregular', NULL,        'England', 'get-data/uk/sources/rofsw.py:EaRofsw'),
    ('uk.ofcom.connected_nations', 'uk.ofcom',        'Ofcom Connected Nations (fixed + mobile coverage)', 'irregular', 'oa', 'UK', 'get-data/uk/sources/manual.py:OfcomConnectedNations'),
    ('uk.nhs.gp_patients',        'uk.nhs_england',   'Patients registered at a GP practice',    'monthly',    NULL,            'England', 'get-data/uk/sources/manual.py:NhsGpPatients'),
    ('uk.nhs.ods',                'uk.nhs',           'NHS ODS (GP, pharmacy, dental, trust sites)', 'weekly', NULL,            'England & Wales', 'get-data/uk/sources/amenities.py:NhsOds'),
    ('uk.defra.pcm',              'uk.defra',         'PCM background concentrations',           'annual',     NULL,            'UK',  'get-data/uk/sources/amenities.py:DefraPcm'),
    ('uk.dfe.school_performance', 'uk.dfe',           'School performance tables KS2/KS4/KS5',   'annual',     NULL,            'England', 'get-data/uk/sources/schools_perf.py:DfePerformance'),
    ('uk.welsh_gov.wimd',         'uk.welsh_gov',     'Welsh Index of Multiple Deprivation 2025', 'irregular',  'lsoa',          'Wales', 'get-data/uk/sources/wales.py:Wimd'),
    ('uk.welsh_gov.schools',      'uk.welsh_gov',     'Wales schools address list',              'annual',     NULL,            'Wales', 'get-data/uk/sources/wales.py:WalesSchools'),
    ('uk.orr.station_usage',      'uk.orr',           'Estimates of station usage',              'annual',     NULL,            'GB',  'get-data/uk/sources/rail.py:OrrStationUsage'),
    ('uk.dft.connectivity',       'uk.dft',           'Transport connectivity metric',           'annual',     'oa',            'E&W', 'get-data/uk/sources/social.py:GovukAttachments'),
    ('uk.council_tax',            'uk.mhclg',         'Council tax levels + stock of properties', 'annual',     'lad',           'E&W', 'get-data/uk/sources/council_tax.py:CouncilTax'),
    ('uk.mhclg.planning_data',    'uk.planning',      'Planning constraints (conservation, Article 4, green belt, TPO, listed)', 'weekly', NULL, 'England', 'get-data/uk/sources/zones.py:PlanningData'),
    ('uk.ne.designations',        'uk.ne',            'SSSI, National Parks, National Landscapes, LNR', 'irregular', NULL,           'England', 'get-data/uk/sources/zones.py:ArcgisZones'),
    ('uk.ons.pfa',                'uk.ons',           'Police Force Areas boundaries',           'irregular',  NULL,            'E&W', 'get-data/uk/sources/zones.py:ArcgisZones'),
    ('uk.ea.flood_zones',         'uk.ea',            'Flood Map for Planning (Rivers and Sea)', 'quarterly',  NULL,            'England', 'get-data/uk/sources/zones.py:ArcgisZones'),
    ('uk.mhclg.epc_domestic',     'uk.mhclg.epc',     'EPC domestic certificates',               'monthly',    'postcode_unit', 'E&W', 'get-data/uk/sources/epc.py:EpcDomestic'),
    ('uk.ea.flood_areas',         'uk.ea',            'Flood alert/warning areas',               'irregular',  NULL,            'England', 'get-data/uk/sources/amenities.py:EaFloodAreas')
ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id, name = EXCLUDED.name, update_frequency = EXCLUDED.update_frequency,
    native_level = EXCLUDED.native_level, coverage = EXCLUDED.coverage, loader_module = EXCLUDED.loader_module;

-- ---------------------------------------------------------------- danh mục dùng bởi loader -----
INSERT INTO core.geo_level (market_code, code, name, rank, kind, is_searchable, has_pages, url_segment, boundary_vintage) VALUES
    ('uk', 'postcode_unit', 'Postcode',            0, 'postal',         true,  true,  'postcode', NULL),
    ('uk', 'sector',        'Postcode sector',     1, 'postal',         true,  true,  'sector',   NULL),
    ('uk', 'district',      'Postcode district',   2, 'postal',         true,  true,  'district', NULL),
    ('uk', 'postal_area',   'Postcode area',       3, 'postal',         false, false, NULL,       NULL),
    ('uk', 'oa',            'Output Area',         0, 'statistical',    false, false, NULL,       '2021'),
    ('uk', 'lsoa',          'LSOA',                1, 'statistical',    false, false, NULL,       '2021'),
    ('uk', 'msoa',          'MSOA',                2, 'statistical',    false, false, NULL,       '2021'),
    ('uk', 'town',          'Town / city',         3, 'settlement',     true,  true,  'town',     NULL),
    ('uk', 'lad',           'Local authority',     4, 'administrative', true,  true,  'area',     NULL),
    ('uk', 'region',        'Region',              5, 'administrative', true,  true,  'region',   NULL),
    ('uk', 'nation',        'Nation',              6, 'administrative', false, false, NULL,       NULL)
ON CONFLICT (market_code, code) DO UPDATE SET name = EXCLUDED.name, rank = EXCLUDED.rank, kind = EXCLUDED.kind,
    is_searchable = EXCLUDED.is_searchable, has_pages = EXCLUDED.has_pages, url_segment = EXCLUDED.url_segment,
    boundary_vintage = EXCLUDED.boundary_vintage;

INSERT INTO core.metric_category (code, name_i18n, sort_order) VALUES
    ('housing',      '{"en":"Property prices"}', 10), ('rent', '{"en":"Rent"}', 20),
    ('safety',       '{"en":"Crime & safety"}', 30),  ('education', '{"en":"Schools"}', 40),
    ('transport',    '{"en":"Transport"}', 50),       ('amenities', '{"en":"Amenities & health"}', 60),
    ('environment',  '{"en":"Environment"}', 70),     ('risk', '{"en":"Risks"}', 80),
    ('connectivity', '{"en":"Broadband & mobile"}', 90), ('people', '{"en":"People"}', 100),
    ('economy',      '{"en":"Income & deprivation"}', 110), ('energy', '{"en":"Housing stock & energy"}', 120),
    ('costs',        '{"en":"Costs"}', 130),          ('planning', '{"en":"Planning & conservation"}', 140)
ON CONFLICT (code) DO UPDATE SET name_i18n = EXCLUDED.name_i18n, sort_order = EXCLUDED.sort_order;

INSERT INTO core.poi_type (code, parent_code, name_i18n, is_searchable, has_pages, url_segment) VALUES
    ('school', NULL, '{"en":"School"}', true, true, 'school'),
    ('school.nursery', 'school', '{"en":"Nursery school"}', true, true, 'school'),
    ('school.primary', 'school', '{"en":"Primary school"}', true, true, 'school'),
    ('school.secondary', 'school', '{"en":"Secondary school"}', true, true, 'school'),
    ('school.all_through', 'school', '{"en":"All-through school"}', true, true, 'school'),
    ('school.post16', 'school', '{"en":"Sixth form / 16+"}', true, true, 'school'),
    ('school.special', 'school', '{"en":"Special school"}', true, true, 'school'),
    ('school.other', 'school', '{"en":"Other education provider"}', true, true, 'school'),
    ('college', NULL, '{"en":"College / university"}', true, false, NULL),
    ('transport', NULL, '{"en":"Transport"}', false, false, NULL),
    ('stop.bus', 'transport', '{"en":"Bus stop"}', false, false, NULL),
    ('station.bus', 'transport', '{"en":"Bus station"}', false, false, NULL),
    ('station.rail', 'transport', '{"en":"Rail station"}', true, true, 'station'),
    ('station.metro', 'transport', '{"en":"Underground / metro / tram stop"}', true, true, 'station'),
    ('station.ferry', 'transport', '{"en":"Ferry terminal"}', false, false, NULL),
    ('airport', 'transport', '{"en":"Airport"}', false, false, NULL),
    ('health', NULL, '{"en":"Health"}', false, false, NULL),
    ('health.gp', 'health', '{"en":"GP practice"}', true, false, NULL),
    ('health.pharmacy', 'health', '{"en":"Pharmacy"}', false, false, NULL),
    ('health.dentist', 'health', '{"en":"Dentist"}', false, false, NULL),
    ('health.trust_site', 'health', '{"en":"NHS hospital / clinic site"}', false, false, NULL),
    ('food', NULL, '{"en":"Food business"}', false, false, NULL),
    ('food.restaurant', 'food', '{"en":"Restaurant / cafe"}', false, false, NULL),
    ('food.takeaway', 'food', '{"en":"Takeaway"}', false, false, NULL),
    ('food.pub', 'food', '{"en":"Pub / bar / nightclub"}', false, false, NULL),
    ('shop.supermarket', 'food', '{"en":"Supermarket"}', false, false, NULL),
    ('shop.food_retail', 'food', '{"en":"Other food retailer"}', false, false, NULL),
    ('food.other', 'food', '{"en":"Other food business"}', false, false, NULL)
ON CONFLICT (code) DO UPDATE SET parent_code = EXCLUDED.parent_code, name_i18n = EXCLUDED.name_i18n,
    is_searchable = EXCLUDED.is_searchable, has_pages = EXCLUDED.has_pages, url_segment = EXCLUDED.url_segment;

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, dataset_id) VALUES
    ('greenspace.park', 'amenities', '{"en":"Public park or garden"}', false, 'uk.os.open_greenspace'),
    ('greenspace.play', 'amenities', '{"en":"Play space"}', false, 'uk.os.open_greenspace'),
    ('greenspace.playing_field', 'amenities', '{"en":"Playing field"}', false, 'uk.os.open_greenspace'),
    ('greenspace.sports', 'amenities', '{"en":"Sports facility"}', false, 'uk.os.open_greenspace'),
    ('greenspace.allotment', 'amenities', '{"en":"Allotments"}', false, 'uk.os.open_greenspace'),
    ('greenspace.cemetery', 'amenities', '{"en":"Cemetery / religious grounds"}', false, 'uk.os.open_greenspace'),
    ('greenspace.golf', 'amenities', '{"en":"Golf course"}', false, 'uk.os.open_greenspace')
ON CONFLICT (code) DO UPDATE SET category_code = EXCLUDED.category_code, name_i18n = EXCLUDED.name_i18n;

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, level_scale, dataset_id) VALUES
    ('planning.conservation_area', 'planning', '{"en":"Conservation area"}', false, NULL, 'uk.mhclg.planning_data'),
    ('planning.article4', 'planning', '{"en":"Article 4 direction area"}', false, NULL, 'uk.mhclg.planning_data'),
    ('planning.green_belt', 'planning', '{"en":"Green belt"}', false, NULL, 'uk.mhclg.planning_data'),
    ('planning.tpo', 'planning', '{"en":"Tree preservation order zone"}', false, NULL, 'uk.mhclg.planning_data'),
    ('nature.sssi', 'planning', '{"en":"Site of Special Scientific Interest"}', false, NULL, 'uk.ne.designations'),
    ('nature.national_park', 'planning', '{"en":"National Park"}', false, NULL, 'uk.ne.designations'),
    ('nature.national_landscape', 'planning', '{"en":"National Landscape (AONB)"}', false, NULL, 'uk.ne.designations'),
    ('nature.local_nature_reserve', 'planning', '{"en":"Local Nature Reserve"}', false, NULL, 'uk.ne.designations'),
    ('admin.police_force_area', 'safety', '{"en":"Police force area"}', false, NULL, 'uk.ons.pfa'),
    ('flood.zone3', 'risk', '{"en":"Flood Zone 3 (high probability, rivers and sea)"}', true, '{"rank":3}', 'uk.ea.flood_zones'),
    ('flood.zone2', 'risk', '{"en":"Flood Zone 2 (medium probability, rivers and sea)"}', true, '{"rank":2}', 'uk.ea.flood_zones'),
    ('flood.storage_area', 'risk', '{"en":"Flood storage area"}', true, NULL, 'uk.ea.flood_zones'),
    ('flood.warning_area', 'risk', '{"en":"Flood Warning area (Environment Agency warning service)"}', false, NULL, 'uk.ea.flood_areas'),
    ('flood.alert_area', 'risk', '{"en":"Flood Alert area (Environment Agency alert service)"}', false, NULL, 'uk.ea.flood_areas')
ON CONFLICT (code) DO UPDATE SET category_code = EXCLUDED.category_code, name_i18n = EXCLUDED.name_i18n,
    is_hazard = EXCLUDED.is_hazard, level_scale = EXCLUDED.level_scale, dataset_id = EXCLUDED.dataset_id;

INSERT INTO core.poi_type (code, parent_code, name_i18n, is_searchable, has_pages, url_segment) VALUES
    ('heritage', NULL, '{"en":"Heritage"}', false, false, NULL),
    ('heritage.listed_building', 'heritage', '{"en":"Listed building"}', false, false, NULL)
ON CONFLICT (code) DO NOTHING;

INSERT INTO core.comparison_scope (id, market_code, name, description) VALUES
    ('uk.england', 'uk', 'England', 'Chỉ số chỉ có/so sánh được trong England (IoD 2025, Ofsted)'),
    ('uk.wales', 'uk', 'Wales', 'Chỉ số riêng Wales (WIMD)'),
    ('uk.ew', 'uk', 'England & Wales', 'Chỉ số cùng phương pháp ở E&W (Census 2021, police, Price Paid)'),
    ('uk.uk', 'uk', 'United Kingdom', 'Chỉ số toàn UK (PCM, UK HPI)')
ON CONFLICT (id) DO NOTHING;

-- Dataset do loader tự sinh (không có tool tải riêng)
INSERT INTO ops.dataset (id, source_id, name, update_frequency, native_level, coverage, loader_module) VALUES
    ('uk.derived.geo', 'uk.ons', 'Đơn vị suy ra (sector, district, nation, liên kết cấp)', 'irregular', NULL, 'UK',
     'get-data/uk/loaders')
ON CONFLICT (id) DO NOTHING;

-- ------------------------------------------------ lấp khoảng trống so với đối thủ (DATA_GAP_TRACKER.md) -----
INSERT INTO ops.licence (code, name, url, allows_commercial, requires_attribution, is_share_alike, notes) VALUES
    ('OPL-3.0', 'Open Parliament Licence v3.0', 'https://www.parliament.uk/site-information/copyright-parliament/open-parliament-licence/', true, true, false, NULL),
    ('TFL-OD', 'Transport for London open data terms', 'https://tfl.gov.uk/corporate/terms-and-conditions/transport-data-service', true, true, false,
     'Ghi "Powered by TfL Open Data"; không dùng logo TfL')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, notes = EXCLUDED.notes;

INSERT INTO ops.data_source (id, market_code, name, publisher, homepage_url, licence_code, attribution_text, terms_url, terms_notes) VALUES
    ('uk.bgs', 'uk', 'British Geological Survey', 'BGS', 'https://www.bgs.ac.uk/', 'OGL-UK-3.0',
     'Contains British Geological Survey materials © UKRI [year]. Radon: © UKHSA and UKRI.', NULL,
     'Bản hex/1 km là tổng quát hoá (mỗi ô lấy mức cao nhất), chỉ mang tính chỉ dẫn'),
    ('uk.coal', 'uk', 'Mining Remediation Authority (Coal Authority)', 'Mining Remediation Authority', 'https://datamine-cauk.hub.arcgis.com/', 'OGL-UK-3.0',
     'Contains Mining Remediation Authority data © Crown copyright and database right [year].', NULL, NULL),
    ('uk.nrw', 'uk', 'Natural Resources Wales', 'NRW', 'https://datamap.gov.wales/', 'OGL-UK-3.0',
     'Contains Natural Resources Wales information © Natural Resources Wales and database right. All rights Reserved.', NULL, NULL),
    ('uk.cqc', 'uk', 'Care Quality Commission', 'CQC', 'https://www.cqc.org.uk/about-us/transparency/using-cqc-data', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.metoffice', 'uk', 'Met Office HadUK-Grid', 'Met Office', 'https://www.metoffice.gov.uk/research/climate/maps-and-data/data/haduk-grid', 'OGL-UK-3.0',
     'Contains Met Office data © Crown copyright [year], licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.tfl', 'uk', 'Transport for London', 'TfL', 'https://api.tfl.gov.uk/', 'TFL-OD', 'Powered by TfL Open Data.', NULL, NULL),
    ('uk.gla', 'uk', 'London Datastore', 'Greater London Authority', 'https://data.london.gov.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.osm', 'uk', 'OpenStreetMap (Geofabrik extract)', 'OpenStreetMap contributors', 'https://download.geofabrik.de/europe/united-kingdom.html', 'ODbL-1.0',
     '© OpenStreetMap contributors', 'https://www.openstreetmap.org/copyright', 'Chỉ hiển thị; không phát hành lại database dẫn xuất'),
    ('uk.parliament', 'uk', 'UK Parliament Members API', 'UK Parliament', 'https://members-api.parliament.uk/', 'OPL-3.0',
     'Contains Parliamentary information licensed under the Open Parliament Licence v3.0.', NULL, NULL),
    ('uk.govuk', 'uk', 'GOV.UK', 'GOV.UK', 'https://www.gov.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL),
    ('uk.voa', 'uk', 'Valuation Office Agency', 'VOA', 'https://www.gov.uk/government/organisations/valuation-office-agency', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0.', NULL, NULL)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, homepage_url = EXCLUDED.homepage_url, licence_code = EXCLUDED.licence_code,
    attribution_text = EXCLUDED.attribution_text, terms_url = EXCLUDED.terms_url, terms_notes = EXCLUDED.terms_notes;

INSERT INTO ops.dataset (id, source_id, name, update_frequency, native_level, coverage, loader_module) VALUES
    ('uk.mhclg.planning_data_extra', 'uk.planning', 'Planning data bổ sung (di sản, môi trường, quy hoạch)', 'irregular', NULL, 'England', 'get-data/uk/sources/zones.py:PlanningDataExtra'),
    ('uk.ea.landfill',            'uk.ea',  'Historic + Authorised Landfill',                 'quarterly',  NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.pollution_incidents', 'uk.ea',  'Environmental Pollution Incidents (cat 1–2)',     'annual',     NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.ncerm',               'uk.ea',  'National Coastal Erosion Risk Mapping 2024',      'irregular',  NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.flood_history',       'uk.ea',  'Recorded Flood Outlines + Historic Flood Map',    'quarterly',  NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.flood_defences',      'uk.ea',  'AIMS Spatial Flood Defences',                     'quarterly',  NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.reservoir_flood',     'uk.ea',  'Reservoir Flood Extents',                         'irregular',  NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.rofrs_postcodes',     'uk.ea',  'RoFRS postcodes/properties in areas at risk',     'irregular',  'postcode_unit', 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.ea.storm_overflows',     'uk.ea',  'Event Duration Monitoring storm overflows',       'annual',     NULL, 'England', 'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.nrw.flood',              'uk.nrw', 'NRW flood risk, flood map, historic flood, landfill', 'irregular', NULL, 'Wales', 'get-data/uk/sources/environment.py:WfsLayers'),
    ('uk.coal.risk_areas',        'uk.coal', 'Coal mining development high/low risk areas',    'irregular',  NULL, 'GB',      'get-data/uk/sources/environment.py:ArcgisZones'),
    ('uk.bgs.radon',              'uk.bgs', 'Indicative Atlas of Radon (1 km)',                'irregular',  NULL, 'GB',      'get-data/uk/sources/environment.py:BgsOpenData'),
    ('uk.bgs.geosure_hex',        'uk.bgs', 'GeoSure 5 km hex grid',                           'irregular',  NULL, 'GB',      'get-data/uk/sources/environment.py:BgsOpenData'),
    ('uk.bgs.mining_hazard',      'uk.bgs', 'Mining hazard (not coal) 1 km hex',               'irregular',  NULL, 'GB',      'get-data/uk/sources/environment.py:BgsOpenData'),
    ('uk.defra.noise_r4',         'uk.defra', 'Strategic Noise Mapping Round 4 (road, rail, airport)', 'irregular', NULL, 'England', 'get-data/uk/sources/noise.py:DefraNoise'),
    ('uk.cqc.directory',          'uk.cqc', 'CQC care directory + latest ratings',             'monthly',    NULL, 'England', 'get-data/uk/sources/extra.py:Cqc'),
    ('uk.ofsted.childcare',       'uk.ofsted', 'Childcare providers and inspections',          'semiannual', NULL, 'England', 'get-data/uk/sources/extra.py:GovukLatestStats'),
    ('uk.dft.stats19',            'uk.dft', 'Road casualty statistics (STATS19), last 5 years', 'annual',    NULL, 'GB',      'get-data/uk/sources/extra.py:UrlFiles'),
    ('uk.dft.traffic_aadf',       'uk.dft', 'Road traffic AADF by count point',                'annual',     NULL, 'GB',      'get-data/uk/sources/extra.py:UrlFiles'),
    ('uk.gla.ptal',               'uk.gla', 'PTAL 2015 (London)',                              'irregular',  NULL, 'London',  'get-data/uk/sources/environment.py:CkanFiles'),
    ('uk.tfl.stations',           'uk.tfl', 'TfL stations + fare zones',                       'monthly',    NULL, 'London',  'get-data/uk/sources/extra.py:TflStations'),
    ('uk.metoffice.haduk_grid',   'uk.metoffice', 'HadUK-Grid 1 km 30-year climate averages',  'annual',     NULL, 'UK',      'get-data/uk/sources/extra.py:HadUkGrid'),
    ('uk.osm.geofabrik',          'uk.osm', 'OpenStreetMap UK extract',                        'monthly',    NULL, 'UK',      'get-data/uk/sources/extra.py:OsmUk'),
    ('uk.parliament.mps',         'uk.parliament', 'Current MPs by constituency',              'monthly',    NULL, 'UK',      'get-data/uk/sources/extra.py:ParliamentMps'),
    ('uk.govuk.rpt_decisions',    'uk.govuk', 'Residential Property Tribunal decisions',       'weekly',     NULL, 'England', 'get-data/uk/sources/extra.py:TribunalDecisions'),
    ('uk.voa.lha_rates',          'uk.voa', 'Local Housing Allowance rates',                   'annual',     NULL, 'England', 'get-data/uk/sources/extra.py:GovukLatestStats'),
    ('uk.defra.fly_tipping',      'uk.defra', 'Fly-tipping incidents by LA',                   'annual',     'lad', 'England', 'get-data/uk/sources/extra.py:GovukLatestStats'),
    ('uk.ons.affordability',      'uk.ons', 'House price to workplace-based earnings ratio',   'annual',     'lad', 'E&W',    'get-data/uk/sources/housing.py:OnsDataset'),
    ('uk.ons.lsoa_population',    'uk.ons', 'LSOA mid-year population estimates',             'annual',     'lsoa', 'E&W',   'get-data/uk/sources/housing.py:OnsDataset'),
    ('uk.dfe.school_offers',      'uk.dfe', 'Primary and secondary school applications and offers', 'annual', 'lad', 'England', 'get-data/uk/sources/extra.py:EesReleaseFiles'),
    ('uk.os.boundary_line',       'uk.os',  'OS Boundary-Line',                                'semiannual', NULL, 'GB',      'get-data/uk/sources/geography.py:OsOpenData'),
    ('uk.os.built_up_areas',      'uk.os',  'OS Open Built Up Areas',                          'annual',     NULL, 'GB',      'get-data/uk/sources/geography.py:OsOpenData')
ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id, name = EXCLUDED.name, update_frequency = EXCLUDED.update_frequency,
    native_level = EXCLUDED.native_level, coverage = EXCLUDED.coverage, loader_module = EXCLUDED.loader_module;

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, level_scale, dataset_id) VALUES
    ('risk.landfill_historic', 'risk', '{"en":"Historic landfill site"}', true, NULL, 'uk.ea.landfill'),
    ('risk.landfill_authorised', 'risk', '{"en":"Authorised (permitted) landfill site"}', true, NULL, 'uk.ea.landfill'),
    ('flood.historic', 'risk', '{"en":"Historic flood extent (all recorded floods)"}', true, NULL, 'uk.ea.flood_history'),
    ('flood.recorded', 'risk', '{"en":"Recorded flood outline (individual event)"}', true, NULL, 'uk.ea.flood_history'),
    ('coast.erosion_2055', 'risk', '{"en":"Coastal erosion zone by 2055 (with shoreline management plan)"}', true, NULL, 'uk.ea.ncerm'),
    ('coast.erosion_2105', 'risk', '{"en":"Coastal erosion zone by 2105 (with shoreline management plan)"}', true, NULL, 'uk.ea.ncerm'),
    ('coast.ground_instability', 'risk', '{"en":"Coastal ground instability zone"}', true, NULL, 'uk.ea.ncerm'),
    ('coal.high_risk', 'risk', '{"en":"Coal mining development high risk area"}', true, '{"rank":2}', 'uk.coal.risk_areas'),
    ('coal.low_risk', 'risk', '{"en":"Coal mining development low risk area"}', true, '{"rank":1}', 'uk.coal.risk_areas'),
    ('radon.atlas', 'risk', '{"en":"Radon potential (share of homes above the action level)"}', true, '{"1":"<1%","2":"1–3%","3":"3–5%","4":"5–10%","5":"10–30%","6":">30%"}', 'uk.bgs.radon'),
    ('geo.shrink_swell', 'risk', '{"en":"Shrink–swell clay (subsidence) susceptibility"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.geosure_hex'),
    ('geo.landslides', 'risk', '{"en":"Landslide susceptibility"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.geosure_hex'),
    ('geo.soluble_rocks', 'risk', '{"en":"Soluble rocks (sinkhole) susceptibility"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.geosure_hex'),
    ('geo.compressible_ground', 'risk', '{"en":"Compressible ground susceptibility"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.geosure_hex'),
    ('geo.collapsible_deposits', 'risk', '{"en":"Collapsible deposits susceptibility"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.geosure_hex'),
    ('geo.running_sand', 'risk', '{"en":"Running sand susceptibility"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.geosure_hex'),
    ('geo.mining_non_coal', 'risk', '{"en":"Non-coal mining hazard"}', true, '{"1":"Low","2":"Moderate","3":"Significant"}', 'uk.bgs.mining_hazard'),
    ('heritage.scheduled_monument', 'planning', '{"en":"Scheduled monument"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('heritage.park_garden', 'planning', '{"en":"Registered park and garden"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('heritage.battlefield', 'planning', '{"en":"Registered battlefield"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('heritage.world_heritage_site', 'planning', '{"en":"World Heritage Site"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('heritage.world_heritage_buffer', 'planning', '{"en":"World Heritage Site buffer zone"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('nature.heritage_coast', 'planning', '{"en":"Heritage coast"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('nature.ancient_woodland', 'planning', '{"en":"Ancient woodland"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('nature.sac', 'planning', '{"en":"Special Area of Conservation"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('nature.spa', 'planning', '{"en":"Special Protection Area"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('nature.ramsar', 'planning', '{"en":"Ramsar wetland"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('env.aqma', 'environment', '{"en":"Air Quality Management Area"}', true, NULL, 'uk.mhclg.planning_data_extra'),
    ('climate.tas', 'environment', '{"en":"Mean annual temperature 1991–2020 (°C)"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.tasmax', 'environment', '{"en":"Mean daily maximum temperature 1991–2020 (°C)"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.tasmin', 'environment', '{"en":"Mean daily minimum temperature 1991–2020 (°C)"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.rainfall', 'environment', '{"en":"Annual rainfall 1991–2020 (mm)"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.airfrost_days', 'environment', '{"en":"Air frost days per year 1991–2020"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.summer_days', 'environment', '{"en":"Summer days (>25 °C) per year 1991–2020"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.rain10mm_days', 'environment', '{"en":"Days with 10 mm+ rain per year 1991–2020"}', false, NULL, 'uk.metoffice.haduk_grid'),
    ('climate.icing_days', 'environment', '{"en":"Icing days per year 1991–2020"}', false, NULL, 'uk.metoffice.haduk_grid')
ON CONFLICT (code) DO UPDATE SET category_code = EXCLUDED.category_code, name_i18n = EXCLUDED.name_i18n,
    is_hazard = EXCLUDED.is_hazard, level_scale = EXCLUDED.level_scale, dataset_id = EXCLUDED.dataset_id;

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, level_scale, dataset_id) VALUES
    ('flood.wales_zone3', 'risk', '{"en":"Flood Zone 3 (Wales, rivers and sea)"}', true, '{"rank":3}', 'uk.nrw.flood'),
    ('flood.wales_zone2', 'risk', '{"en":"Flood Zone 2 (Wales, rivers and sea)"}', true, '{"rank":2}', 'uk.nrw.flood'),
    ('flood.wales_rivers', 'risk', '{"en":"Flood risk from rivers (Wales)"}', true, '{"1":"Low","2":"Medium","3":"High"}', 'uk.nrw.flood'),
    ('flood.wales_sea', 'risk', '{"en":"Flood risk from the sea (Wales)"}', true, '{"1":"Low","2":"Medium","3":"High"}', 'uk.nrw.flood'),
    ('flood.wales_historic', 'risk', '{"en":"Recorded flood extent (Wales)"}', true, NULL, 'uk.nrw.flood'),
    ('risk.landfill_historic_wales', 'risk', '{"en":"Historic landfill site (Wales)"}', true, NULL, 'uk.nrw.flood'),
    ('flood.wales_warning_area', 'risk', '{"en":"Flood warning area (Natural Resources Wales)"}', false, NULL, 'uk.nrw.flood')
ON CONFLICT (code) DO UPDATE SET category_code = EXCLUDED.category_code, name_i18n = EXCLUDED.name_i18n,
    is_hazard = EXCLUDED.is_hazard, level_scale = EXCLUDED.level_scale, dataset_id = EXCLUDED.dataset_id;

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, level_scale, dataset_id) VALUES
    ('admin.westminster_const', 'people', '{"en":"Westminster parliamentary constituency"}', false, NULL, 'uk.os.boundary_line'),
    ('admin.ward', 'people', '{"en":"Electoral ward"}', false, NULL, 'uk.os.boundary_line'),
    ('admin.parish', 'people', '{"en":"Parish / community"}', false, NULL, 'uk.os.boundary_line'),
    ('admin.county_division', 'people', '{"en":"County electoral division"}', false, NULL, 'uk.os.boundary_line')
ON CONFLICT (code) DO UPDATE SET category_code = EXCLUDED.category_code, name_i18n = EXCLUDED.name_i18n,
    is_hazard = EXCLUDED.is_hazard, level_scale = EXCLUDED.level_scale, dataset_id = EXCLUDED.dataset_id;
UPDATE ops.dataset SET loader_module = 'get-data/uk/sources/environment.py:EaReservoirWms' WHERE id = 'uk.ea.reservoir_flood';

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, level_scale, dataset_id) VALUES
    ('admin.built_up_area', 'people', '{"en":"Built-up area"}', false, NULL, 'uk.os.built_up_areas')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------- lấp khoảng trống đợt 2 (GPPS, HMLR, DWP, NRW nước mặt, planning) -----
INSERT INTO ops.licence (code, name, url, allows_commercial, requires_attribution, is_share_alike, notes) VALUES
    ('HMLR-LPD', 'HM Land Registry Use land and property data licences (CCOD, OCOD, Registered Leases)',
     'https://use-land-property-data.service.gov.uk/', true, true, false,
     'Ký licence theo từng dataset trên web; CCOD/OCOD miễn phí; Registered Leases freemium (xem điều khoản trước khi hiển thị công khai)')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url, notes = EXCLUDED.notes;

INSERT INTO ops.data_source (id, market_code, name, publisher, homepage_url, licence_code, attribution_text, terms_url, terms_notes) VALUES
    ('uk.gpps', 'uk', 'GP Patient Survey', 'NHS England (Ipsos)', 'https://www.gp-patient.co.uk/', 'OGL-UK-3.0',
     'GP Patient Survey, NHS England / Ipsos. Contains public sector information licensed under the Open Government Licence v3.0.', NULL,
     'Kết quả có trọng số; phòng khám có ít phản hồi có khoảng tin cậy rộng'),
    ('uk.hmlr_lpd', 'uk', 'HM Land Registry: Use land and property data', 'HM Land Registry',
     'https://use-land-property-data.service.gov.uk/', 'HMLR-LPD',
     'Information produced by HM Land Registry. © Crown copyright [year].',
     'https://use-land-property-data.service.gov.uk/', 'Licence CCOD/OCOD điều 3.2: địa chỉ (AddressBase/PAF) chỉ dùng phi thương mại → chỉ hiển thị thống kê theo khu, không hiển thị địa chỉ từng căn; điều 4.1: HMLR có quyền audit, phải giữ End-User Records; không marketing trực tiếp chủ sở hữu'),
    ('uk.dwp', 'uk', 'DWP Stat-Xplore', 'Department for Work and Pensions', 'https://stat-xplore.dwp.gov.uk/', 'OGL-UK-3.0',
     'Contains public sector information licensed under the Open Government Licence v3.0 (DWP Stat-Xplore).', NULL,
     'Số liệu LSOA được DWP làm tròn/nhiễu nhẹ để bảo mật')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, homepage_url = EXCLUDED.homepage_url, licence_code = EXCLUDED.licence_code,
    attribution_text = EXCLUDED.attribution_text, terms_url = EXCLUDED.terms_url, terms_notes = EXCLUDED.terms_notes;

INSERT INTO ops.dataset (id, source_id, name, update_frequency, native_level, coverage, loader_module) VALUES
    ('uk.nhs.gpps',               'uk.gpps',     'GP Patient Survey (practice level)',              'annual',     NULL,   'England', 'get-data/uk/sources/extra2.py:GpPatientSurvey'),
    ('uk.land_registry.ccod',     'uk.hmlr_lpd', 'UK companies that own property (CCOD)',           'monthly',    'postcode_unit', 'E&W', 'get-data/uk/sources/extra2.py:HmlrDataset'),
    ('uk.land_registry.ocod',     'uk.hmlr_lpd', 'Overseas companies that own property (OCOD)',     'monthly',    'postcode_unit', 'E&W', 'get-data/uk/sources/extra2.py:HmlrDataset'),
    ('uk.land_registry.leases',   'uk.hmlr_lpd', 'Registered Leases',                               'monthly',    NULL,   'E&W',     'get-data/uk/sources/extra2.py:HmlrDataset'),
    ('uk.dwp.uc_people',          'uk.dwp',      'People on Universal Credit (LSOA)',               'monthly',    'lsoa', 'GB',      'get-data/uk/sources/extra2.py:DwpUniversalCredit'),
    ('uk.nrw.rofsw',              'uk.nrw',      'Flood risk from surface water and small watercourses (Wales)', 'irregular', NULL, 'Wales', 'get-data/uk/sources/rofsw.py:NrwRofsw')
ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id, name = EXCLUDED.name, update_frequency = EXCLUDED.update_frequency,
    native_level = EXCLUDED.native_level, coverage = EXCLUDED.coverage, loader_module = EXCLUDED.loader_module;

INSERT INTO core.zone_type (code, category_code, name_i18n, is_hazard, level_scale, dataset_id) VALUES
    ('heritage.at_risk', 'planning', '{"en":"Heritage at Risk Register site"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('heritage.listed_outline', 'planning', '{"en":"Listed building outline"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('heritage.locally_listed', 'planning', '{"en":"Locally listed building"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('planning.open_space', 'planning', '{"en":"Designated open space (local plan)"}', false, NULL, 'uk.mhclg.planning_data_extra'),
    ('planning.local_plan_area', 'planning', '{"en":"Local plan area"}', false, NULL, 'uk.mhclg.planning_data_extra')
ON CONFLICT (code) DO UPDATE SET category_code = EXCLUDED.category_code, name_i18n = EXCLUDED.name_i18n,
    is_hazard = EXCLUDED.is_hazard, level_scale = EXCLUDED.level_scale, dataset_id = EXCLUDED.dataset_id;

INSERT INTO core.poi_type (code, parent_code, name_i18n, is_searchable, has_pages, url_segment) VALUES
    ('planning', NULL, '{"en":"Planning"}', false, false, NULL),
    ('planning.brownfield_site', 'planning', '{"en":"Brownfield land register site"}', false, false, NULL)
ON CONFLICT (code) DO NOTHING;

COMMIT;
