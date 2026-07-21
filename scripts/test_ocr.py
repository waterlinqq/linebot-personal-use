"""擷取設定區域並列出 OCR 結果，不會發送 LINE 訊息。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.connector.ocr import (  # noqa: E402
    ScreenRegion,
    TesseractScreenSource,
    load_ocr_config,
)


def main() -> None:
    config = load_ocr_config()
    region_value = os.environ.get("LINEBOT_OCR_REGION") or config.get("region", "")
    if not region_value:
        raise SystemExit("缺少 LINEBOT_OCR_REGION，請先執行 scripts/calibrate_ocr.py")

    source = TesseractScreenSource(
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
    source.activate_target()
    preview_path = ROOT / "data" / "ocr_preview.png"
    source.capture_image().save(preview_path)
    print(f"截圖預覽已儲存：{preview_path}")

    blocks = source.read_blocks()

    print(f"辨識到 {len(blocks)} 個文字區塊：")
    for index, block in enumerate(blocks, start=1):
        print(f"{index:02d}. {block.text}")

    if not blocks:
        print("未辨識到文字：請確認區域、螢幕錄製權限及中文語言包。")


if __name__ == "__main__":
    main()
