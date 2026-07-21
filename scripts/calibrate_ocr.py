"""互動式設定 OCR 截圖區域與 LINE 訊息輸入點。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.connector.ocr import save_ocr_config  # noqa: E402


def capture_points() -> list[tuple[int, int]]:
    prompts = [
        "點擊聊天室訊息區域的左上角",
        "點擊聊天室訊息區域的右下角",
        "點擊 LINE 訊息輸入框中央",
    ]
    points: list[tuple[int, int]] = []
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.25)
    root.configure(bg="black")
    label = tk.Label(
        root,
        text=prompts[0],
        bg="black",
        fg="white",
        font=("Arial", 28, "bold"),
    )
    label.pack(pady=50)

    def on_click(event: tk.Event) -> None:
        points.append((event.x_root, event.y_root))
        if len(points) == len(prompts):
            root.destroy()
            return
        label.config(text=prompts[len(points)])

    root.bind("<Button-1>", on_click)
    root.bind("<Escape>", lambda _: root.destroy())
    root.mainloop()
    return points


def main() -> None:
    print("LINE Bot OCR 校準")
    print("請先將 LINE 視窗固定在日後運行時的位置與大小。")
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "LINE" to activate'],
            check=False,
        )
        time.sleep(1)

    points = capture_points()
    if len(points) != 3:
        raise SystemExit("校準已取消。")
    (left, top), (right, bottom), (input_x, input_y) = points

    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        raise SystemExit("右下角必須位於左上角的右下方，請重新執行。")

    region = f"{left},{top},{width},{height}"
    input_point = f"{input_x},{input_y}"
    save_ocr_config(region, input_point)

    print("\n校準已保存至 data/ocr_config.json。")
    print("現在可直接執行：python scripts/test_ocr.py")
    print("\n如需暫時覆寫，macOS/Linux 當前終端機可執行：")
    print(f"export LINEBOT_OCR_REGION='{region}'")
    print(f"export LINEBOT_INPUT_POINT='{input_point}'")
    print("\nWindows PowerShell 當前視窗請執行：")
    print(f"$env:LINEBOT_OCR_REGION='{region}'")
    print(f"$env:LINEBOT_INPUT_POINT='{input_point}'")


if __name__ == "__main__":
    main()
