from __future__ import annotations

import sys
from typing import Any

from server.connector.line_win.types import ChatLineMessage
from server.connector.line_win.ui import LineUIClient, is_noise_message, message_fingerprint

LINE_PROCESS_NAMES = {"line.exe"}


def get_process_name(process_id: int) -> str:
    import psutil

    try:
        return psutil.Process(process_id).name().lower()
    except (psutil.Error, OSError):
        return ""


def is_line_process(process_id: int) -> bool:
    return get_process_name(process_id) in LINE_PROCESS_NAMES


class WinLineUIClient(LineUIClient):
    """透過 Windows UI Automation 操作 LINE.exe。"""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WinLineUIClient 僅能在 Windows 上使用")
        self._window: Any = None
        self._last_error = ""
        self._auto_module: Any = None
        self._window_name = ""
        self._process_id = 0
        self._process_name = ""

    @property
    def _auto(self) -> Any:
        if self._auto_module is None:
            import uiautomation as auto  # type: ignore[import-untyped]

            self._auto_module = auto
        return self._auto_module

    def connect(self) -> bool:
        self._window = self._find_line_window()
        if self._window is None:
            self._last_error = "找不到 LINE 視窗，請確認 LINE 桌面版已開啟"
            return False
        try:
            self._window.SetFocus()
            self._window_name = self._window.Name or ""
            self._process_id = int(self._window.ProcessId)
            self._process_name = get_process_name(self._process_id)
            self._last_error = ""
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"無法聚焦 LINE 視窗: {exc}"
            return False

    def read_visible_messages(self) -> list[ChatLineMessage]:
        if not self._window and not self.connect():
            return []

        assert self._window is not None
        messages: list[ChatLineMessage] = []
        seen: set[str] = set()

        try:
            for control in self._iter_message_controls(self._window):
                text = (control.Name or "").strip()
                if is_noise_message(text):
                    continue
                fingerprint = message_fingerprint(text)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                messages.append(
                    ChatLineMessage(
                        text=text,
                        sender="",
                        fingerprint=fingerprint,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"讀取訊息失敗: {exc}"
            return messages

        return messages

    def send_text(self, text: str) -> None:
        if not self._window and not self.connect():
            raise RuntimeError(self._last_error or "LINE 未連線")

        assert self._window is not None
        edit = self._find_message_input(self._window)
        if edit is None:
            raise RuntimeError("找不到訊息輸入框")

        edit.SetFocus()
        edit.SendKeys(text, waitTime=0)
        edit.SendKeys("{Enter}", waitTime=0)

    def get_diagnostics(self) -> dict:
        return {
            "platform": sys.platform,
            "window_found": self._window is not None,
            "window_name": self._window_name,
            "process_id": self._process_id,
            "process_name": self._process_name,
            "last_error": self._last_error,
        }

    def _find_line_window(self) -> Any | None:
        root = self._auto.GetRootControl()
        candidates = []
        for control in root.GetChildren():
            if control.ControlType != self._auto.ControlType.WindowControl:
                continue
            if is_line_process(int(control.ProcessId)):
                candidates.append(control)

        if not candidates:
            return None

        # LINE.exe 可能同時有登入或聊天視窗，優先選標題較完整者。
        candidates.sort(key=lambda item: len(item.Name or ""), reverse=True)
        return candidates[0]

    def _find_message_input(self, window: Any) -> Any | None:
        edits = window.GetChildren()
        queue = list(edits)
        found: list[Any] = []
        while queue:
            current = queue.pop(0)
            try:
                if current.ControlType == self._auto.ControlType.EditControl:
                    found.append(current)
            except Exception:  # noqa: BLE001
                pass
            try:
                queue.extend(current.GetChildren())
            except Exception:  # noqa: BLE001
                continue

        if not found:
            return None

        # 通常輸入框是距離底部最近的 EditControl
        found.sort(key=lambda item: getattr(item.BoundingRectangle, "bottom", 0), reverse=True)
        return found[0]

    def _iter_message_controls(self, window: Any) -> list[Any]:
        text_controls: list[Any] = []
        list_items: list[Any] = []
        queue = [window]
        while queue:
            current = queue.pop(0)
            try:
                control_type = current.ControlType
            except Exception:  # noqa: BLE001
                continue

            name = (current.Name or "").strip()
            if name:
                if control_type == self._auto.ControlType.TextControl:
                    text_controls.append(current)
                elif control_type == self._auto.ControlType.ListItemControl:
                    list_items.append(current)

            try:
                queue.extend(current.GetChildren())
            except Exception:  # noqa: BLE001
                continue

        # ListItem 優先（較像聊天列），否則退回 TextControl
        candidates = list_items or text_controls
        candidates.sort(
            key=lambda item: getattr(item.BoundingRectangle, "top", 0),
        )
        return candidates[-30:]
