from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MatchMode = Literal["either", "both", "origin_only", "dest_only"]


@dataclass
class MatchConfig:
    match_mode: MatchMode = "either"
    min_price: int = 0
    max_price: int = 999999
    exclude_keywords: list[str] = field(default_factory=list)
    reply_text: str = "接"
    regions: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class MatchResult:
    should_reply: bool
    matched_regions: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    reason: str = ""


class RegionMatcher:
    def __init__(self, config: MatchConfig) -> None:
        self.config = config

    def update_config(self, config: MatchConfig) -> None:
        self.config = config

    def _text_contains_keyword(self, text: str, keyword: str) -> bool:
        return keyword in text

    def _location_matches(self, location: str | None, text: str) -> tuple[list[str], list[str]]:
        if not location:
            return [], []

        matched_regions: list[str] = []
        matched_keywords: list[str] = []

        for region_name, keywords in self.config.regions.items():
            for keyword in keywords:
                if not keyword:
                    continue
                if keyword in location or self._text_contains_keyword(text, keyword):
                    if region_name not in matched_regions:
                        matched_regions.append(region_name)
                    if keyword not in matched_keywords:
                        matched_keywords.append(keyword)

        return matched_regions, matched_keywords

    def match(
        self,
        *,
        is_order: bool,
        raw_text: str,
        origin: str | None,
        destination: str | None,
        price: int | None,
    ) -> MatchResult:
        if not is_order:
            return MatchResult(should_reply=False, reason="not_order")

        text = raw_text.replace("臺", "台")

        for keyword in self.config.exclude_keywords:
            if keyword and keyword in text:
                return MatchResult(
                    should_reply=False,
                    reason=f"excluded_by_keyword:{keyword}",
                )

        if price is not None:
            if price < self.config.min_price:
                return MatchResult(should_reply=False, reason="below_min_price")
            if price > self.config.max_price:
                return MatchResult(should_reply=False, reason="above_max_price")

        origin_regions, origin_keywords = self._location_matches(origin, text)
        dest_regions, dest_keywords = self._location_matches(destination, text)

        mode = self.config.match_mode
        if mode == "either":
            regions = list(dict.fromkeys(origin_regions + dest_regions))
            keywords = list(dict.fromkeys(origin_keywords + dest_keywords))
            if not regions:
                # 全文 fallback（處理 高雄台南 6000 這類連寫）
                regions, keywords = self._location_matches(text, text)
        elif mode == "both":
            if not origin_regions or not dest_regions:
                return MatchResult(should_reply=False, reason="both_required")
            regions = list(dict.fromkeys(origin_regions + dest_regions))
            keywords = list(dict.fromkeys(origin_keywords + dest_keywords))
        elif mode == "origin_only":
            regions, keywords = origin_regions, origin_keywords
        else:
            regions, keywords = dest_regions, dest_keywords

        if regions:
            return MatchResult(
                should_reply=True,
                matched_regions=regions,
                matched_keywords=keywords,
                reason="matched",
            )

        return MatchResult(should_reply=False, reason="no_region_match")
