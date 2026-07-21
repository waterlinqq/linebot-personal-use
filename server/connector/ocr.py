from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from server.connector.base import IncomingMessage, LineConnector, MessageHandler

CONNECTOR_VERSION = "1.7"
OCR_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "ocr_config.json"


def load_ocr_config(path: Path = OCR_CONFIG_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    return {str(key): str(value) for key, value in data.items()}


def save_ocr_config(
    region: str,
    input_point: str,
    path: Path = OCR_CONFIG_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "region": region,
                "input_point": input_point,
                "language": "chi_tra+eng",
            },
            file,
            ensure_ascii=False,
            indent=2,
        )


@dataclass(frozen=True)
class ScreenRegion:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def parse(cls, value: str) -> ScreenRegion:
        try:
            parts = [int(part.strip()) for part in value.split(",")]
        except ValueError as exc:
            raise ValueError("OCR 區域格式必須是 left,top,width,height") from exc
        if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
            raise ValueError("OCR 區域格式必須是 left,top,width,height，寬高需大於 0")
        return cls(*parts)


@dataclass(frozen=True)
class ScreenPoint:
    x: int
    y: int

    @classmethod
    def parse(cls, value: str) -> ScreenPoint:
        try:
            parts = [int(part.strip()) for part in value.split(",")]
        except ValueError as exc:
            raise ValueError("輸入點格式必須是 x,y") from exc
        if len(parts) != 2:
            raise ValueError("輸入點格式必須是 x,y")
        return cls(*parts)


@dataclass(frozen=True)
class OcrBlock:
    text: str
    fingerprint: str


class OcrSource(Protocol):
    def read_blocks(self) -> list[OcrBlock]: ...


class TextSender(Protocol):
    def send_text(self, text: str) -> None: ...


def normalize_ocr_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip()


def ocr_fingerprint(text: str) -> str:
    normalized = normalize_ocr_text(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def find_message_bubble_boxes(image) -> list[tuple[int, int, int, int]]:
    """找出 LINE 綠色訊息氣泡，避免時間戳與其他介面文字干擾 OCR。"""
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    pixels = rgb_image.load()
    mask = bytearray(width * height)

    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            if green >= 120 and green - red >= 25 and green - blue >= 25:
                mask[y * width + x] = 1

    seen = bytearray(width * height)
    boxes: list[tuple[int, int, int, int]] = []
    for start, is_bubble_pixel in enumerate(mask):
        if not is_bubble_pixel or seen[start]:
            continue

        stack = [start]
        seen[start] = 1
        pixel_count = 0
        left = right = start % width
        top = bottom = start // width

        while stack:
            current = stack.pop()
            x = current % width
            y = current // width
            pixel_count += 1
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)

            neighbours = []
            if x > 0:
                neighbours.append(current - 1)
            if x + 1 < width:
                neighbours.append(current + 1)
            if y > 0:
                neighbours.append(current - width)
            if y + 1 < height:
                neighbours.append(current + width)
            for neighbour in neighbours:
                if mask[neighbour] and not seen[neighbour]:
                    seen[neighbour] = 1
                    stack.append(neighbour)

        box_width = right - left + 1
        box_height = bottom - top + 1
        if pixel_count >= 200 and box_width >= 24 and box_height >= 16:
            boxes.append((left, top, right + 1, bottom + 1))

    return sorted(boxes, key=lambda box: (box[1], box[0]))


class TesseractScreenSource:
    def __init__(
        self,
        region: ScreenRegion,
        *,
        language: str = "chi_tra+eng",
        tesseract_cmd: str = "",
    ) -> None:
        self.region = region
        self.language = language
        self.tesseract_cmd = tesseract_cmd

    def activate_target(self) -> None:
        if os.sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", 'tell application "LINE" to activate'],
                check=False,
                capture_output=True,
                text=True,
            )
            time.sleep(0.5)
        elif os.sys.platform == "win32":
            self._activate_line_on_windows()
            time.sleep(0.5)

    @staticmethod
    def _activate_line_on_windows() -> None:
        import psutil

        user32 = ctypes.windll.user32
        target_hwnd = ctypes.c_void_p()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def callback(hwnd, _extra) -> bool:
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            try:
                process_name = psutil.Process(process_id.value).name().lower()
            except (psutil.Error, OSError):
                return True
            if process_name == "line.exe" and user32.IsWindowVisible(hwnd):
                target_hwnd.value = hwnd
                return False
            return True

        user32.EnumWindows(callback, 0)
        if target_hwnd.value:
            user32.ShowWindow(target_hwnd.value, 9)  # SW_RESTORE
            user32.SetForegroundWindow(target_hwnd.value)

    def capture_image(self):
        from PIL import Image
        import mss

        with mss.mss() as capture:
            shot = capture.grab(
                {
                    "left": self.region.left,
                    "top": self.region.top,
                    "width": self.region.width,
                    "height": self.region.height,
                }
            )
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def screen_signature(self) -> bytes:
        from PIL import ImageOps

        image = ImageOps.grayscale(self.capture_image())
        image = image.resize((32, 32))
        return bytes(image.getdata())

    def read_blocks(self) -> list[OcrBlock]:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        import pytesseract

        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

        image = self.capture_image()
        blocks: list[OcrBlock] = []
        bubble_boxes = find_message_bubble_boxes(image)
        targets = (
            [(image.crop(box), 7) for box in bubble_boxes]
            if bubble_boxes
            else [(image, 11)]
        )

        for target, page_mode in targets:
            prepared = ImageOps.grayscale(target)
            prepared = ImageOps.expand(prepared, border=4, fill=255)
            prepared = prepared.resize(
                (prepared.width * 3, prepared.height * 3),
                Image.Resampling.LANCZOS,
            )
            prepared = ImageEnhance.Contrast(prepared).enhance(2.0)
            prepared = prepared.filter(ImageFilter.SHARPEN)

            data = pytesseract.image_to_data(
                prepared,
                lang=self.language,
                config=f"--psm {page_mode}",
                output_type=pytesseract.Output.DICT,
            )
            groups: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
            count = len(data["text"])
            for index in range(count):
                text = normalize_ocr_text(str(data["text"][index]))
                try:
                    confidence = float(data["conf"][index])
                except (TypeError, ValueError):
                    confidence = -1
                if not text or confidence < 25:
                    continue
                key = (
                    int(data["block_num"][index]),
                    int(data["par_num"][index]),
                    int(data["line_num"][index]),
                )
                groups.setdefault(key, []).append(
                    (int(data["left"][index]), text)
                )

            for words in groups.values():
                words.sort(key=lambda item: item[0])
                text = normalize_ocr_text(" ".join(word for _, word in words))
                if len(text) < 2:
                    continue
                blocks.append(
                    OcrBlock(text=text, fingerprint=ocr_fingerprint(text))
                )
        return blocks


class ClipboardTextSender:
    def __init__(self, input_point: ScreenPoint) -> None:
        self.input_point = input_point

    def send_text(self, text: str) -> None:
        import pyperclip

        pyperclip.copy(text)
        if os.sys.platform == "darwin":
            self._send_on_macos()
        elif os.sys.platform == "win32":
            self._send_on_windows()
        else:
            raise RuntimeError("OCR 自動回覆目前只支援 macOS 與 Windows")

    def _send_on_macos(self) -> None:
        script = f"""
        tell application "System Events"
            click at {{{self.input_point.x}, {self.input_point.y}}}
            delay 0.1
            keystroke "v" using command down
            key code 36
        end tell
        """
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "未知錯誤").strip()
            raise RuntimeError(
                f"macOS 自動回覆失敗：{detail}。"
                "請在系統設定允許 Cursor/終端機的「輔助使用」權限。"
            )

    def _send_on_windows(self) -> None:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(self.input_point.x, self.input_point.y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
        time.sleep(0.1)

        def key(code: int, down: bool) -> None:
            user32.keybd_event(code, 0, 0 if down else 0x0002, 0)

        key(0x11, True)   # Ctrl
        key(0x56, True)   # V
        key(0x56, False)
        key(0x11, False)
        key(0x0D, True)   # Enter
        key(0x0D, False)


class OcrConnector(LineConnector):
    def __init__(
        self,
        source: OcrSource | None = None,
        sender: TextSender | None = None,
        *,
        poll_interval: float = 0.75,
        screenshot_interval: float = 0.1,
        change_debounce: float = 0.3,
        confirmation_interval: float = 0.15,
        change_threshold: float = 0.01,
        stable_frames: int = 2,
        absent_frames: int = 3,
    ) -> None:
        self._source = source or self._source_from_environment()
        self._sender = sender or self._sender_from_environment()
        self._poll_interval = poll_interval
        self._screenshot_interval = screenshot_interval
        self._change_debounce = change_debounce
        self._confirmation_interval = confirmation_interval
        self._change_threshold = change_threshold
        self._stable_frames = max(1, stable_frames)
        self._absent_frames = max(1, absent_frames)
        self._running = False
        self._connected = False
        self._handler: MessageHandler | None = None
        self._thread: threading.Thread | None = None
        self._accepted_fingerprints: set[str] = set()
        self._candidate_counts: dict[str, int] = {}
        self._missing_counts: dict[str, int] = {}
        self._last_error = ""
        self._last_poll_at = ""
        self._blocks_seen = 0
        self._last_ocr_ms = 0
        self._average_ocr_ms = 0
        self._ocr_runs = 0
        self._screenshot_checks = 0
        self._last_signature: bytes | None = None
        self._uses_change_detection = callable(
            getattr(self._source, "screen_signature", None)
        )
        self._reset_after_send = False

    @property
    def connector_type(self) -> str:
        return "ocr"

    def start_monitoring(self, group_name: str, on_message: MessageHandler) -> None:
        if self._running:
            return
        self._handler = on_message
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="linebot-ocr-thread",
            daemon=True,
        )
        self._thread.start()

    def stop_monitoring(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._connected = False

    def send_message(self, text: str) -> None:
        try:
            self._sender.send_text(text)
            self._last_error = ""
            self._reset_after_send = True
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"send_failed: {exc}"
            raise

    def is_connected(self) -> bool:
        return self._running and self._connected

    def get_diagnostics(self) -> dict:
        return {
            "connector_version": CONNECTOR_VERSION,
            "running": self._running,
            "connected": self._connected,
            "blocks_seen": self._blocks_seen,
            "visible_blocks": len(self._accepted_fingerprints),
            "candidate_blocks": len(self._candidate_counts),
            "stable_frames_required": self._stable_frames,
            "poll_interval_ms": round(self._poll_interval * 1000),
            "screenshot_interval_ms": round(self._screenshot_interval * 1000),
            "change_detection": self._uses_change_detection,
            "screenshot_checks": self._screenshot_checks,
            "ocr_runs": self._ocr_runs,
            "last_ocr_ms": self._last_ocr_ms,
            "average_ocr_ms": self._average_ocr_ms,
            "last_poll_at": self._last_poll_at,
            "last_error": self._last_error,
            "monitor_thread": self._thread.name if self._thread else "",
        }

    def _poll_loop(self) -> None:
        try:
            activate_target = getattr(self._source, "activate_target", None)
            if callable(activate_target):
                activate_target()
            initial = self._read_blocks()
            self._accepted_fingerprints = {
                block.fingerprint for block in initial
            }
            self._blocks_seen = 0
            self._last_signature = self._capture_signature()
            self._connected = True

            while self._running:
                self._last_poll_at = time.strftime("%Y-%m-%d %H:%M:%S")
                confirming_candidate = bool(self._candidate_counts)
                if self._uses_change_detection and not confirming_candidate:
                    signature = self._capture_signature()
                    if not self._screen_changed(self._last_signature, signature):
                        time.sleep(self._screenshot_interval)
                        continue
                    time.sleep(self._change_debounce)
                    self._last_signature = self._capture_signature()

                blocks = self._read_blocks()
                current = {block.fingerprint: block for block in blocks}

                for fingerprint in list(self._candidate_counts):
                    if fingerprint not in current:
                        del self._candidate_counts[fingerprint]

                for block in blocks:
                    fingerprint = block.fingerprint
                    if fingerprint in self._accepted_fingerprints:
                        self._missing_counts.pop(fingerprint, None)
                        continue

                    count = self._candidate_counts.get(fingerprint, 0) + 1
                    self._candidate_counts[fingerprint] = count
                    if count < self._stable_frames:
                        continue

                    self._candidate_counts.pop(fingerprint, None)
                    self._accepted_fingerprints.add(fingerprint)
                    self._blocks_seen += 1
                    if self._handler:
                        self._handler(IncomingMessage(text=block.text))

                if self._reset_after_send:
                    # 等待自己的訊息出現在畫面後，重新建立完整基準。
                    time.sleep(0.5)
                    refreshed = self._read_blocks()
                    self._accepted_fingerprints = {
                        block.fingerprint for block in refreshed
                    }
                    self._candidate_counts.clear()
                    self._missing_counts.clear()
                    self._last_signature = self._capture_signature()
                    self._reset_after_send = False
                    time.sleep(self._screenshot_interval)
                    continue

                for fingerprint in list(self._accepted_fingerprints):
                    if fingerprint in current:
                        continue
                    missing = self._missing_counts.get(fingerprint, 0) + 1
                    if missing >= self._absent_frames:
                        self._accepted_fingerprints.remove(fingerprint)
                        self._missing_counts.pop(fingerprint, None)
                    else:
                        self._missing_counts[fingerprint] = missing

                delay = (
                    self._confirmation_interval
                    if self._candidate_counts
                    else (
                        self._screenshot_interval
                        if self._uses_change_detection
                        else self._poll_interval
                    )
                )
                if self._uses_change_detection and not self._candidate_counts:
                    self._last_signature = self._capture_signature()
                time.sleep(delay)
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._running = False
            self._connected = False

    def _read_blocks(self) -> list[OcrBlock]:
        started = time.perf_counter()
        blocks = self._source.read_blocks()
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        self._last_ocr_ms = elapsed_ms
        self._ocr_runs += 1
        self._average_ocr_ms = round(
            (
                (self._average_ocr_ms * (self._ocr_runs - 1))
                + elapsed_ms
            )
            / self._ocr_runs
        )
        return blocks

    def _capture_signature(self) -> bytes | None:
        capture = getattr(self._source, "screen_signature", None)
        if not callable(capture):
            return None
        self._screenshot_checks += 1
        return capture()

    def _screen_changed(
        self,
        previous: bytes | None,
        current: bytes | None,
    ) -> bool:
        if previous is None or current is None or len(previous) != len(current):
            return True
        changed_pixels = sum(
            1 for old, new in zip(previous, current)
            if abs(old - new) >= 12
        )
        return (changed_pixels / len(current)) >= self._change_threshold

    @staticmethod
    def _source_from_environment() -> OcrSource:
        config = load_ocr_config()
        region_value = os.environ.get("LINEBOT_OCR_REGION") or config.get("region", "")
        if not region_value:
            raise RuntimeError(
                "尚未設定 LINEBOT_OCR_REGION；請先執行 scripts/calibrate_ocr.py"
            )
        return TesseractScreenSource(
            ScreenRegion.parse(region_value),
            language=(
                os.environ.get("LINEBOT_OCR_LANG")
                or config.get("language", "chi_tra+eng")
            ),
            tesseract_cmd=(
                os.environ.get("LINEBOT_TESSERACT_CMD")
                or config.get("tesseract_cmd", "")
            ),
        )

    @staticmethod
    def _sender_from_environment() -> TextSender:
        config = load_ocr_config()
        point_value = (
            os.environ.get("LINEBOT_INPUT_POINT")
            or config.get("input_point", "")
        )
        if not point_value:
            raise RuntimeError(
                "尚未設定 LINEBOT_INPUT_POINT；請先執行 scripts/calibrate_ocr.py"
            )
        return ClipboardTextSender(ScreenPoint.parse(point_value))
