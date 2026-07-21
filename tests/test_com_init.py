import sys
from types import SimpleNamespace

import pytest

from server.connector.line_win.com_init import _reset_automation_client, uiautomation_thread_context


def test_uiautomation_thread_context_is_noop_off_windows() -> None:
    with uiautomation_thread_context() as auto:
        assert auto is None


def test_reset_automation_client_noop_when_missing() -> None:
    _reset_automation_client(SimpleNamespace())  # no _AutomationClient


def test_reset_automation_client_clears_instance() -> None:
    class Client:
        _instance = object()

    module = SimpleNamespace(_AutomationClient=Client)
    _reset_automation_client(module)
    assert Client._instance is None
