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
    def __init__(
        self,
        config: MatchConfig,
        known_keywords: list[str] | None = None,
    ) -> None:
        self.config = config
        self.catalog_keywords = list(known_keywords or [])
        self.known_keywords = self._effective_known_keywords()

    def update_config(self, config: MatchConfig) -> None:
        self.config = config
        self.known_keywords = self._effective_known_keywords()

    def _effective_known_keywords(self) -> list[str]:
        combined = list(self.catalog_keywords)
        for keywords in self.config.regions.values():
            combined.extend(keywords)
        seen: set[str] = set()
        result: list[str] = []
        for keyword in combined:
            keyword = keyword.strip()
            if keyword and keyword not in seen:
                seen.add(keyword)
                result.append(keyword)
        return result

    def _text_contains_keyword(self, text: str, keyword: str) -> bool:
        compact_text = "".join(text.split())
        compact_keyword = "".join(keyword.split())
        return compact_keyword in compact_text

    def _is_known_location(self, location: str | None) -> bool:
        if not location:
            return False
        compact = "".join(location.split())
        for keyword in self.known_keywords:
            if keyword and self._text_contains_keyword(compact, keyword):
                return True
        return False

    def _validate_route_locations(
        self,
        locations: list[str],
        origin: str | None,
        destination: str | None,
    ) -> MatchResult | None:
        if len(locations) >= 2:
            for split_at in range(1, len(locations)):
                route_origin = "".join(locations[:split_at])
                route_destination = "".join(locations[split_at:])
                if self._is_known_location(route_origin) and self._is_known_location(
                    route_destination
                ):
                    return None
            return MatchResult(should_reply=False, reason="invalid_destination")

        if origin and not self._is_known_location(origin):
            return MatchResult(should_reply=False, reason="invalid_origin")
        if destination and not self._is_known_location(destination):
            return MatchResult(should_reply=False, reason="invalid_destination")
        return None

    def _location_matches(self, location: str | None, text: str) -> tuple[list[str], list[str]]:
        if not location:
            return [], []

        matched_regions: list[str] = []
        matched_keywords: list[str] = []

        for region_name, keywords in self.config.regions.items():
            for keyword in keywords:
                if not keyword:
                    continue
                if (
                    self._text_contains_keyword(location, keyword)
                    or self._text_contains_keyword(text, keyword)
                ):
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
        locations: list[str] | None = None,
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

        invalid = self._validate_route_locations(locations or [], origin, destination)
        if invalid is not None:
            return invalid

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
