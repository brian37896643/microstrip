# microstrip (Streamlit Plotly CSV Plotter)

一個 Streamlit 小工具：上傳多個 CSV 疊圖、每條曲線可勾選顯示/隱藏、可手動改圖例名稱、支援 X 軸線性/對數，並支援 PNG/HTML 下載。

> ✅ 你要的「放大後的圖」下載方式：  
> 請先點圖右上角 **Fullscreen**，再點 **相機（Download plot as png）**，下載的就是放大狀態的 PNG。

---

## Features
- 多 CSV 疊圖（可多選上傳）
- 每條曲線旁有勾選框：顯示/隱藏
- 圖例名稱可手動修改
- X 軸：線性 / 對數（預設對數）
- 下載：
  - **Fullscreen 後用 Plotly 相機下載**（最符合「放大後」）
  - App 內「固定規格 PNG」下載（需要 kaleido + Chrome）
  - 互動式 HTML 下載

---

## Quick Start

### 1) 安裝套件
```bash
pip install -r requirements.txt
```

### 2) 執行
```bash
streamlit run app6.py
```

---

## PNG 下載說明

### A) 下載「放大後」的 PNG（推薦）
1. 圖右上角按 **Fullscreen**
2. 再按 **相機 Download plot as png**

> 這個方式在瀏覽器端輸出，會最貼近你當下放大的畫面。

### B) App 內「固定規格 PNG」下載（伺服器端）
- 需要 `kaleido` + Chrome/Chromium
- Linux/headless 環境常見要補系統依賴套件

#### Chrome 安裝（無 root 也可）
```bash
plotly_get_chrome
```

#### Ubuntu/Debian 常見系統依賴（需要 sudo）
```bash
sudo apt update
sudo apt-get install -y   libnss3 libatk-bridge2.0-0 libcups2   libxcomposite1 libxdamage1 libxfixes3 libxrandr2   libgbm1 libxkbcommon0   libpango-1.0-0 libcairo2   libasound2
```

---

## Repo 建議
- 建議不要把量測資料（CSV）、資料庫資料夾、快取資料推上 GitHub
- Windows 下載/搬檔可能產生 `*:Zone.Identifier`，已在 `.gitignore` 忽略

---

## License
Internal / private use (adjust if needed).
