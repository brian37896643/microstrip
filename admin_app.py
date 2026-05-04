import os
import io
import re
import json
import uuid
import hashlib
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ============================================================
# Admin Backend (方案1)
# - DB 預設：data_store_admin（不用 export DB_DIR）
# - 同步伺服器資料夾：新增匯入 + 刪除刷掉（硬刪）
# - 安全：grace_rounds（預設 2）避免 SMB 瞬斷誤刪
# - 後台只讀（無編輯模式）
# - Δ 疊圖：同料號多 sample 疊 Δ，並多一條 Δ mean 平均線
# ============================================================

# ✅ 方案1：後台 DB 固定預設（可用環境變數覆蓋）
STORE_DIR = os.environ.get("DB_DIR", "data_store_admin")
FILES_DIR = os.path.join(STORE_DIR, "files")
META_PATH = os.path.join(STORE_DIR, "metadata.json")

os.makedirs(FILES_DIR, exist_ok=True)

STD_FREQ_COL = "Freq(Hz)"
STD_VAL_COL = "Magnetic Decoupling (dB)"

# 來源資料夾（伺服器掛載後的路徑）
IMPORT_DIR = os.environ.get(
    "CSV_IMPORT_DIR",
    "/mnt/iec_rf_absorber/IEC_RF_MAP/absorber_data"
)

# 是否遞迴掃子資料夾
RECURSIVE = False

# 避免讀到正在複製中的檔案（秒）
MIN_FILE_AGE_SEC = int(os.environ.get("MIN_FILE_AGE_SEC", "3"))

# 刪除緩衝：連續掃不到幾次才刪（預設 2）
GRACE_ROUNDS = int(os.environ.get("CSV_PRUNE_GRACE_ROUNDS", "2"))

st.set_page_config(page_title="吸波材資料庫後台 (Admin)", layout="wide")
st.title("吸波材資料庫後台（Admin）")


# ============================================================
# Metadata I/O (atomic write)
# ============================================================
def load_meta():
    if not os.path.exists(META_PATH):
        return {"datasets": {}, "baseline_id": None}
    with open(META_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_meta(meta: dict):
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = META_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, META_PATH)

meta = load_meta()


# ============================================================
# Filename inference
# ============================================================
def infer_from_filename(filename: str):
    """
    baseline: 檔名前綴 base (case-insensitive)
    material: 檔名數字開頭 -> material_code=開頭數字；thickness_mm=最後兩位/100
    """
    stem = os.path.splitext(os.path.basename(filename))[0].strip()
    s = stem.lower()

    if s.startswith("base"):
        return "baseline", None, None, stem

    m = re.match(r"^(\d+)", stem)
    if m:
        code = m.group(1)
        thk = int(code[-2:]) / 100.0 if len(code) >= 2 else None
        return "material", code, thk, code

    return "material", None, None, stem


# ============================================================
# CSV parsing (Keysight/VNA compatible)
# ============================================================
def read_csv_robust(raw: bytes) -> pd.DataFrame:
    lines = raw.decode("utf-8", errors="ignore").splitlines()
    kept = []
    for line in lines:
        s = line.strip().strip('"').strip()
        if not s or s.startswith("#"):
            continue
        kept.append(line)

    if not kept:
        raise ValueError("CSV 無有效資料（可能全是註解行）")

    df = pd.read_csv(io.StringIO("\n".join(kept)), engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    return df

def standardize_csv(raw: bytes) -> pd.DataFrame:
    """
    轉成標準兩欄：
      Freq(Hz), Magnetic Decoupling (dB)
    """
    df = read_csv_robust(raw)
    lower = {c.lower(): c for c in df.columns}

    def build(f, v):
        out = pd.DataFrame({
            STD_FREQ_COL: pd.to_numeric(df[f], errors="coerce"),
            STD_VAL_COL: pd.to_numeric(df[v], errors="coerce"),
        }).dropna()
        return out.sort_values(STD_FREQ_COL)

    # 標準欄位
    if STD_FREQ_COL.lower() in lower and STD_VAL_COL.lower() in lower:
        return build(lower[STD_FREQ_COL.lower()], lower[STD_VAL_COL.lower()])

    # Keysight 格式
    if "frequency" in lower:
        fd = [c for c in df.columns if c.lower().startswith("formatted data")]
        if fd:
            return build(lower["frequency"], fd[0])

    # fallback：挑兩個最像數字的欄
    scores = [(c, pd.to_numeric(df[c], errors="coerce").notna().sum()) for c in df.columns]
    scores.sort(key=lambda x: x[1], reverse=True)
    if len(scores) >= 2 and scores[0][1] > 0 and scores[1][1] > 0:
        return build(scores[0][0], scores[1][0])

    raise ValueError("無法判斷頻率/數值欄位（請確認 CSV 內容）")

def df_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


# ============================================================
# Helpers
# ============================================================
def pick_latest_baseline_id(meta: dict):
    baselines = [(ds_id, d.get("uploaded_at", "")) for ds_id, d in meta["datasets"].items() if d.get("type") == "baseline"]
    if not baselines:
        return None
    baselines.sort(key=lambda x: x[1], reverse=True)
    return baselines[0][0]

def load_curve_from_stored(stored_filename: str) -> pd.DataFrame:
    path = os.path.join(FILES_DIR, stored_filename)
    df = pd.read_csv(path)
    ghz = pd.to_numeric(df[STD_FREQ_COL], errors="coerce") / 1e9
    db = pd.to_numeric(df[STD_VAL_COL], errors="coerce")
    out = pd.DataFrame({"GHz": ghz, "dB": db}).dropna()
    out = out.sort_values("GHz").drop_duplicates(subset=["GHz"])
    return out

def compute_delta_on_baseline_grid(base_df: pd.DataFrame, mat_df: pd.DataFrame) -> pd.DataFrame:
    """
    Δ = material - baseline
    用 baseline 的 GHz grid 做共同軸，material 插值到 baseline grid
    """
    x = base_df["GHz"].values
    yb = base_df["dB"].values
    xm = mat_df["GHz"].values
    ym = mat_df["dB"].values

    lo = max(np.min(x), np.min(xm))
    hi = min(np.max(x), np.max(xm))
    mask = (x >= lo) & (x <= hi)

    x2 = x[mask]
    yb2 = yb[mask]
    ym2 = np.interp(x2, xm, ym)

    return pd.DataFrame({"GHz": x2, "Delta_dB": ym2 - yb2})


# ============================================================
# Sync (import + prune)
# ============================================================
def auto_sync_from_folder(import_dir: str, grace_rounds: int = 2):
    """
    雙向同步（硬刪）：
      - 新檔名（folder 有、DB 沒有）→ 匯入
      - 已刪檔名（DB 有、folder 沒有）→ 連續 grace_rounds 次掃不到才刪（刪 stored + meta）
    防呆：
      - folder 不存在/不可讀 → 不做刪除清理（避免誤刪整庫）
    """
    p = Path(import_dir)
    if not p.exists() or not p.is_dir():
        return {"folder_cnt": None, "added": 0, "skipped": 0, "failed": 0, "deleted": 0,
                "errors": [f"IMPORT_DIR 不存在或不是資料夾：{import_dir}"]}

    # 掃描現況
    files = list(p.rglob("*")) if RECURSIVE else list(p.iterdir())
    now_ts = datetime.now().timestamp()

    current_names = set()
    for fp in files:
        if fp.is_file() and fp.suffix.lower() == ".csv":   # ✅ .csv / .CSV
            current_names.add(fp.name)

    existing_names = {d.get("original_filename") for d in meta["datasets"].values()}

    added = skipped = failed = deleted = 0
    errors = []

    # 1) import new
    for fp in files:
        if not fp.is_file() or fp.suffix.lower() != ".csv":
            continue

        name = fp.name

        if name in existing_names:
            skipped += 1
            continue

        # 避免 copy 未完成
        if now_ts - fp.stat().st_mtime < MIN_FILE_AGE_SEC:
            skipped += 1
            continue

        try:
            df_std = standardize_csv(fp.read_bytes())
            dtype, code, thk, label = infer_from_filename(name)

            ds_id = str(uuid.uuid4())
            stored = f"{ds_id}.csv"
            df_std.to_csv(os.path.join(FILES_DIR, stored), index=False)

            meta["datasets"][ds_id] = {
                "id": ds_id,
                "type": dtype,
                "material_code": code,
                "label": label,
                "thickness_mm": thk,
                "original_filename": name,
                "source_path": str(fp),
                "stored_filename": stored,
                "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "hash": df_hash(df_std),
                "note": "",
            }

            if dtype == "baseline":
                meta["baseline_id"] = ds_id

            existing_names.add(name)
            added += 1

        except Exception as e:
            failed += 1
            errors.append(f"{name} 匯入失敗：{e}")

    # 2) prune deleted
    for ds_id, d in list(meta["datasets"].items()):
        src = d.get("original_filename")
        if not src:
            continue

        if src in current_names:
            d.pop("missing_count", None)
            continue

        d["missing_count"] = int(d.get("missing_count", 0)) + 1

        if d["missing_count"] >= grace_rounds:
            # 硬刪：刪 stored file + 移除 meta
            stored = d.get("stored_filename")
            if stored:
                p_stored = os.path.join(FILES_DIR, stored)
                if os.path.exists(p_stored):
                    os.remove(p_stored)
            meta["datasets"].pop(ds_id, None)
            deleted += 1

    # baseline 修正
    if meta.get("baseline_id") not in meta["datasets"] or (
        meta.get("baseline_id")
        and meta["datasets"].get(meta["baseline_id"], {}).get("type") != "baseline"
    ):
        meta["baseline_id"] = pick_latest_baseline_id(meta)

    save_meta(meta)
    return {"folder_cnt": len(current_names), "added": added, "skipped": skipped, "failed": failed,
            "deleted": deleted, "errors": errors}


sync = auto_sync_from_folder(IMPORT_DIR, grace_rounds=GRACE_ROUNDS)


# ============================================================
# UI Tabs
# ============================================================
tab_status, tab_list, tab_plot = st.tabs(["📌 狀態", "📋 資料列表（只讀）", "📈 Δ 疊圖（含平均）"])


# -----------------------------
# Tab 1: Status
# -----------------------------
with tab_status:
    st.write("來源資料夾：", IMPORT_DIR)
    st.write(f"本次同步：新增 {sync['added']} / 略過 {sync['skipped']} / 失敗 {sync['failed']} / 刪除 {sync['deleted']}")
    st.caption(f"刪除 grace_rounds = {GRACE_ROUNDS}")

    if sync["folder_cnt"] is None:
        st.warning("來源資料夾不可讀 → 不做刪除清理（防止誤刪整庫）")
    else:
        st.write("來源資料夾 CSV 數量：", sync["folder_cnt"])

    total_db = len(meta["datasets"])
    n_base = sum(1 for d in meta["datasets"].values() if d.get("type") == "baseline")
    n_mat = sum(1 for d in meta["datasets"].values() if d.get("type") == "material")
    st.write(f"目前 DB 筆數：{total_db}（baseline={n_base}, material={n_mat}）")
    st.write("baseline_id：", meta.get("baseline_id"))

    if sync["errors"]:
        st.warning("同步錯誤（最多顯示 20 筆）：")
        for e in sync["errors"][:20]:
            st.write("-", e)


# -----------------------------
# Tab 2: Read-only list
# -----------------------------
with tab_list:
    if not meta["datasets"]:
        st.info("目前沒有資料")
    else:
        df = pd.DataFrame([
            {
                "type": d.get("type"),
                "material_code": d.get("material_code"),
                "label": d.get("label"),
                "thickness_mm": d.get("thickness_mm"),
                "original_filename": d.get("original_filename"),
                "uploaded_at": d.get("uploaded_at"),
                "missing_count": d.get("missing_count", 0),
                "source_path": d.get("source_path", ""),
            }
            for d in meta["datasets"].values()
        ]).sort_values(["type", "uploaded_at"], ascending=[True, False])

        st.dataframe(df, width="stretch")
        st.caption("missing_count：來源資料夾掃不到該檔案的連續次數（達到 grace_rounds 才會刪除）")


# -----------------------------
# Tab 3: Δ plot + mean
# -----------------------------
with tab_plot:
    baseline_id = meta.get("baseline_id")
    if not baseline_id or baseline_id not in meta["datasets"]:
        st.warning("目前沒有 baseline_id（請確認 base* 檔案存在於來源資料夾）")
        st.stop()

    base_curve = load_curve_from_stored(meta["datasets"][baseline_id]["stored_filename"])

    codes = sorted({
        d.get("material_code")
        for d in meta["datasets"].values()
        if d.get("type") == "material" and d.get("material_code") not in (None, "", "None")
    })

    if not codes:
        st.info("目前沒有 material 資料")
        st.stop()

    code_sel = st.selectbox("選擇料號（material_code）", codes)

    samples = [
        d for d in meta["datasets"].values()
        if d.get("type") == "material" and str(d.get("material_code")) == str(code_sel)
    ]

    st.caption(f"料號 {code_sel}：{len(samples)} 筆 sample")

    fig = go.Figure()
    delta_list = []
    last_delta_df = None

    # 每條 sample Δ
    for d in samples:
        mat_curve = load_curve_from_stored(d["stored_filename"])
        delta_df = compute_delta_on_baseline_grid(base_curve, mat_curve)
        last_delta_df = delta_df

        fig.add_trace(go.Scatter(
            x=delta_df["GHz"],
            y=delta_df["Delta_dB"],
            mode="lines",
            name=d.get("original_filename", d.get("label", "")),
        ))

        delta_list.append(delta_df["Delta_dB"].values)

    # 平均線
    if len(delta_list) >= 2 and last_delta_df is not None:
        Y = np.vstack(delta_list)
        mean_y = np.mean(Y, axis=0)

        fig.add_trace(go.Scatter(
            x=last_delta_df["GHz"],
            y=mean_y,
            mode="lines",
            name="Δ mean",
            line=dict(width=4, dash="dash"),
        ))

    fig.update_layout(
        title=f"Δ 疊圖（含平均）：{code_sel}（Δ = material - baseline）",
        xaxis_title="Frequency (GHz)",
        yaxis_title="Δ (dB)",
        legend_title="Samples",
    )

    st.plotly_chart(fig, width="stretch")