
# Microstrip Calculators (Streamlit)

一組可直接使用的 **微帶線計算器**：
- **`app_4in1_vertical_v2.py`**：四求一一般版（可解 Z0、w、h、εr、t），右側 **進階（搜尋上下界）置頂**。
- **`app_4in1.py`**：四求一（含 t），水平版面。
- **`app_4in1_vertical.py`**：四求一（含 t），左直排 + 右結果。
- **`tuner_50ohm.py`**：固定三個自動求解 **命中目標 Z0**（預設 50 Ω，可改）。
- **`app.py`**：通用資料分析範例（非微帶線；可忽略）。

> 公式採 **Hammerstad–Jensen 準靜態閉式（含厚度修正）**，適合單端外層微帶的尺寸**初估/反算**，未含頻散、損耗、阻焊層、粗糙度等；嚴格容差請用 2D/3D 場解或板廠阻抗表校核。

---

## 快速開始（本機 / WSL）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 建議使用這個做為入口：
streamlit run app_4in1_vertical_v2.py
# 或：streamlit run tuner_50ohm.py
```

打開瀏覽器 `http://localhost:8501` 即可使用。

---

## 在 Streamlit Community Cloud 分享

1. **Fork** 或 **Push** 本 repo 到你的 GitHub 帳號。
2. 打開 <https://share.streamlit.io>，登入後 **New app**。
3. 選擇 repo 與 branch，**Main file path** 指向 `app_4in1_vertical_v2.py`。
4. Deploy 後把產生的 **Public URL** 分享給同事即可。

> Community Cloud 會自動依 `requirements.txt` 安裝相依套件；若新增套件，記得更新 `requirements.txt`。

---

## 專案結構建議

```
my_streamlit_app/
├─ app_4in1_vertical_v2.py
├─ tuner_50ohm.py
├─ app_4in1.py
├─ app_4in1_vertical.py
├─ requirements.txt
├─ .gitignore
└─ README.md
```

---

## License

預設未附授權；若需對外公開，建議加上 **MIT License** 或公司內部授權政策。
