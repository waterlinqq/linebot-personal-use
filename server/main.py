from __future__ import annotations

import argparse
import os

import uvicorn
from fastapi import FastAPI

from server.api.routes import router
from server.app_state import init_bot_service

app = FastAPI(title="LINE 搶單 Bot", version="0.2.0")
app.include_router(router)


def main() -> None:
    parser = argparse.ArgumentParser(description="LINE 搶單 Bot")
    parser.add_argument(
        "--connector",
        choices=["auto", "mock", "ocr", "line_win"],
        default=os.environ.get("LINEBOT_CONNECTOR", "auto"),
        help="連接器模式：ocr=跨平台畫面辨識；auto=已校準時 OCR，否則 mock",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    init_bot_service(args.connector)
    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
