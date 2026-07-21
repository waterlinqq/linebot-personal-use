from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod

from server.connector.line_win.types import ChatLineMessage

# 過濾 LINE UI 雜訊（時間、日期分隔、系統提示）
NOISE_PATTERNS = (
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^\d{4}/\d{1,2}/\d{1,2}"),
    re.compile(r"^(今天|昨天|星期一|星期二|星期三|星期四|星期五|星期六|星期日)"),
    re.compile(r"^(您已加入|已變更|已收回|訊息已收回)"),
)


def message_fingerprint(text: str, sender: str = "") -> str:
    normalized = f"{sender.strip()}|{text.strip()}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def is_noise_message(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) <= 1:
        return True
    if stripped in {"接", "收", "👌", "👋"}:
        return False
    for pattern in NOISE_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


class LineUIClient(ABC):
    @abstractmethod
    def connect(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def read_visible_messages(self) -> list[ChatLineMessage]:
        raise NotImplementedError

    @abstractmethod
    def send_text(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_diagnostics(self) -> dict:
        raise NotImplementedError
