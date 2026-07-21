import pytest

from server.connector.line_win.com_init import uiautomation_thread_context


def test_uiautomation_thread_context_is_noop_off_windows() -> None:
    with uiautomation_thread_context() as auto:
        assert auto is None
