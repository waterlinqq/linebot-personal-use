import pytest

from server.config import load_default_config
from server.engine.matcher import MatchConfig, RegionMatcher
from server.engine.parser import parse_message


@pytest.fixture
def matcher() -> RegionMatcher:
    return RegionMatcher(load_default_config())


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
    )
    assert result.should_reply is should_reply
    if should_reply:
        for region in regions:
            assert region in result.matched_regions


def test_exclude_keywords() -> None:
    config = load_default_config()
    config.exclude_keywords = ["人力"]
    matcher = RegionMatcher(config)
    text = "07.04 13:00 龜山 人力 1小時3000"
    parsed = parse_message(text)
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
    )
    assert result.should_reply is False
    assert result.reason.startswith("excluded_by_keyword")


def test_region_matching_ignores_ocr_spaces() -> None:
    matcher = RegionMatcher(load_default_config())
    text = "關 廟 柳 營 5000"
    parsed = parse_message(text)
    result = matcher.match(
        is_order=parsed.is_order,
        raw_text=text,
        origin=parsed.origin,
        destination=parsed.destination,
        price=parsed.price,
    )
    assert parsed.is_order is True
    assert result.should_reply is True
    assert "台南" in result.matched_regions
