from __future__ import annotations

import os
import sys

from server.connector.base import LineConnector
from server.connector.mock import MockConnector


def create_connector(mode: str | None = None) -> LineConnector:
    selected = (mode or os.environ.get("LINEBOT_CONNECTOR", "auto")).lower()

    if selected == "mock":
        return MockConnector()

    if selected == "line_win":
        from server.connector.line_win import LineWinConnector

        return LineWinConnector()

    if selected == "auto" and sys.platform == "win32":
        from server.connector.line_win import LineWinConnector

        return LineWinConnector()

    return MockConnector()
