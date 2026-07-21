# LINE 搶單 Bot

監控 LINE 群組派單訊息，符合南部地區條件時自動回覆「接」。

## 功能

- 派單正則解析
- 嘉義 / 台南 / 高雄 / 屏東 完整地區關鍵字
- 本機 Web 後台（編輯關鍵字、開始/停止監控）
- 跨平台 OCR：讀取目前開啟的 LINE 聊天畫面並回覆
- Mac 開發用 Mock 連接器

## 環境需求

- Python 3.11+（Windows 部署建議 3.11 或 3.12）
- macOS：可測真實 LINE Desktop OCR
- Windows 10/11：正式部署

## 安裝

### macOS OCR

```bash
cd linebot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-ocr.txt
brew install tesseract tesseract-lang
```

### Windows / 部署

```powershell
cd linebot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-windows.txt
```

## OCR 校準與啟動

LINE Desktop 的聊天文字沒有公開給 Windows UI Automation，因此正式讀取方式為螢幕 OCR。

1. 開啟 LINE Desktop，手動進入目標群組。
2. 固定 LINE 視窗的位置與大小。
3. 執行校準：

```bash
python scripts/calibrate_ocr.py
```

4. 依校準工具輸出設定 `LINEBOT_OCR_REGION` 與 `LINEBOT_INPUT_POINT`。
5. 先做只讀測試（不會發送訊息）：

```bash
python scripts/test_ocr.py
```

6. 確認 OCR 能讀到派單文字後啟動：

```bash
python -m server.main --connector ocr
```

瀏覽器開啟：http://127.0.0.1:8080，再按「開始監控」。

### macOS 權限

請在「系統設定 → 隱私權與安全性」允許執行程式：

- 螢幕錄製
- 輔助使用

### Windows Tesseract

安裝 Tesseract 及繁體中文 `chi_tra` 語言資料。若不在 PATH：

```powershell
$env:LINEBOT_TESSERACT_CMD='C:\Program Files\Tesseract-OCR\tesseract.exe'
```

### Mock 模式

```bash
python -m server.main --connector mock
```

## 測試

```bash
pytest -q
```

## 專案結構

```
server/engine/          規則引擎（parser, matcher）
server/connector/
  mock.py               Mac 測試用
  ocr.py                跨平台 OCR 連接器
  line_win/             Windows UIA 診斷用
  factory.py            依平台選擇連接器
server/core/            Bot 主流程
server/api/             FastAPI 路由
web/                    後台介面
scripts/calibrate_ocr.py     OCR 區域校準
scripts/test_ocr.py          OCR 只讀測試
scripts/inspect_line_ui.py   Windows UIA 診斷
data/                   地區設定、SQLite
tests/
```

## 連接器模式

| 模式 | 說明 |
|------|------|
| `auto` | 已設定 OCR 區域時使用 OCR，否則 mock |
| `mock` | 模擬訊息（Mac 開發） |
| `ocr` | 跨平台 OCR（建議正式使用） |
| `line_win` | Windows UIA 診斷；LINE 聊天文字目前不可讀 |

環境變數：

- `LINEBOT_CONNECTOR=mock|ocr|auto|line_win`
- `LINEBOT_OCR_REGION=left,top,width,height`
- `LINEBOT_INPUT_POINT=x,y`
- `LINEBOT_OCR_LANG=chi_tra+eng`
- `LINEBOT_TESSERACT_CMD=...`（選用）
