# LINE 搶單 Bot

監控 LINE 群組派單訊息，符合南部地區條件時自動回覆「接」。

## 功能

- 派單正則解析
- 嘉義 / 台南 / 高雄 / 屏東 完整地區關鍵字
- 本機 Web 後台（編輯關鍵字、開始/停止監控）
- **Phase 2**：Windows LINE.exe UI 自動化（讀訊息 + 回覆）
- Mac 開發用 Mock 連接器

## 環境需求

- Python 3.11+（Windows 部署建議 3.11 或 3.12）
- macOS：開發與規則測試
- Windows 10/11：實際連接 LINE 桌面版

## 安裝

### Mac / 開發

```bash
cd linebot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows / 部署

```powershell
cd linebot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-windows.txt
```

## 啟動

### Mac（Mock 模式）

```bash
python -m server.main --connector mock
```

### Windows（自動使用 LINE.exe）

```powershell
python -m server.main --connector auto
```

瀏覽器開啟：http://127.0.0.1:8080

## Windows 使用前準備

1. 安裝並登入 [LINE 桌面版](https://line.me/download)
2. **手動點開**目標群組聊天室（例如：優先承攬-尊爵會員）
3. 電腦不要休眠，LINE 視窗保持可見
4. 後台點「**開始監控**」（群組名稱欄僅供紀錄）
5. Bot 會監聽**目前畫面上**的聊天室新訊息並自動回「接」

### 常見錯誤：`CoInitialize has not been called`

監控執行緒已使用 `UIAutomationInitializerInThread` 初始化 COM。若仍出現此錯誤，請更新程式後重啟 Bot。

### UI 除錯（讀不到訊息時）

```powershell
python scripts/inspect_line_ui.py --keyword 優先承攬
```

把輸出貼回來，可協助調整 UI 控件定位。請先**手動開啟**目標群組再執行。

## 測試

```bash
pytest -q
```

## 專案結構

```
server/engine/          規則引擎（parser, matcher）
server/connector/
  mock.py               Mac 測試用
  line_win/             Windows LINE.exe 自動化
  factory.py            依平台選擇連接器
server/core/            Bot 主流程
server/api/             FastAPI 路由
web/                    後台介面
scripts/inspect_line_ui.py   Windows UI 除錯
data/                   地區設定、SQLite
tests/
```

## 連接器模式

| 模式 | 說明 |
|------|------|
| `auto` | Windows 用 LINE.exe，其他平台用 mock |
| `mock` | 模擬訊息（Mac 開發） |
| `line_win` | 強制使用 LINE.exe（僅 Windows） |

環境變數：`LINEBOT_CONNECTOR=mock|auto|line_win`
