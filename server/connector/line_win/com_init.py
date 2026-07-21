from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Iterator


def _reset_automation_client(auto_module: Any) -> None:
    client_cls = getattr(auto_module, "_AutomationClient", None)
    if client_cls is not None:
        client_cls._instance = None


@contextmanager
def uiautomation_thread_context() -> Iterator[Any]:
    """在背景執行緒初始化 COM + UIAutomation。"""
    if sys.platform != "win32":
        yield None
        return

    import uiautomation as auto

    _reset_automation_client(auto)

    initializer = auto.UIAutomationInitializerInThread(debug=False)
    try:
        yield auto
    finally:
        initializer.Uninitialize()
