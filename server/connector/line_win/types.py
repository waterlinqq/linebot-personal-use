from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatLineMessage:
    text: str
    sender: str = ""
    fingerprint: str = ""
