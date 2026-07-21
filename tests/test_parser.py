import pytest

from server.engine.parser import parse_message


@pytest.mark.parametrize(
    "text,expected_order",
    [
        ("07.04 8.00 三峽 蘆洲 4100", True),
        ("07.03 14:00 桃園 大園 3500", True),
        ("07.03 台南 台南 4100配合時間折500", True),
        ("7.13配合时间 鳥松區-三民區 3000", True),
        ("07/2 10點 高雄台南 6000", True),
        ("07.01 15:00 歸仁 歸仁 3000", True),
        ("07.03 14:00 小港 小港 5300", True),
        ("三民到三民 4800", True),
        ("07.04 下午3點 嘉義 嘉義 4700 2➕", True),
        ("接", False),
        ("收", False),
        ("👌", False),
        ("有地址嗎？", False),
        ("@辰（客服） 去改時間", False),
        ("收到", False),
        ("快包3500", False),
    ],
)
def test_parse_message_order_detection(text: str, expected_order: bool) -> None:
    parsed = parse_message(text)
    assert parsed.is_order is expected_order


def test_parse_message_extracts_price_and_locations() -> None:
    parsed = parse_message("07.01 15:00 歸仁 歸仁 3000")
    assert parsed.is_order is True
    assert parsed.price == 3000
    assert parsed.origin == "歸仁"
    assert parsed.destination == "歸仁"
