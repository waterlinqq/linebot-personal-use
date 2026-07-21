from __future__ import annotations

import sys
import time

import pytest

from server.connector.base import IncomingMessage
from server.connector.factory import create_connector
from server.connector.line_win.connector import LineWinConnector
from server.connector.line_win.types import ChatLineMessage
from server.connector.line_win.ui import LineUIClient, message_fingerprint


class FakeLineUIClient(LineUIClient):
    def __init__(self) -> None:
        self.messages: list[ChatLineMessage] = []
        self.sent: list[str] = []
        self.connected = True
        self.last_error = ""

    def connect(self) -> bool:
        self.connected = True
        return True

    def read_visible_messages(self) -> list[ChatLineMessage]:
        current, self.messages = self.messages, []
        return current

    def send_text(self, text: str) -> None:
        self.sent.append(text)

    def get_diagnostics(self) -> dict:
        return {
            "window_found": True,
            "window_name": "LINE",
            "last_error": self.last_error,
        }

    def push_message(self, text: str) -> None:
        self.messages.append(
            ChatLineMessage(
                text=text,
                fingerprint=message_fingerprint(text),
            )
        )


def test_line_win_connector_polls_new_messages() -> None:
    ui = FakeLineUIClient()
    connector = LineWinConnector(ui_client=ui, poll_interval=0.05)
    received: list[IncomingMessage] = []

    connector.start_monitoring("測試群組", lambda msg: received.append(msg))
    time.sleep(0.05)

    ui.push_message("07.03 14:00 小港 小港 5300")
    time.sleep(0.2)

    connector.stop_monitoring()
    assert len(received) == 1
    assert received[0].text == "07.03 14:00 小港 小港 5300"


def test_line_win_connector_dedupes_messages() -> None:
    ui = FakeLineUIClient()
    connector = LineWinConnector(ui_client=ui, poll_interval=0.05)
    received: list[IncomingMessage] = []

    connector.start_monitoring("測試群組", lambda msg: received.append(msg))
    time.sleep(0.05)

    ui.push_message("07.03 14:00 小港 小港 5300")
    time.sleep(0.15)
    ui.push_message("07.03 14:00 小港 小港 5300")
    time.sleep(0.15)

    connector.stop_monitoring()
    assert len(received) == 1


def test_line_win_connector_send_message() -> None:
    ui = FakeLineUIClient()
    connector = LineWinConnector(ui_client=ui)
    connector.send_message("接")
    assert ui.sent == ["接"]


def test_factory_mock_on_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    connector = create_connector("auto")
    assert connector.connector_type == "mock"


def test_factory_line_win_mode_uses_stub_ui() -> None:
    ui = FakeLineUIClient()
    connector = LineWinConnector(ui_client=ui)
    assert connector.connector_type == "line_win"
