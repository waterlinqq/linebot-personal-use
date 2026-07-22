from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from server.engine.matcher import MatchConfig

DEFAULT_YAML = Path(__file__).resolve().parents[1] / "data" / "default_regions.yaml"

RegionCatalogEntry = dict[str, Any]


def _load_yaml(path: Path | None = None) -> dict[str, Any]:
    yaml_path = path or DEFAULT_YAML
    with yaml_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_region_catalog(path: Path | None = None) -> dict[str, RegionCatalogEntry]:
    data = _load_yaml(path)
    regions = data.get("regions", {})
    catalog: dict[str, RegionCatalogEntry] = {}
    for region_name, entry in regions.items():
        if isinstance(entry, dict) and "districts" in entry:
            catalog[region_name] = {
                "aliases": list(entry.get("aliases", [])),
                "districts": {
                    district: list(keywords)
                    for district, keywords in entry.get("districts", {}).items()
                },
            }
    return catalog


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    combined: list[str] = []
    for keyword in keywords:
        keyword = keyword.strip()
        if keyword and keyword not in combined:
            combined.append(keyword)
    return combined


def flatten_all_keywords(catalog: dict[str, RegionCatalogEntry]) -> list[str]:
    keywords: list[str] = []
    for entry in catalog.values():
        keywords.extend(flatten_region(entry, None))
    return _dedupe_keywords(keywords)


def flatten_region(
    catalog_entry: RegionCatalogEntry,
    selected_districts: list[str] | None = None,
) -> list[str]:
    """Build keyword list for a county. None selected_districts means all districts."""
    keywords = list(catalog_entry.get("aliases", []))
    districts: dict[str, list[str]] = catalog_entry.get("districts", {})

    if selected_districts is None:
        for district_keywords in districts.values():
            keywords.extend(district_keywords)
    elif selected_districts:
        keywords.extend(catalog_entry.get("aliases", []))
        for district_name in selected_districts:
            keywords.extend(districts.get(district_name, []))

    return _dedupe_keywords(keywords)


def infer_selection(
    stored_keywords: list[str],
    catalog_entry: RegionCatalogEntry,
) -> tuple[bool, list[str]]:
    """Return (all_districts_selected, selected_district_names)."""
    districts: dict[str, list[str]] = catalog_entry.get("districts", {})
    if not districts:
        return False, []

    stored_set = set(stored_keywords)
    selected = [
        district_name
        for district_name, keywords in districts.items()
        if stored_set.intersection(keywords)
    ]
    return len(selected) == len(districts), selected


def build_regions_from_selection(
    catalog: dict[str, RegionCatalogEntry],
    selection: dict[str, list[str] | None],
) -> dict[str, list[str]]:
    regions: dict[str, list[str]] = {}
    for region_name, selected_districts in selection.items():
        catalog_entry = catalog.get(region_name)
        if not catalog_entry:
            continue
        if selected_districts is None:
            keywords = flatten_region(catalog_entry, None)
        elif selected_districts:
            keywords = flatten_region(catalog_entry, selected_districts)
        else:
            continue
        if keywords:
            regions[region_name] = keywords
    return regions


def infer_region_selection(
    stored_regions: dict[str, list[str]],
    catalog: dict[str, RegionCatalogEntry],
) -> dict[str, list[str] | None]:
    selection: dict[str, list[str] | None] = {}
    for region_name, keywords in stored_regions.items():
        catalog_entry = catalog.get(region_name)
        if not catalog_entry:
            continue
        all_selected, selected_districts = infer_selection(keywords, catalog_entry)
        if all_selected:
            selection[region_name] = None
        elif selected_districts:
            selection[region_name] = selected_districts
    return selection


def load_default_config(path: Path | None = None) -> MatchConfig:
    data = _load_yaml(path)
    return MatchConfig(
        match_mode=data.get("match_mode", "either"),
        min_price=int(data.get("min_price", 0)),
        max_price=int(data.get("max_price", 999999)),
        exclude_keywords=list(data.get("exclude_keywords", [])),
        reply_text=str(data.get("reply_text", "接")),
        regions={},
    )


def merge_region_keywords(
    stored: MatchConfig,
    catalog: dict[str, RegionCatalogEntry],
) -> MatchConfig:
    """Merge catalog keywords into enabled counties only, preserving custom keywords."""
    merged_regions: dict[str, list[str]] = {}

    for region_name in stored.regions:
        stored_keywords = list(stored.regions[region_name])
        catalog_entry = catalog.get(region_name)
        if not catalog_entry:
            merged_regions[region_name] = _dedupe_keywords(stored_keywords)
            continue

        all_selected, selected_districts = infer_selection(stored_keywords, catalog_entry)
        if all_selected:
            catalog_keywords = flatten_region(catalog_entry, None)
        else:
            catalog_keywords = flatten_region(catalog_entry, selected_districts)

        merged_regions[region_name] = _dedupe_keywords(stored_keywords + catalog_keywords)

    return MatchConfig(
        match_mode=stored.match_mode,
        min_price=stored.min_price,
        max_price=stored.max_price,
        exclude_keywords=list(stored.exclude_keywords),
        reply_text=stored.reply_text,
        regions=merged_regions,
    )


def resolve_startup_config(
    stored: MatchConfig | None,
    defaults: MatchConfig,
    catalog: dict[str, RegionCatalogEntry],
) -> MatchConfig:
    if stored is None:
        return MatchConfig(
            match_mode=defaults.match_mode,
            min_price=defaults.min_price,
            max_price=defaults.max_price,
            exclude_keywords=list(defaults.exclude_keywords),
            reply_text=defaults.reply_text,
            regions={},
        )
    return merge_region_keywords(stored, catalog)


def load_config_with_regions(region_names: list[str]) -> MatchConfig:
    """Build a MatchConfig with selected counties fully enabled (for tests)."""
    defaults = load_default_config()
    catalog = load_region_catalog()
    selection = {name: None for name in region_names}
    return MatchConfig(
        match_mode=defaults.match_mode,
        min_price=defaults.min_price,
        max_price=defaults.max_price,
        exclude_keywords=list(defaults.exclude_keywords),
        reply_text=defaults.reply_text,
        regions=build_regions_from_selection(catalog, selection),
    )
