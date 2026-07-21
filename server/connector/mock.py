from __future__ import annotations

import threading
import time
from collections.abc import Iterable

from server.connector.base import IncomingMessage, LineConnector, MessageHandler


class MockConnector(LineConnector):
    """Mac 開發用：餵入假訊息測試完整流程。"""

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._handler: MessageHandler | None = None
        self._queue: list[IncomingMessage] = []
        self._sent: list[str] = []

    @property
    def connector_type(self) -> str:
        return "mock"

    def enqueue_messages(self, messages: Iterable[IncomingMessage]) -> None:
        self._queue.extend(messages)

    @property
    def sent_messages(self) -> list[str]:
        return list(self._sent)

    def start_monitoring(self, group_name: str, on_message: MessageHandler) -> None:
        self._handler = on_message
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            if self._queue and self._handler:
                message = self._queue.pop(0)
                self._handler(message)
            time.sleep(0.05)

    def stop_monitoring(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def send_message(self, text: str) -> None:
        self._sent.append(text)

    def is_connected(self) -> bool:
        return self._running

    def inject_message(self, text: str, sender: str = "測試") -> None:
        if self._handler and self._running:
            self._handler(IncomingMessage(text=text, sender=sender))
        else:
            self._queue.append(IncomingMessage(text=text, sender=sender))
