from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from server.config import flatten_all_keywords, load_region_catalog
from server.connector.base import IncomingMessage, LineConnector, MessageHandler

CONNECTOR_VERSION = "1.10"
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
                "language": "chi_tra",
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
    bottom_y: int = 0


class OcrSource(Protocol):
    def read_blocks(self) -> list[OcrBlock]: ...


class TextSender(Protocol):
    def send_text(self, text: str) -> None: ...


def normalize_ocr_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip()


def _compact_keyword(keyword: str) -> str:
    return "".join(keyword.split())


def build_keyword_regions(
    catalog: dict | None = None,
) -> tuple[set[str], list[str], dict[str, set[str]]]:
    catalog = catalog or load_region_catalog()
    keyword_set: set[str] = set()
    keyword_regions: dict[str, set[str]] = {}

    for region_name, entry in catalog.items():
        for alias in entry.get("aliases", []):
            compact = _compact_keyword(alias)
            if compact:
                keyword_set.add(compact)
                keyword_regions.setdefault(compact, set()).add(region_name)
        for district_name, district_keywords in entry.get("districts", {}).items():
            keyword_set.add(district_name)
            keyword_regions.setdefault(district_name, set()).add(region_name)
            for keyword in district_keywords:
                compact = _compact_keyword(keyword)
                if compact:
                    keyword_set.add(compact)
                    keyword_regions.setdefault(compact, set()).add(region_name)

    keywords_sorted = sorted(keyword_set, key=len, reverse=True)
    return keyword_set, keywords_sorted, keyword_regions


def _best_fuzzy_keyword_match(
    chunk: str,
    keyword_set: set[str],
    keyword_regions: dict[str, set[str]],
    previous_regions: set[str],
    *,
    max_distance: int = 1,
) -> str | None:
    candidates: list[tuple[bool, int, str]] = []
    for keyword in keyword_set:
        if len(keyword) != len(chunk):
            continue
        distance = sum(left != right for left, right in zip(chunk, keyword))
        if distance > max_distance:
            continue
        same_region = bool(previous_regions.intersection(keyword_regions.get(keyword, set())))
        candidates.append((same_region, distance, keyword))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    return candidates[0][2]


def _segment_known_keywords(compact_text: str, keywords_sorted: list[str]) -> list[str]:
    segments: list[str] = []
    position = 0
    while position < len(compact_text):
        matched = next(
            (
                keyword
                for keyword in keywords_sorted
                if compact_text.startswith(keyword, position)
            ),
            None,
        )
        if matched:
            segments.append(matched)
            position += len(matched)
            continue

        literal_start = position
        position += 1
        while position < len(compact_text) and not any(
            compact_text.startswith(keyword, position) for keyword in keywords_sorted
        ):
            position += 1
        segments.append(compact_text[literal_start:position])
    return segments


def correct_ocr_text(
    text: str,
    known_keywords: list[str] | None = None,
    *,
    catalog: dict | None = None,
) -> str:
    """以地名詞彙修正 OCR 錯字，保留非地名的字面片段（例如 楠梓加工）。"""
    normalized = normalize_ocr_text(text)
    price_match = re.search(r"\d{3,5}", normalized)
    if not price_match:
        return normalized

    price = price_match.group(0)
    location_text = (
        normalized[: price_match.start()] + normalized[price_match.end() :]
    ).strip()
    location_compact = re.sub(
        r"[^\u4e00-\u9fff]",
        "",
        location_text.replace("臺", "台"),
    )
    if not location_compact:
        return normalized

    if known_keywords is None:
        keyword_set, keywords_sorted, keyword_regions = build_keyword_regions(catalog)
    else:
        keyword_set = {_compact_keyword(keyword) for keyword in known_keywords}
        keyword_set.discard("")
        keywords_sorted = sorted(keyword_set, key=len, reverse=True)
        _, _, keyword_regions = build_keyword_regions(catalog)

    corrected_segments: list[str] = []
    previous_regions: set[str] = set()
    for segment in _segment_known_keywords(location_compact, keywords_sorted):
        if segment in keyword_set:
            corrected_segments.append(segment)
            previous_regions |= keyword_regions.get(segment, set())
            continue

        if 2 <= len(segment) <= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", segment):
            fuzzy_match = _best_fuzzy_keyword_match(
                segment,
                keyword_set,
                keyword_regions,
                previous_regions,
            )
            if fuzzy_match:
                corrected_segments.append(fuzzy_match)
                previous_regions |= keyword_regions.get(fuzzy_match, set())
                continue

        corrected_segments.append(segment)

    if not corrected_segments:
        return normalized

    return normalize_ocr_text(" ".join(corrected_segments) + f" {price}")


def ocr_fingerprint(text: str) -> str:
    normalized = normalize_ocr_text(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def ocr_blocks_from_texts(*texts: str) -> list[OcrBlock]:
    return [
        OcrBlock(
            text=text,
            fingerprint=ocr_fingerprint(text),
            bottom_y=index,
        )
        for index, text in enumerate(texts)
    ]


def bottom_most_block(blocks: list[OcrBlock]) -> OcrBlock | None:
    if not blocks:
        return None
    return max(blocks, key=lambda block: block.bottom_y)


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
        language: str = "chi_tra",
        tesseract_cmd: str = "",
        known_keywords: list[str] | None = None,
    ) -> None:
        self.region = region
        self.language = language
        self.tesseract_cmd = tesseract_cmd
        self.known_keywords = known_keywords

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
            [(image.crop(box), 7, box[3]) for box in bubble_boxes]
            if bubble_boxes
            else [(image, 11, image.height)]
        )

        for target, page_mode, bottom_y in targets:
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
                text = correct_ocr_text(text, self.known_keywords)
                blocks.append(
                    OcrBlock(
                        text=text,
                        fingerprint=ocr_fingerprint(text),
                        bottom_y=bottom_y,
                    )
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
    ) -> None:
        self._source = source or self._source_from_environment()
        self._sender = sender or self._sender_from_environment()
        self._poll_interval = poll_interval
        self._screenshot_interval = screenshot_interval
        self._change_debounce = change_debounce
        self._confirmation_interval = confirmation_interval
        self._change_threshold = change_threshold
        self._stable_frames = max(1, stable_frames)
        self._running = False
        self._connected = False
        self._monitoring = False
        self._phase_lock = threading.Lock()
        self._handler: MessageHandler | None = None
        self._thread: threading.Thread | None = None
        self._session_records: dict[str, str] = {}
        self._candidate_counts: dict[str, int] = {}
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
        self._monitoring = False

    def activate_monitoring(self) -> None:
        """Phase 2：使用者手動切換，開始偵測新訊息。"""
        if not self._running:
            raise RuntimeError("尚未開始 Phase 1 掃描")
        with self._phase_lock:
            if self._monitoring:
                return
            self._candidate_counts.clear()
            self._monitoring = True
            self._last_signature = self._capture_signature()

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
        phase = "idle"
        if self._running:
            phase = "monitoring" if self._monitoring else "baseline"
        return {
            "connector_version": CONNECTOR_VERSION,
            "running": self._running,
            "connected": self._connected,
            "phase": phase,
            "blocks_seen": self._blocks_seen,
            "session_seen": len(self._session_records),
            "session_records": list(self._session_records.values()),
            "monitoring": self._monitoring,
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

    def _remember_block(self, block: OcrBlock) -> None:
        self._session_records[block.fingerprint] = block.text

    def _process_baseline_frame(self, blocks: list[OcrBlock]) -> None:
        """Phase 1：只累積畫面上看得到的訊息，不觸發 handler。"""
        for block in blocks:
            self._remember_block(block)

    def _process_monitoring_frame(self, blocks: list[OcrBlock]) -> None:
        """Phase 2：只對最底部且穩定的新訊息觸發 handler。"""
        current = {block.fingerprint: block for block in blocks}
        for fingerprint in list(self._candidate_counts):
            if fingerprint not in current:
                del self._candidate_counts[fingerprint]

        bottom_block = bottom_most_block(blocks)
        emit_block: OcrBlock | None = None

        for block in blocks:
            fingerprint = block.fingerprint
            if fingerprint in self._session_records:
                continue

            count = self._candidate_counts.get(fingerprint, 0) + 1
            self._candidate_counts[fingerprint] = count
            if count < self._stable_frames:
                continue

            self._candidate_counts.pop(fingerprint, None)
            self._remember_block(block)
            if (
                bottom_block is not None
                and block.fingerprint == bottom_block.fingerprint
            ):
                emit_block = block

        if emit_block and self._handler:
            self._blocks_seen += 1
            self._handler(IncomingMessage(text=emit_block.text))

    def _should_run_ocr(self, confirming_candidate: bool) -> bool:
        if not self._uses_change_detection or confirming_candidate:
            return True

        signature = self._capture_signature()
        if not self._screen_changed(self._last_signature, signature):
            time.sleep(self._screenshot_interval)
            return False

        time.sleep(self._change_debounce)
        self._last_signature = self._capture_signature()
        return True

    def _poll_loop(self) -> None:
        try:
            activate_target = getattr(self._source, "activate_target", None)
            if callable(activate_target):
                activate_target()
            self._session_records.clear()
            self._candidate_counts.clear()
            self._blocks_seen = 0
            self._monitoring = False
            self._connected = True

            initial_blocks = self._read_blocks()
            self._process_baseline_frame(initial_blocks)
            self._last_signature = self._capture_signature()

            while self._running:
                self._last_poll_at = time.strftime("%Y-%m-%d %H:%M:%S")
                confirming_candidate = (
                    self._monitoring and bool(self._candidate_counts)
                )
                if not self._should_run_ocr(confirming_candidate):
                    continue

                blocks = self._read_blocks()
                if self._monitoring:
                    self._process_monitoring_frame(blocks)
                else:
                    self._process_baseline_frame(blocks)

                if self._reset_after_send:
                    # 等待自己的訊息出現在畫面後，補進 session 記憶。
                    time.sleep(0.5)
                    for block in self._read_blocks():
                        self._remember_block(block)
                    self._candidate_counts.clear()
                    self._last_signature = self._capture_signature()
                    self._reset_after_send = False
                    time.sleep(self._screenshot_interval)
                    continue

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
        self._monitoring = False

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
                or config.get("language", "chi_tra")
            ),
            tesseract_cmd=(
                os.environ.get("LINEBOT_TESSERACT_CMD")
                or config.get("tesseract_cmd", "")
            ),
            known_keywords=flatten_all_keywords(load_region_catalog()),
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
