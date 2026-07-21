from __future__ import annotations

import os

from server.config import load_default_config
from server.connector.base import LineConnector
from server.connector.factory import create_connector
from server.core.bot import BotService

_bot_service: BotService | None = None


def init_bot_service(connector_mode: str = "auto", connector: LineConnector | None = None) -> BotService:
    global _bot_service
    os.environ["LINEBOT_CONNECTOR"] = connector_mode
    _bot_service = BotService(
        load_default_config(),
        connector=connector or create_connector(connector_mode),
    )
    return _bot_service


def get_bot_service() -> BotService:
    global _bot_service
    if _bot_service is None:
        _bot_service = init_bot_service()
    return _bot_service
