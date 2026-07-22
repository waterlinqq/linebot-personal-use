from server.config import load_config_with_regions, load_default_config
from server.connector.mock import MockConnector
from server.core.bot import BotService


SOUTHERN_COUNTIES = ["嘉義", "台南", "高雄", "屏東"]


def _make_bot(connector):
    bot = BotService(load_default_config(), connector=connector)
    bot.update_config(load_config_with_regions(SOUTHERN_COUNTIES))
    return bot


def test_bot_replies_for_southern_order() -> None:
    connector = MockConnector()
    bot = _make_bot(connector)
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
    bot = _make_bot(connector)
    bot.start("測試群組")

    connector.inject_message("07.04 8.00 三峽 蘆洲 4100", sender="辰（客服）")

    assert connector.sent_messages == []
    logs = bot.get_logs(limit=1)
    assert logs[0]["should_reply"] is False
    assert logs[0]["replied"] is False

    bot.stop()


def test_evaluate_endpoint_logic() -> None:
    bot = _make_bot(MockConnector())
    result = bot.evaluate_text("07.01 15:00 歸仁 歸仁 3000")
    assert result["is_order"] is True
    assert result["should_reply"] is True
    assert "台南" in result["matched_regions"]


def test_reply_failure_is_logged_without_stopping_bot() -> None:
    class FailingConnector(MockConnector):
        def send_message(self, text: str) -> None:
            raise RuntimeError("沒有輔助使用權限")

    connector = FailingConnector()
    bot = _make_bot(connector)
    bot.start("測試群組")

    connector.inject_message("關廟 柳營 5000")

    assert bot.status.running is True
    assert bot.status.replied_count == 0
    assert bot.status.last_action.startswith("reply_failed:")
    log = bot.get_logs(limit=1)[0]
    assert log["should_reply"] is True
    assert log["replied"] is False
    assert log["reason"].startswith("reply_failed:")

    bot.stop()


def test_semantic_duplicate_order_replies_only_once() -> None:
    connector = MockConnector()
    bot = _make_bot(connector)
    bot.start("測試群組")

    connector.inject_message("15:40 wei 高雄 台南 3000")
    connector.inject_message("15:40 wei 高 雄 台 南 3000")
    connector.inject_message("高雄 台南 3000")

    assert connector.sent_messages == ["接"]
    assert bot.status.replied_count == 1
    assert bot.status.duplicates_suppressed == 2
    latest_logs = bot.get_logs(limit=3)
    assert sum(log["replied"] for log in latest_logs) == 1
    assert sum(
        log["reason"] == "duplicate_suppressed"
        for log in latest_logs
    ) == 2

    bot.stop()


def test_same_order_at_different_times_can_reply_again() -> None:
    connector = MockConnector()
    bot = _make_bot(connector)
    bot.start("測試群組")

    connector.inject_message("15:40 wei 高雄 台南 3000")
    connector.inject_message("15:41 wei 高雄 台南 3000")

    assert connector.sent_messages == ["接", "接"]
    assert bot.status.replied_count == 2

    bot.stop()
