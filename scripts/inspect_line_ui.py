"""Windows 專用：探索 LINE.exe UI 結構，協助除錯 Phase 2 連接器。

用法（在 Windows PowerShell）：
    python scripts/inspect_line_ui.py
    python scripts/inspect_line_ui.py --keyword 優先承攬
"""

from __future__ import annotations

import argparse
import sys

import psutil


def main() -> None:
    if sys.platform != "win32":
        print("此腳本僅能在 Windows 上執行")
        sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", default="", help="搜尋包含此文字的控件")
    parser.add_argument("--depth", type=int, default=3, help="輸出控件樹深度")
    args = parser.parse_args()

    import uiautomation as auto  # type: ignore[import-untyped]

    root = auto.GetRootControl()
    line_windows = []
    for child in root.GetChildren():
        if child.ControlType != auto.ControlType.WindowControl:
            continue
        try:
            process_name = psutil.Process(int(child.ProcessId)).name().lower()
        except (psutil.Error, OSError):
            continue
        if process_name == "line.exe":
            line_windows.append(child)

    if not line_windows:
        print("找不到 LINE 視窗。請先開啟 LINE 桌面版。")
        sys.exit(2)

    window = line_windows[0]
    process_name = psutil.Process(int(window.ProcessId)).name()
    print(
        f"LINE 視窗: {window.Name!r} / "
        f"ClassName={window.ClassName!r} / "
        f"PID={window.ProcessId} / Process={process_name!r}"
    )
    print("-" * 60)

    def walk(control: auto.Control, depth: int, prefix: str = "") -> None:
        if depth < 0:
            return
        try:
            name = (control.Name or "").replace("\n", " ")[:120]
            ctype = control.ControlTypeName
            line = f"{prefix}[{ctype}] {name!r}"
            if not args.keyword or args.keyword in name:
                print(line)
        except Exception as exc:  # noqa: BLE001
            print(f"{prefix}[?] <error: {exc}>")
            return

        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return
        for index, child in enumerate(children[:80]):
            walk(child, depth - 1, prefix + "  ")

    walk(window, args.depth)
    print("-" * 60)
    print("完成。若看不到聊天訊息控件，請開啟目標群組後再跑一次。")


if __name__ == "__main__":
    main()
