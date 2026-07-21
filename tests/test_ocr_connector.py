from __future__ import annotations

import time

import pytest

from server.connector.base import IncomingMessage
from server.connector.ocr import (
    OcrBlock,
    OcrConnector,
    ScreenPoint,
    ScreenRegion,
    find_message_bubble_boxes,
    normalize_ocr_text,
    ocr_fingerprint,
)


class FakeOcrSource:
    def __init__(self) -> None:
        self.blocks: list[OcrBlock] = []

    def read_blocks(self) -> list[OcrBlock]:
        return list(self.blocks)

    def set_texts(self, *texts: str) -> None:
        self.blocks = [
            OcrBlock(text=text, fingerprint=ocr_fingerprint(text))
            for text in texts
        ]


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_text(self, text: str) -> None:
        self.sent.append(text)


class SequenceOcrSource:
    def __init__(self, frames: list[list[str]]) -> None:
        self.frames = frames
        self.index = 0

    def read_blocks(self) -> list[OcrBlock]:
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return [
            OcrBlock(text=text, fingerprint=ocr_fingerprint(text))
            for text in frame
        ]


class SignatureOcrSource(FakeOcrSource):
    def __init__(self) -> None:
        super().__init__()
        self.signature = bytes([0] * 16)
        self.read_count = 0

    def read_blocks(self) -> list[OcrBlock]:
        self.read_count += 1
        return super().read_blocks()

    def screen_signature(self) -> bytes:
        return self.signature


class FakeRgbImage:
    def __init__(
        self,
        width: int,
        height: int,
        rectangles: list[tuple[int, int, int, int]],
    ) -> None:
        self.size = (width, height)
        self._pixels = {
            (x, y): (195, 246, 157)
            for left, top, right, bottom in rectangles
            for y in range(top, bottom)
            for x in range(left, right)
        }

    def convert(self, _mode: str) -> FakeRgbImage:
        return self

    def load(self):
        pixels = self._pixels

        class PixelMap:
            def __getitem__(self, point: tuple[int, int]) -> tuple[int, int, int]:
                return pixels.get(point, (255, 255, 255))

        return PixelMap()


def test_screen_region_parse() -> None:
    assert ScreenRegion.parse("10,20,300,400") == ScreenRegion(10, 20, 300, 400)
    with pytest.raises(ValueError):
        ScreenRegion.parse("10,20,0,400")


def test_screen_point_parse() -> None:
    assert ScreenPoint.parse("100,200") == ScreenPoint(100, 200)
    with pytest.raises(ValueError):
        ScreenPoint.parse("100")


def test_normalize_ocr_text() -> None:
    assert normalize_ocr_text("  關 廟\n 柳 營   5000 ") == "關 廟 柳 營 5000"


def test_find_message_bubble_boxes_returns_visual_order() -> None:
    image = FakeRgbImage(
        120,
        100,
        [
            (50, 55, 110, 80),
            (60, 10, 100, 35),
            (5, 5, 10, 10),  # 太小的綠色介面雜訊
        ],
    )

    assert find_message_bubble_boxes(image) == [
        (60, 10, 100, 35),
        (50, 55, 110, 80),
    ]


def test_ocr_connector_emits_only_new_visible_blocks() -> None:
    source = FakeOcrSource()
    sender = FakeSender()
    source.set_texts("舊訊息")
    connector = OcrConnector(
        source,
        sender,
        poll_interval=0.02,
        confirmation_interval=0.01,
    )
    received: list[IncomingMessage] = []

    connector.start_monitoring("", received.append)
    time.sleep(0.05)
    source.set_texts("舊訊息", "關廟 柳營 5000")
    time.sleep(0.08)
    connector.stop_monitoring()

    assert [message.text for message in received] == ["關廟 柳營 5000"]


def test_ocr_connector_sends_through_clipboard_sender() -> None:
    source = FakeOcrSource()
    sender = FakeSender()
    connector = OcrConnector(source, sender)
    connector.send_message("接")
    assert sender.sent == ["接"]


def test_ocr_connector_ignores_single_frame_jitter() -> None:
    source = SequenceOcrSource(
        [
            ["既有文字"],
            ["既有文字", "錯誤辨識"],
            ["既有文字"],
            ["既有文字"],
        ]
    )
    connector = OcrConnector(
        source,
        FakeSender(),
        poll_interval=0.01,
        stable_frames=2,
    )
    received: list[IncomingMessage] = []

    connector.start_monitoring("", received.append)
    time.sleep(0.08)
    connector.stop_monitoring()

    assert received == []
    assert connector.get_diagnostics()["blocks_seen"] == 0


def test_change_detection_skips_ocr_when_screen_is_unchanged() -> None:
    source = SignatureOcrSource()
    source.set_texts("既有文字")
    connector = OcrConnector(
        source,
        FakeSender(),
        screenshot_interval=0.01,
    )

    connector.start_monitoring("", lambda _: None)
    time.sleep(0.08)
    connector.stop_monitoring()

    assert source.read_count == 1
    diagnostics = connector.get_diagnostics()
    assert diagnostics["change_detection"] is True
    assert diagnostics["screenshot_checks"] > 1
    assert diagnostics["ocr_runs"] == 1


def test_change_detection_runs_ocr_after_screen_changes() -> None:
    source = SignatureOcrSource()
    source.set_texts("既有文字")
    connector = OcrConnector(
        source,
        FakeSender(),
        screenshot_interval=0.01,
        change_debounce=0.01,
        confirmation_interval=0.01,
        stable_frames=2,
    )
    received: list[IncomingMessage] = []

    connector.start_monitoring("", received.append)
    time.sleep(0.03)
    source.set_texts("既有文字", "關廟 柳營 5000")
    source.signature = bytes([255] * 16)
    time.sleep(0.12)
    connector.stop_monitoring()

    assert [message.text for message in received] == ["關廟 柳營 5000"]
    assert source.read_count == 3  # baseline + candidate + confirmation
