from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.app_state import get_bot_service
from server.config import infer_region_selection, load_region_catalog
from server.engine.matcher import MatchConfig

router = APIRouter()


class StartRequest(BaseModel):
    group_name: str = ""


class EvaluateRequest(BaseModel):
    text: str


class ConfigUpdate(BaseModel):
    match_mode: str = "either"
    min_price: int = 0
    max_price: int = 999999
    exclude_keywords: list[str] = Field(default_factory=list)
    reply_text: str = "接"
    regions: dict[str, list[str]] = Field(default_factory=dict)


@router.get("/")
def index() -> FileResponse:
    from pathlib import Path

    web_path = Path(__file__).resolve().parents[2] / "web" / "index.html"
    return FileResponse(
        web_path,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/api/status")
def get_status() -> dict:
    bot_service = get_bot_service()
    status = bot_service.status
    payload = {
        "running": status.running,
        "connector_type": status.connector_type,
        "group_name": status.group_name,
        "processed_count": status.processed_count,
        "replied_count": status.replied_count,
        "duplicates_suppressed": status.duplicates_suppressed,
        "last_action": status.last_action,
        "connected": bot_service.connector.is_connected(),
    }
    connector = bot_service.connector
    if hasattr(connector, "get_diagnostics"):
        payload["diagnostics"] = connector.get_diagnostics()
    return payload


@router.post("/api/start")
def start_bot(body: StartRequest) -> dict:
    bot_service = get_bot_service()
    status = bot_service.start(body.group_name)
    return {
        "running": status.running,
        "group_name": status.group_name,
        "last_action": status.last_action,
    }


@router.post("/api/start-detection")
def start_detection() -> dict:
    bot_service = get_bot_service()
    status = bot_service.begin_detection()
    return {
        "running": status.running,
        "last_action": status.last_action,
    }


@router.post("/api/stop")
def stop_bot() -> dict:
    bot_service = get_bot_service()
    status = bot_service.stop()
    return {
        "running": status.running,
        "last_action": status.last_action,
    }


@router.get("/api/config")
def get_config() -> dict:
    config = get_bot_service().get_config()
    payload = config.__dict__
    catalog = load_region_catalog()
    payload["region_selection"] = infer_region_selection(config.regions, catalog)
    return payload


@router.get("/api/regions/catalog")
def get_regions_catalog() -> dict:
    catalog = load_region_catalog()
    groups = {
        "北部": ["台北", "新北", "基隆", "桃園", "新竹", "宜蘭"],
        "中部": ["苗栗", "台中", "彰化", "南投", "雲林"],
        "南部": ["嘉義", "台南", "高雄", "屏東"],
        "東部": ["花蓮", "台東"],
        "離島": ["澎湖", "金門", "連江"],
    }
    return {"groups": groups, "regions": catalog}


@router.put("/api/config")
def update_config(body: ConfigUpdate) -> dict:
    if body.match_mode not in {"either", "both", "origin_only", "dest_only"}:
        raise HTTPException(status_code=400, detail="invalid match_mode")

    config = MatchConfig(
        match_mode=body.match_mode,
        min_price=body.min_price,
        max_price=body.max_price,
        exclude_keywords=body.exclude_keywords,
        reply_text=body.reply_text,
        regions=body.regions,
    )
    get_bot_service().update_config(config)
    return config.__dict__


@router.get("/api/config/stats")
def get_config_stats() -> dict:
    config = get_bot_service().get_config()
    return {region: len(keywords) for region, keywords in config.regions.items()}


@router.post("/api/evaluate")
def evaluate(body: EvaluateRequest) -> dict:
    return get_bot_service().evaluate_text(body.text)


@router.get("/api/logs")
def get_logs(limit: int = 100) -> dict:
    return {"logs": get_bot_service().get_logs(limit=limit)}


@router.post("/api/line/test")
def test_line_connection() -> dict:
    bot_service = get_bot_service()
    connector = bot_service.connector
    if connector.connector_type != "line_win":
        raise HTTPException(status_code=400, detail="only available for line_win connector")

    if not hasattr(connector, "get_diagnostics"):
        raise HTTPException(status_code=400, detail="connector has no diagnostics")

    return connector.get_diagnostics()


@router.post("/api/mock/message")
def mock_message(body: EvaluateRequest) -> dict:
    bot_service = get_bot_service()
    connector = bot_service.connector
    if connector.connector_type != "mock":
        raise HTTPException(status_code=400, detail="mock endpoint only available in mock mode")

    connector.inject_message(body.text)
    return {"ok": True}
