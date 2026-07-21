from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    text: str
    sender: str = ""
    timestamp: str = ""


MessageHandler = Callable[[IncomingMessage], None]


class LineConnector(ABC):
    @abstractmethod
    def start_monitoring(self, group_name: str, on_message: MessageHandler) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop_monitoring(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_message(self, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def connector_type(self) -> str:
        raise NotImplementedError
