from __future__ import annotations

import os

from server.connector.base import LineConnector
from server.connector.mock import MockConnector


def create_connector(mode: str | None = None) -> LineConnector:
    selected = (mode or os.environ.get("LINEBOT_CONNECTOR", "auto")).lower()

    if selected == "mock":
        return MockConnector()

    if selected == "ocr":
        from server.connector.ocr import OcrConnector

        return OcrConnector()

    if selected == "line_win":
        from server.connector.line_win import LineWinConnector

        return LineWinConnector()

    if selected == "auto" and os.environ.get("LINEBOT_OCR_REGION"):
        from server.connector.ocr import OcrConnector

        return OcrConnector()

    return MockConnector()
