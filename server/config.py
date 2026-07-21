from __future__ import annotations

from pathlib import Path

import yaml

from server.engine.matcher import MatchConfig

DEFAULT_YAML = Path(__file__).resolve().parents[1] / "data" / "default_regions.yaml"


def load_default_config(path: Path | None = None) -> MatchConfig:
    yaml_path = path or DEFAULT_YAML
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return MatchConfig(
        match_mode=data.get("match_mode", "either"),
        min_price=int(data.get("min_price", 0)),
        max_price=int(data.get("max_price", 999999)),
        exclude_keywords=list(data.get("exclude_keywords", [])),
        reply_text=str(data.get("reply_text", "接")),
        regions={k: list(v) for k, v in data.get("regions", {}).items()},
    )


def merge_region_keywords(
    stored: MatchConfig,
    defaults: MatchConfig,
) -> MatchConfig:
    """合併預設關鍵字到已儲存設定，保留使用者自訂項目。"""
    merged_regions: dict[str, list[str]] = {}

    all_region_names = set(defaults.regions) | set(stored.regions)
    for region_name in sorted(all_region_names):
        combined: list[str] = []
        for source in (defaults.regions.get(region_name, []), stored.regions.get(region_name, [])):
            for keyword in source:
                keyword = keyword.strip()
                if keyword and keyword not in combined:
                    combined.append(keyword)
        merged_regions[region_name] = combined

    return MatchConfig(
        match_mode=stored.match_mode,
        min_price=stored.min_price,
        max_price=stored.max_price,
        exclude_keywords=list(stored.exclude_keywords),
        reply_text=stored.reply_text,
        regions=merged_regions,
    )


def resolve_startup_config(stored: MatchConfig | None, defaults: MatchConfig) -> MatchConfig:
    if stored is None:
        return defaults
    return merge_region_keywords(stored, defaults)
