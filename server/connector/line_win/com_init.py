from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def uiautomation_thread_context() -> Iterator[Any]:
    """在背景執行緒初始化 COM + UIAutomation。"""
    if sys.platform != "win32":
        yield None
        return

    import uiautomation as auto

    # 若主執行緒曾建立過 COM client，清掉 singleton 讓此執行緒重建
    auto._AutomationClient._instance = None  # noqa: SLF001

    initializer = auto.UIAutomationInitializerInThread(debug=False)
    try:
        yield auto
    finally:
        initializer.Uninitialize()
