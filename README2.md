# Absorber Streamlit Apps（前台 / 後台）

本專案包含兩個 Streamlit App：

* **前台（frontend\_app.py）**：使用者查詢（單頻點/頻帶 + 厚度篩選 + 排名）。
* **後台（admin\_app.py）**：管理者監看/看圖（同步狀態、資料列表只讀、Δ 疊圖）。

> ⚠️ \*\*前後台不互相同步資料庫\*\*：
> - 兩個 App 都會同步同一個「伺服器資料夾」(CSV\_IMPORT\_DIR)
> - 但各自維護自己的 DB 目錄 (DB\_DIR)，互不影響。

\---

## 1\. 檔案結構（建議）

```text
.
├─ frontend\_app.py                 # 前台：查詢 + 排名
├─ admin\_app.py                    # 後台：只讀 + Δ 疊圖
├─ requirements.txt                # Python 依賴
├─ README.md
└─ .streamlit/
   └─ config.toml                  # (可選) Streamlit 設定
```

\---

## 2\. 環境需求

* Python 3.10+（建議 3.10/3.11）
* Linux（建議；本專案的資料來源通常是 SMB share 掛載到 `/mnt/...`）

安裝依賴：

```bash
pip install -r requirements.txt
```

\---

## 3\. 資料來源（伺服器資料夾）

兩個 App 都會掃描同一個資料來源資料夾：

* **CSV\_IMPORT\_DIR**：伺服器 CSV 資料夾（建議為 Linux mount 後的路徑）

  * 例：`/mnt/iec\_rf\_absorber/IEC\_RF\_MAP/absorber\_data`

> 若資料來源是 Windows Share（例如 `\\\\iec1-td6server\\RF\_SERVER$\\...`），
> 請先在 Linux 上用 CIFS/SMB 掛載成 `/mnt/...`，再把 `CSV\_IMPORT\_DIR` 指到掛載後的路徑。

\---

## 4\. 同步機制（新增 + 刪除）

兩個 App 在啟動/重跑時會同步資料夾：

* **新增**：資料夾出現新 CSV 檔 → 匯入 DB
* **刪除**：資料夾檔案被刪掉 → DB 也會刷掉對應資料（硬刪除，含刪 cache 檔）

為避免 SMB/掛載短暫抖動造成誤刪，刪除有「緩衝」：

* **CSV\_PRUNE\_GRACE\_ROUNDS**（預設 2）

  * 代表連續掃不到 `N` 次才真的刪除。
  * 測試時可設為 1（立即刪），正式建議 2 或 3。

\---

## 5\. DB 分離（前台一個、後台一個）

### 5.1 建議 DB 目錄

* 後台（Admin）：`DB\_DIR=data\_store\_admin`
* 前台（Frontend）：`DB\_DIR=data\_store\_frontend`

> 我們的程式碼預設已各自指向不同 DB\_DIR（方案1）。
> 若要覆蓋，可用環境變數 `DB\_DIR` 指定。

\---

## 6\. 啟動方式（命令列）

### 6.1 後台（Admin）

```bash
export CSV\_IMPORT\_DIR=/mnt/iec\_rf\_absorber/IEC\_RF\_MAP/absorber\_data
export CSV\_PRUNE\_GRACE\_ROUNDS=2
# 可選：覆蓋 DB 位置（若不設定則使用程式預設）
# export DB\_DIR=data\_store\_admin

streamlit run admin\_app.py --server.port 8502 --server.address 0.0.0.0
```

### 6.2 前台（Frontend）

```bash
export CSV\_IMPORT\_DIR=/mnt/iec\_rf\_absorber/IEC\_RF\_MAP/absorber\_data
export CSV\_PRUNE\_GRACE\_ROUNDS=2
# 可選：覆蓋 DB 位置（若不設定則使用程式預設）
# export DB\_DIR=data\_store\_frontend

streamlit run frontend\_app.py --server.port 8501 --server.address 0.0.0.0
```

\---

## 7\. systemd 服務（推薦部署方式）

> 以下示範以 `brian` 使用者、專案位於 `/home/brian/my\_streamlit\_app`。
> 請依實際環境調整。

### 7.1 前台：/etc/systemd/system/absorber-frontend.service

```ini
\[Unit]
Description=Absorber Frontend (Streamlit)
After=network-online.target
Wants=network-online.target

\[Service]
User=brian
WorkingDirectory=/home/brian/my\_streamlit\_app
Environment=CSV\_IMPORT\_DIR=/mnt/iec\_rf\_absorber/IEC\_RF\_MAP/absorber\_data
Environment=CSV\_PRUNE\_GRACE\_ROUNDS=2
Environment=DB\_DIR=data\_store\_frontend
ExecStart=/usr/bin/python3 -m streamlit run frontend\_app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=3

\[Install]
WantedBy=multi-user.target
```

### 7.2 後台：/etc/systemd/system/absorber-admin.service

```ini
\[Unit]
Description=Absorber Admin (Streamlit)
After=network-online.target
Wants=network-online.target

\[Service]
User=brian
WorkingDirectory=/home/brian/my\_streamlit\_app
Environment=CSV\_IMPORT\_DIR=/mnt/iec\_rf\_absorber/IEC\_RF\_MAP/absorber\_data
Environment=CSV\_PRUNE\_GRACE\_ROUNDS=2
Environment=DB\_DIR=data\_store\_admin
ExecStart=/usr/bin/python3 -m streamlit run admin\_app.py --server.port 8502 --server.address 0.0.0.0
Restart=always
RestartSec=3

\[Install]
WantedBy=multi-user.target
```

啟用與啟動：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now absorber-frontend.service
sudo systemctl enable --now absorber-admin.service

sudo systemctl status absorber-frontend.service --no-pager
sudo systemctl status absorber-admin.service --no-pager
```

\---

## 8\. 常見問題（Troubleshooting）

### 8.1 顯示 IMPORT\_DIR 不存在

* 請確認 `CSV\_IMPORT\_DIR` 指向的路徑存在且可讀。
* 若資料來自 Windows share，請先 mount 到 Linux（例如 `/mnt/iec\_rf\_absorber`）。

### 8.2 刪檔後 DB 沒立刻消失

* 可能是 `CSV\_PRUNE\_GRACE\_ROUNDS=2`，需要連續兩次同步才會刪除。
* 測試可改 `CSV\_PRUNE\_GRACE\_ROUNDS=1`。

### 8.3 前後台資料筆數不同

* 正常：前後台 DB 不共用（各自同步），時間點不同可能不同步。
* 兩邊都重啟/重跑一次後應趨於一致（以伺服器資料夾為準）。

\---

## 9\. 安全提醒

* **請不要把帳密寫在程式碼**。
* 若需 mount SMB share，建議使用 credentials 檔並設 `chmod 600`。

