from __future__ import annotations

import re
from dataclasses import dataclass, field

# 常見回覆或非派單訊息
SKIP_EXACT = {
    "接",
    "收",
    "👌",
    "👋",
    "收到",
    "明白了",
    "知道了",
    "呃要等",
    "打錯",
    "不明",
}

SKIP_PREFIXES = ("@", "[語音", "[貼圖", "[照片", "[影片")

# 日期：07.04、7/14、06.30、7.13配合时间
DATE_PATTERN = re.compile(
    r"(?<!\d)"
    r"(?:\d{1,2}[./]\d{1,2}|\d{1,2}\.\d{2})"
    r"(?:配合\s*时间|配合\s*時間)?"
)

# 時間：8.00、14:00、10點、上午9点、全天、早上6.00
TIME_PATTERN = re.compile(
    r"(?:"
    r"\d{1,2}[:.]\d{2,3}|"
    r"\d{1,2}\s*點|\d{1,2}\s*点|"
    r"(?:上午|下午|早上|中午|晚(?:上)?)\s*\d{1,2}\s*[點点]?|"
    r"全天(?:配合)?|"
    r"\d{1,2}[:.]\d{2}\s*-\s*\d{1,2}[:.]\d{2}"
    r")",
    re.IGNORECASE,
)

# 金額：3500、16800、3500+500、快包3500
PRICE_PATTERN = re.compile(
    r"(?<![\d.])"
    r"(\d{3,5})"
    r"(?:\s*[+＋]\s*\d+)?"
    r"(?!\d)",
)

# 地點分隔
LOCATION_SPLIT = re.compile(r"[\s\-到→]+")

# 不像地點的 token
NOISE_TOKENS = {
    "配合",
    "时间",
    "時間",
    "人力",
    "搬運",
    "搬运",
    "快包",
    "打包",
    "单件",
    "單件",
    "转点",
    "轉點",
    "全天",
    "上午",
    "下午",
    "早上",
    "中午",
    "晚上",
    "物品",
    "单",
    "單",
    "小巷",
    "3+",
    "2+",
    "2➕",
    "5+",
}


@dataclass
class ParsedMessage:
    raw_text: str
    is_order: bool
    date: str | None = None
    time: str | None = None
    locations: list[str] = field(default_factory=list)
    origin: str | None = None
    destination: str | None = None
    price: int | None = None
    reason: str = ""


def _normalize(text: str) -> str:
    return text.strip().replace("\u3000", " ").replace("臺", "台")


def _is_noise_token(token: str) -> bool:
    if not token:
        return True
    if token in NOISE_TOKENS:
        return True
    if token.isdigit():
        return True
    if re.fullmatch(r"\d[+＋]?", token):
        return True
    if re.search(r"[a-zA-Z]", token) and not re.search(r"[\u4e00-\u9fff]", token):
        return True
    if re.search(r"[tT]|噸|吨|\.5", token):
        return True
    return False


def _extract_locations(text: str) -> list[str]:
    working = DATE_PATTERN.sub(" ", text)
    working = TIME_PATTERN.sub(" ", working)
    working = PRICE_PATTERN.sub(" ", working)
    working = re.sub(r"[+＋]\d+", " ", working)
    working = re.sub(r"\d[+＋]", " ", working)

    tokens: list[str] = []
    for part in LOCATION_SPLIT.split(working):
        token = part.strip(" ，,。.")
        if _is_noise_token(token):
            continue
        if re.search(r"[\u4e00-\u9fff]", token):
            tokens.append(token)

    return tokens


def parse_message(text: str) -> ParsedMessage:
    normalized = _normalize(text)
    result = ParsedMessage(raw_text=text, is_order=False)

    if not normalized:
        result.reason = "empty"
        return result

    if normalized in SKIP_EXACT:
        result.reason = "reply_or_ack"
        return result

    if any(normalized.startswith(prefix) for prefix in SKIP_PREFIXES):
        result.reason = "mention_or_media"
        return result

    if normalized.endswith("?") or normalized.endswith("？"):
        result.reason = "question"
        return result

    if re.fullmatch(r"(有地址嗎|有地址吗).?", normalized):
        result.reason = "question"
        return result

    prices = [int(m.group(1)) for m in PRICE_PATTERN.finditer(normalized)]
    if not prices:
        result.reason = "no_price"
        return result

    result.price = max(prices)

    date_match = DATE_PATTERN.search(normalized)
    if date_match:
        result.date = date_match.group(0)

    time_match = TIME_PATTERN.search(normalized)
    if time_match:
        result.time = time_match.group(0)

    locations = _extract_locations(normalized)
    result.locations = locations
    if locations:
        result.origin = locations[0]
        result.destination = locations[1] if len(locations) > 1 else locations[0]

    has_date = result.date is not None
    has_locations = len(locations) >= 1
    has_route_hint = bool(re.search(r"[\-到→]", normalized))

    if has_locations and (has_date or has_route_hint or len(locations) >= 2):
        result.is_order = True
        result.reason = "order_detected"
        return result

    # 無日期但明確起訖：三民到三民 4800
    if has_locations and len(locations) >= 2 and result.price >= 1000:
        result.is_order = True
        result.reason = "order_detected_route_only"
        return result

    # 單一地點 + 日期 + 金額：07.12 楊梅 楊梅3000
    if has_date and has_locations and result.price >= 1000:
        result.is_order = True
        result.reason = "order_detected_date_location"
        return result

    result.reason = "insufficient_structure"
    return result
