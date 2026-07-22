import pytest

from server.config import (
    build_regions_from_selection,
    flatten_all_keywords,
    flatten_region,
    infer_region_selection,
    infer_selection,
    load_config_with_regions,
    load_default_config,
    load_region_catalog,
    merge_region_keywords,
    resolve_startup_config,
)
from server.engine.matcher import MatchConfig, RegionMatcher
from server.engine.parser import parse_message

SOUTHERN_COUNTIES = ["嘉義", "台南", "高雄", "屏東"]

SOUTHERN_SAMPLES = [
    ("關廟 柳營 5000", ["台南"]),
    ("07.01 15:00 歸仁 歸仁 3000", ["台南"]),
    ("07.18 13:00 新市 善化3500", ["台南"]),
    ("07.06 12.30-15.30 臺南北區 七股 3800", ["台南"]),
    ("07.03 14:00 小港 小港 5300", ["高雄"]),
    ("7.13配合时间 鳥松區-三民區 3000", ["高雄"]),
    ("07.10 13.00 三民 前鎮 3200", ["高雄"]),
    ("07.23 14:30 前鎮 前金3500+1000", ["高雄"]),
    ("07.04 下午3點 嘉義 嘉義 4700 2➕", ["嘉義"]),
    ("07.12 9:30 大寮 東區 4500", ["高雄", "台南"]),
]

NORTHERN_SAMPLES = [
    "07.04 8.00 三峽 蘆洲 4100",
    "07.01 14:00 淡水 淡水 3000",
    "07.06 11:00 板橋 板橋 4500",
    "07.03 10.00 宜蘭 臺北 8500",
]


@pytest.fixture
def catalog():
    return load_region_catalog()


@pytest.fixture
def matcher() -> RegionMatcher:
    catalog = load_region_catalog()
    return RegionMatcher(
        load_config_with_regions(SOUTHERN_COUNTIES),
        known_keywords=flatten_all_keywords(catalog),
    )


@pytest.mark.parametrize("text,expected_regions", SOUTHERN_SAMPLES)
def test_southern_districts_match(matcher: RegionMatcher, text: str, expected_regions: list[str]) -> None:
    parsed = parse_message(text)
    assert parsed.is_order is True, f"應判定為派單: {text} ({parsed.reason})"
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
        locations=parsed.locations,
    )
    assert result.should_reply is True, f"應接單: {text} ({result.reason})"
    for region in expected_regions:
        assert region in result.matched_regions, f"{text} 應匹配 {region}"


@pytest.mark.parametrize("text", NORTHERN_SAMPLES)
def test_northern_orders_do_not_match(matcher: RegionMatcher, text: str) -> None:
    parsed = parse_message(text)
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
        locations=parsed.locations,
    )
    assert result.should_reply is False, f"不應接單: {text}"


def test_default_config_has_no_regions() -> None:
    config = load_default_config()
    assert config.regions == {}


def test_catalog_covers_southern_counties(catalog) -> None:
    for county in SOUTHERN_COUNTIES:
        assert county in catalog
        assert len(catalog[county]["districts"]) >= 20


def test_catalog_has_taiwan_counties(catalog) -> None:
    assert len(catalog) == 20
    assert "台北" in catalog
    assert "新北" in catalog
    assert "連江" in catalog


def test_southern_keywords_present(catalog) -> None:
    tainan = flatten_region(catalog["台南"], None)
    kaohsiung = flatten_region(catalog["高雄"], None)
    assert "關廟" in tainan
    assert "柳營" in tainan
    assert "新市" in tainan
    assert "前金" in kaohsiung


def test_resolve_startup_config_empty_when_no_stored(catalog) -> None:
    defaults = load_default_config()
    resolved = resolve_startup_config(None, defaults, catalog)
    assert resolved.regions == {}


def test_merge_region_keywords_keeps_custom_and_adds_defaults(catalog) -> None:
    stored = MatchConfig(
        regions={"台南": ["關廟", "自訂區"]},
        reply_text="接",
    )
    merged = merge_region_keywords(stored, catalog)
    assert "關廟" in merged.regions["台南"]
    assert "關廟區" in merged.regions["台南"]
    assert "自訂區" in merged.regions["台南"]
    assert "台南" in merged.regions["台南"]
    assert "柳營" not in merged.regions["台南"]
    assert "高雄" not in merged.regions


def test_merge_region_keywords_empty_stored_regions(catalog) -> None:
    stored = MatchConfig(regions={}, reply_text="接")
    merged = merge_region_keywords(stored, catalog)
    assert merged.regions == {}


def test_partial_district_selection(catalog) -> None:
    regions = build_regions_from_selection(catalog, {"台南": ["關廟", "柳營"]})
    matcher = RegionMatcher(
        MatchConfig(regions=regions, reply_text="接"),
        known_keywords=flatten_all_keywords(catalog),
    )

    guanmiao = matcher.match(
        is_order=True,
        raw_text="關廟 柳營 5000",
        origin="關廟",
        destination="柳營",
        price=5000,
        locations=["關廟", "柳營"],
    )
    assert guanmiao.should_reply is True
    assert "台南" in guanmiao.matched_regions

    xinshi = matcher.match(
        is_order=True,
        raw_text="07.18 13:00 新市 善化3500",
        origin="新市",
        destination="善化",
        price=3500,
        locations=["新市", "善化"],
    )
    assert xinshi.should_reply is False


def test_northern_county_matches_when_enabled(catalog) -> None:
    regions = build_regions_from_selection(catalog, {"新北": None})
    matcher = RegionMatcher(
        MatchConfig(regions=regions, reply_text="接"),
        known_keywords=flatten_all_keywords(catalog),
    )
    parsed = parse_message("07.06 11:00 板橋 板橋 4500")
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text="07.06 11:00 板橋 板橋 4500",
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
        locations=parsed.locations,
    )
    assert result.should_reply is True
    assert "新北" in result.matched_regions


def test_infer_region_selection_all_county(catalog) -> None:
    regions = build_regions_from_selection(catalog, {"台南": None})
    selection = infer_region_selection(regions, catalog)
    assert selection["台南"] is None


def test_infer_region_selection_partial_county(catalog) -> None:
    regions = build_regions_from_selection(catalog, {"台南": ["關廟", "柳營"]})
    selection = infer_region_selection(regions, catalog)
    assert set(selection["台南"]) == {"關廟", "柳營"}


def test_infer_selection_detects_partial_districts(catalog) -> None:
    keywords = flatten_region(catalog["台南"], ["關廟"])
    all_selected, selected = infer_selection(keywords, catalog["台南"])
    assert all_selected is False
    assert selected == ["關廟"]


def test_invalid_destination_is_rejected(catalog) -> None:
    matcher = RegionMatcher(
        load_config_with_regions(["台南"]),
        known_keywords=flatten_all_keywords(catalog),
    )
    result = matcher.match(
        is_order=True,
        raw_text="台南 1500 發生地震",
        origin="台南",
        destination="發生地震",
        price=1500,
        locations=["台南", "發生地震"],
    )
    assert result.should_reply is False
    assert result.reason == "invalid_destination"
