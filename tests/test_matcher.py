import pytest

from server.config import flatten_all_keywords, load_config_with_regions, load_region_catalog
from server.engine.matcher import MatchConfig, RegionMatcher
from server.engine.parser import parse_message


SOUTHERN_COUNTIES = ["嘉義", "台南", "高雄", "屏東"]


@pytest.fixture
def matcher() -> RegionMatcher:
    catalog = load_region_catalog()
    return RegionMatcher(
        load_config_with_regions(SOUTHERN_COUNTIES),
        known_keywords=flatten_all_keywords(catalog),
    )


@pytest.mark.parametrize(
    "text,should_reply,regions",
    [
        ("07.03 台南 台南 4100配合時間折500", True, ["台南"]),
        ("07.01 15:00 歸仁 歸仁 3000", True, ["台南"]),
        ("7.13配合时间 鳥松區-三民區 3000", True, ["高雄"]),
        ("07.03 14:00 小港 小港 5300", True, ["高雄"]),
        ("07.04 8.00 三峽 蘆洲 4100", False, []),
        ("07.01 14:00 淡水 淡水 3000", False, []),
        ("07.04 下午3點 嘉義 嘉義 4700 2➕", True, ["嘉義"]),
        ("台南 1500 發生地震", False, []),
        ("接", False, []),
    ],
)
def test_region_matching(
    matcher: RegionMatcher,
    text: str,
    should_reply: bool,
    regions: list[str],
) -> None:
    parsed = parse_message(text)
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
        locations=parsed.locations,
    )
    assert result.should_reply is should_reply
    if should_reply:
        for region in regions:
            assert region in result.matched_regions


def test_exclude_keywords() -> None:
    catalog = load_region_catalog()
    config = load_config_with_regions(SOUTHERN_COUNTIES)
    config.exclude_keywords = ["人力"]
    matcher = RegionMatcher(config, known_keywords=flatten_all_keywords(catalog))
    text = "07.04 13:00 龜山 人力 1小時3000"
    parsed = parse_message(text)
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
        locations=parsed.locations,
    )
    assert result.should_reply is False
    assert result.reason.startswith("excluded_by_keyword")


def test_invalid_destination_not_matched(matcher: RegionMatcher) -> None:
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


def test_region_matching_ignores_ocr_spaces() -> None:
    catalog = load_region_catalog()
    matcher = RegionMatcher(
        load_config_with_regions(["台南"]),
        known_keywords=flatten_all_keywords(catalog),
    )
    text = "關 廟 柳 營 5000"
    parsed = parse_message(text)
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
        locations=parsed.locations,
    )
    assert parsed.is_order is True
    assert result.should_reply is True
    assert "台南" in result.matched_regions
