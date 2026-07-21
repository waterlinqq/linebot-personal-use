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
    parser.add_argument(
        "--details",
        action="store_true",
        help="檢查 AutomationId、ClassName、Value/Text/Legacy patterns",
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="只輸出找到 Name、Value、Text 或 Legacy 文字的控件",
    )
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

    def pattern_text(control: auto.Control) -> str:
        values: list[str] = []
        for pattern_id, label, reader in (
            (auto.PatternId.ValuePattern, "Value", lambda pattern: pattern.Value),
            (
                auto.PatternId.TextPattern,
                "Text",
                lambda pattern: pattern.DocumentRange.GetText(-1),
            ),
            (
                auto.PatternId.LegacyIAccessiblePattern,
                "LegacyName",
                lambda pattern: pattern.Name,
            ),
            (
                auto.PatternId.LegacyIAccessiblePattern,
                "LegacyValue",
                lambda pattern: pattern.Value,
            ),
        ):
            try:
                pattern = control.GetPattern(pattern_id)
                value = reader(pattern) if pattern else ""
                value = str(value or "").replace("\n", " ")[:200]
                if value:
                    values.append(f"{label}={value!r}")
            except Exception:  # noqa: BLE001
                continue
        return " ".join(values)

    def walk(control: auto.Control, depth: int, prefix: str = "") -> None:
        if depth < 0:
            return
        try:
            name = (control.Name or "").replace("\n", " ")[:120]
            ctype = control.ControlTypeName
            line = f"{prefix}[{ctype}] {name!r}"
            patterns = ""
            if args.details:
                line += (
                    f" AutomationId={control.AutomationId!r}"
                    f" ClassName={control.ClassName!r}"
                    f" Rect={control.BoundingRectangle}"
                )
                patterns = pattern_text(control)
                if patterns:
                    line += f" {patterns}"
            has_text = bool(name or patterns)
            if (
                (not args.text_only or has_text)
                and (not args.keyword or args.keyword in line)
            ):
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
    print("完成。若 Name 仍為空，請加上 --details 檢查其他文字介面。")


if __name__ == "__main__":
    main()
