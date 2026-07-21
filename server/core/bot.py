from __future__ import annotations

import threading
from dataclasses import dataclass, field

from server.config import load_default_config, merge_region_keywords, resolve_startup_config
from server.connector.base import IncomingMessage, LineConnector
from server.connector.mock import MockConnector
from server.db.database import get_connection, init_db, insert_message_log, load_match_config, save_match_config
from server.engine.matcher import MatchConfig, RegionMatcher
from server.engine.parser import parse_message


@dataclass
class BotStatus:
    running: bool = False
    connector_type: str = "mock"
    group_name: str = ""
    processed_count: int = 0
    replied_count: int = 0
    duplicates_suppressed: int = 0
    last_action: str = ""


class BotService:
    def __init__(
        self,
        config: MatchConfig,
        connector: LineConnector | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._conn = get_connection()
        init_db(self._conn)

        stored = load_match_config(self._conn)
        defaults = config
        self.config = resolve_startup_config(stored, defaults)
        save_match_config(self._conn, self.config)

        self.matcher = RegionMatcher(self.config)
        self.connector = connector or MockConnector()
        self.status = BotStatus(connector_type=self.connector.connector_type)
        self._replied_order_signatures: set[str] = set()
        self._replied_untimed_signatures: set[str] = set()

    def get_config(self) -> MatchConfig:
        return self.config

    def update_config(self, config: MatchConfig) -> None:
        with self._lock:
            self.config = config
            self.matcher.update_config(config)
            save_match_config(self._conn, config)

    def reload_default_regions(self) -> MatchConfig:
        with self._lock:
            defaults = load_default_config()
            self.config = merge_region_keywords(self.config, defaults)
            self.matcher.update_config(self.config)
            save_match_config(self._conn, self.config)
            return self.config

    def start(self, group_name: str) -> BotStatus:
        with self._lock:
            if self.status.running:
                self.status.last_action = "already_running"
                return self.status

            self.status.group_name = group_name
            self._replied_order_signatures.clear()
            self._replied_untimed_signatures.clear()
            self.status.running = True
            self.status.last_action = "started"
            self.connector.start_monitoring(group_name, self._handle_message)
            return self.status

    def stop(self) -> BotStatus:
        with self._lock:
            if not self.status.running:
                self.status.last_action = "already_stopped"
                return self.status

            self.connector.stop_monitoring()
            self.status.running = False
            self.status.last_action = "stopped"
            return self.status

    def _handle_message(self, message: IncomingMessage) -> None:
        with self._lock:
            parsed = parse_message(message.text)
            match = self.matcher.match(
                is_order=parsed.is_order,
                raw_text=message.text,
                origin=parsed.origin,
                destination=parsed.destination,
                price=parsed.price,
            )

            replied = False
            reply_error = ""
            duplicate_suppressed = False
            if match.should_reply and self.status.running:
                reply_signature = self._reply_signature(
                    parsed.date,
                    parsed.time,
                    parsed.price,
                    match.matched_regions,
                    match.matched_keywords,
                )
                untimed_signature = self._reply_signature(
                    None,
                    None,
                    parsed.price,
                    match.matched_regions,
                    match.matched_keywords,
                )
                is_duplicate = (
                    reply_signature in self._replied_order_signatures
                    or (
                        parsed.time is None
                        and untimed_signature
                        in self._replied_untimed_signatures
                    )
                )
                if is_duplicate:
                    duplicate_suppressed = True
                    self.status.duplicates_suppressed += 1
                    self.status.last_action = (
                        f"duplicate_suppressed:{message.text[:40]}"
                    )
                else:
                    try:
                        self.connector.send_message(self.config.reply_text)
                        replied = True
                        self._replied_order_signatures.add(reply_signature)
                        self._replied_untimed_signatures.add(untimed_signature)
                        self.status.replied_count += 1
                        self.status.last_action = f"replied:{message.text[:40]}"
                    except Exception as exc:  # noqa: BLE001
                        reply_error = str(exc)
                        self.status.last_action = f"reply_failed:{reply_error[:100]}"

            self.status.processed_count += 1

            insert_message_log(
                self._conn,
                sender=message.sender,
                raw_text=message.text,
                is_order=parsed.is_order,
                should_reply=match.should_reply,
                replied=replied,
                matched_regions=match.matched_regions,
                reason=(
                    f"reply_failed:{reply_error}"
                    if reply_error
                    else (
                        "duplicate_suppressed"
                        if duplicate_suppressed
                        else (
                            match.reason
                            if match.should_reply
                            else parsed.reason or match.reason
                        )
                    )
                ),
            )

    @staticmethod
    def _reply_signature(
        date: str | None,
        message_time: str | None,
        price: int | None,
        regions: list[str],
        keywords: list[str],
    ) -> str:
        return "|".join(
            [
                date or "",
                message_time or "",
                str(price or 0),
                ",".join(sorted(regions)),
                ",".join(sorted(keywords)),
            ]
        )

    def evaluate_text(self, text: str) -> dict:
        parsed = parse_message(text)
        match = self.matcher.match(
            is_order=parsed.is_order,
            raw_text=text,
            origin=parsed.origin,
            destination=parsed.destination,
            price=parsed.price,
        )
        return {
            "text": text,
            "is_order": parsed.is_order,
            "parse_reason": parsed.reason,
            "origin": parsed.origin,
            "destination": parsed.destination,
            "price": parsed.price,
            "should_reply": match.should_reply,
            "matched_regions": match.matched_regions,
            "matched_keywords": match.matched_keywords,
            "match_reason": match.reason,
            "reply_text": self.config.reply_text if match.should_reply else None,
        }

    def get_logs(self, limit: int = 100) -> list[dict]:
        from server.db.database import list_message_logs

        return list_message_logs(self._conn, limit=limit)
