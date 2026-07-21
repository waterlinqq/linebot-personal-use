from server.config import load_default_config
from server.connector.mock import MockConnector
from server.core.bot import BotService


def test_bot_replies_for_southern_order() -> None:
    connector = MockConnector()
    bot = BotService(load_default_config(), connector=connector)
    bot.start("測試群組")

    connector.inject_message("07.03 14:00 小港 小港 5300", sender="不明")

    assert connector.sent_messages == ["接"]
    logs = bot.get_logs(limit=1)
    assert len(logs) == 1
    assert logs[0]["should_reply"] is True
    assert logs[0]["replied"] is True
    assert "高雄" in logs[0]["matched_regions"]

    bot.stop()


def test_bot_skips_northern_order() -> None:
    connector = MockConnector()
    bot = BotService(load_default_config(), connector=connector)
    bot.start("測試群組")

    connector.inject_message("07.04 8.00 三峽 蘆洲 4100", sender="辰（客服）")

    assert connector.sent_messages == []
    logs = bot.get_logs(limit=1)
    assert logs[0]["should_reply"] is False
    assert logs[0]["replied"] is False

    bot.stop()


def test_evaluate_endpoint_logic() -> None:
    bot = BotService(load_default_config(), connector=MockConnector())
    result = bot.evaluate_text("07.01 15:00 歸仁 歸仁 3000")
    assert result["is_order"] is True
    assert result["should_reply"] is True
    assert "台南" in result["matched_regions"]
