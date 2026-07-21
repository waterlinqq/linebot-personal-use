from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.app_state import get_bot_service
from server.engine.matcher import MatchConfig

router = APIRouter()


class StartRequest(BaseModel):
    group_name: str = "優先承攬-尊爵會員"


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
    return FileResponse(web_path)


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
    return get_bot_service().get_config().__dict__


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


@router.post("/api/config/reload-defaults")
def reload_default_regions() -> dict:
    return get_bot_service().reload_default_regions().__dict__


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


@router.post("/api/mock/message")
def mock_message(body: EvaluateRequest) -> dict:
    bot_service = get_bot_service()
    connector = bot_service.connector
    if connector.connector_type != "mock":
        raise HTTPException(status_code=400, detail="mock endpoint only available in mock mode")

    connector.inject_message(body.text)
    return {"ok": True}
