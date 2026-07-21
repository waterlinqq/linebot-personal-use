from __future__ import annotations

import sys
import threading
import time
from collections import deque

from server.connector.base import IncomingMessage, LineConnector, MessageHandler
from server.connector.line_win.com_init import uiautomation_thread_context
from server.connector.line_win.types import ChatLineMessage
from server.connector.line_win.ui import LineUIClient

CONNECTOR_VERSION = "2.1"


class LineWinConnector(LineConnector):
    """Windows LINE.exe UI 自動化連接器。"""

    def __init__(
        self,
        ui_client: LineUIClient | None = None,
        poll_interval: float = 0.35,
        history_size: int = 300,
    ) -> None:
        if ui_client is None and sys.platform != "win32":
            raise RuntimeError("LineWinConnector 僅能在 Windows 上使用，Mac 請用 mock")

        self._ui = ui_client
        self._poll_interval = poll_interval
        self._history_size = history_size
        self._running = False
        self._thread: threading.Thread | None = None
        self._handler: MessageHandler | None = None
        self._group_name = ""
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._last_error = ""
        self._connected = False
        self._last_poll_at = ""

    @property
    def connector_type(self) -> str:
        return "line_win"

    def start_monitoring(self, group_name: str, on_message: MessageHandler) -> None:
        if self._running:
            return

        self._group_name = group_name
        self._handler = on_message
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="linebot-uia-thread",
            daemon=True,
        )
        self._thread.start()

    def stop_monitoring(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self._connected = False

    def send_message(self, text: str) -> None:
        if self._ui is None:
            raise RuntimeError("LINE UI 尚未在監控執行緒就緒")
        self._ui.send_text(text)

    def is_connected(self) -> bool:
        return self._running and self._connected

    def get_diagnostics(self) -> dict:
        diagnostics = (
            self._ui.get_diagnostics()
            if self._ui is not None
            else {
                "window_found": False,
                "window_name": "",
                "last_error": "",
            }
        )
        diagnostics.update(
            {
                "connector_version": CONNECTOR_VERSION,
                "running": self._running,
                "connected": self._connected,
                "group_name": self._group_name,
                "seen_count": len(self._seen),
                "last_poll_at": self._last_poll_at,
                "last_error": self._last_error or diagnostics.get("last_error", ""),
                "monitor_thread": self._thread.name if self._thread else "",
            }
        )
        return diagnostics

    def _poll_loop(self) -> None:
        try:
            if sys.platform == "win32":
                with uiautomation_thread_context():
                    if self._ui is None:
                        from server.connector.line_win.ui_automation import WinLineUIClient

                        self._ui = WinLineUIClient()
                    self._run_poll_loop()
                return

            if self._ui is None:
                raise RuntimeError("缺少 UI client")
            self._run_poll_loop()
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._running = False
            self._connected = False

    def _run_poll_loop(self) -> None:
        if self._ui is None or not self._ui.connect():
            self._last_error = (
                self._ui.get_diagnostics().get("last_error", "連線失敗")
                if self._ui
                else "LINE UI 未初始化"
            )
            self._running = False
            return

        # 初始化：忽略啟動前已存在的訊息（使用者需先手動開啟目標群組）
        for message in self._ui.read_visible_messages():
            self._remember(message)

        self._connected = True

        while self._running:
            self._last_poll_at = time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                for message in self._ui.read_visible_messages():
                    if not self._remember(message):
                        continue
                    if self._handler:
                        self._handler(
                            IncomingMessage(
                                text=message.text,
                                sender=message.sender,
                            )
                        )
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                self._connected = False

            time.sleep(self._poll_interval)

    def _remember(self, message: ChatLineMessage) -> bool:
        fingerprint = message.fingerprint or message.text
        if fingerprint in self._seen:
            return False

        self._seen_order.append(fingerprint)
        self._seen.add(fingerprint)
        while len(self._seen_order) > self._history_size:
            old = self._seen_order.popleft()
            self._seen.discard(old)
        return True
