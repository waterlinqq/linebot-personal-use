import pytest

from server.config import load_default_config, merge_region_keywords, resolve_startup_config
from server.engine.matcher import MatchConfig, RegionMatcher
from server.engine.parser import parse_message

# 四縣市行政區抽樣（含先前遺漏、聊天紀錄曾出現者）
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
    ("07.12 9:30 大寮 東區 4500", ["高雄", "台南"]),  # 大寮+東區
]

NORTHERN_SAMPLES = [
    "07.04 8.00 三峽 蘆洲 4100",
    "07.01 14:00 淡水 淡水 3000",
    "07.06 11:00 板橋 板橋 4500",
    "07.03 10.00 宜蘭 臺北 8500",
]


@pytest.fixture
def matcher() -> RegionMatcher:
    return RegionMatcher(load_default_config())


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
    )
    assert result.should_reply is False, f"不應接單: {text}"


def test_default_regions_are_comprehensive() -> None:
    config = load_default_config()
    assert len(config.regions["嘉義"]) >= 20
    assert len(config.regions["台南"]) >= 50
    assert len(config.regions["高雄"]) >= 50
    assert len(config.regions["屏東"]) >= 30
    assert "關廟" in config.regions["台南"]
    assert "柳營" in config.regions["台南"]
    assert "新市" in config.regions["台南"]
    assert "前金" in config.regions["高雄"]


def test_merge_region_keywords_keeps_custom_and_adds_defaults() -> None:
    defaults = load_default_config()
    stored = MatchConfig(
        regions={"台南": ["關廟", "自訂區"]},
        reply_text="接",
    )
    merged = merge_region_keywords(stored, defaults)
    assert "關廟" in merged.regions["台南"]
    assert "自訂區" in merged.regions["台南"]
    assert "柳營" in merged.regions["台南"]


def test_resolve_startup_config_merges_when_stored_exists() -> None:
    defaults = load_default_config()
    stored = MatchConfig(regions={"台南": ["關廟"]}, reply_text="接")
    resolved = resolve_startup_config(stored, defaults)
    assert "柳營" in resolved.regions["台南"]
