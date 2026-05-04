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

# ============================================================
# Frontend App（方案1｜獨立 DB｜同步新增+刪除刷掉｜只給查詢 UI）
# ============================================================
# - DB 預設：data_store_frontend（不用 export DB_DIR）
# - 來源：掃 CSV_IMPORT_DIR（伺服器資料夾），同步：
#     * 新檔（同檔名未入庫）→ 匯入
#     * 來源刪檔 → DB 也刷掉（硬刪除，含刪 stored file；grace_rounds 防誤刪）
# - UI：
#     * 單頻點 / 頻帶
#     * 頻率單位
#     * 厚度篩選（可留空=不限；輸入數字=精準匹配到小數第2位）
# - 排名：降低 dB 越大越好
#     Δ = material - baseline
#     drop = baseline - material = -Δ
#     單頻點：drop_point = -Δ(f0)
#     頻帶： drop_band = -max(Δ)（band 內最小下降量）
# - 同料號多 sample：先平均 Δ 曲線（baseline grid）再算 drop
# - rank 欄位固定在最左：用 index 顯示（Streamlit 原生不支援 freeze column）
# - ✅ 已移除「下載結果 CSV」按鈕
# ============================================================

# -----------------------------
# Paths & constants
# -----------------------------
STORE_DIR = os.environ.get("DB_DIR", "data_store_frontend")
FILES_DIR = os.path.join(STORE_DIR, "files")
META_PATH = os.path.join(STORE_DIR, "metadata.json")

os.makedirs(FILES_DIR, exist_ok=True)

STD_FREQ_COL = "Freq(Hz)"
STD_VAL_COL = "Magnetic Decoupling (dB)"

IMPORT_DIR = os.environ.get(
    "CSV_IMPORT_DIR",
    "/mnt/iec_rf_absorber/IEC_RF_MAP/absorber_data",
)

RECURSIVE = False
MIN_FILE_AGE_SEC = int(os.environ.get("MIN_FILE_AGE_SEC", "3"))
GRACE_ROUNDS = int(os.environ.get("CSV_PRUNE_GRACE_ROUNDS", "2"))

st.set_page_config(page_title="Absorber Query", layout="wide")
st.title("吸波材查詢（前台）")


# -----------------------------
# Metadata I/O (atomic write)
# -----------------------------

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


# -----------------------------
# Filename inference
# -----------------------------

def infer_from_filename(filename: str):
    stem = os.path.splitext(os.path.basename(filename))[0].strip()
    s = stem.lower()

    if s.startswith("base"):
        return "baseline", None, None, stem

    m = re.match(r"^(\d+)", stem)
    if m:
        code = m.group(1)
        thickness = int(code[-2:]) / 100.0 if len(code) >= 2 else None
        return "material", code, thickness, code

    return "material", None, None, stem


# -----------------------------
# CSV parsing
# -----------------------------

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
    df = read_csv_robust(raw)
    lower = {c.lower(): c for c in df.columns}

    def build(f, v):
        out = pd.DataFrame({
            STD_FREQ_COL: pd.to_numeric(df[f], errors="coerce"),
            STD_VAL_COL: pd.to_numeric(df[v], errors="coerce"),
        }).dropna()
        return out.sort_values(STD_FREQ_COL)

    # Standard
    if STD_FREQ_COL.lower() in lower and STD_VAL_COL.lower() in lower:
        return build(lower[STD_FREQ_COL.lower()], lower[STD_VAL_COL.lower()])

    # Keysight
    if "frequency" in lower:
        fd = [c for c in df.columns if c.lower().startswith("formatted data")]
        if fd:
            return build(lower["frequency"], fd[0])

    # fallback numeric-ish
    scores = [(c, pd.to_numeric(df[c], errors="coerce").notna().sum()) for c in df.columns]
    scores.sort(key=lambda x: x[1], reverse=True)
    if len(scores) >= 2 and scores[0][1] > 0 and scores[1][1] > 0:
        return build(scores[0][0], scores[1][0])

    raise ValueError("無法判斷頻率/數值欄位（請確認 CSV 內容）")


def df_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


# -----------------------------
# Curve helpers
# -----------------------------

def load_curve_from_stored(stored_filename: str) -> pd.DataFrame:
    path = os.path.join(FILES_DIR, stored_filename)
    df = pd.read_csv(path)
    ghz = pd.to_numeric(df[STD_FREQ_COL], errors="coerce") / 1e9
    db = pd.to_numeric(df[STD_VAL_COL], errors="coerce")
    out = pd.DataFrame({"GHz": ghz, "dB": db}).dropna()
    out = out.sort_values("GHz").drop_duplicates(subset=["GHz"])
    return out


def compute_delta_on_baseline_grid(base_df: pd.DataFrame, mat_df: pd.DataFrame) -> pd.DataFrame:
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


def pick_latest_baseline_id(meta: dict):
    baselines = []
    for ds_id, d in meta["datasets"].items():
        if d.get("type") == "baseline":
            baselines.append((ds_id, d.get("uploaded_at", "")))
    if not baselines:
        return None
    baselines.sort(key=lambda x: x[1], reverse=True)
    return baselines[0][0]


# -----------------------------
# Sync + prune (frontend local DB)
# -----------------------------

def auto_sync_from_folder(import_dir: str, grace_rounds: int = 2):
    """新增匯入 + 刪除刷掉（硬刪），依檔名對齊。"""
    p = Path(import_dir)
    if not p.exists() or not p.is_dir():
        return

    files = list(p.rglob("*")) if RECURSIVE else list(p.iterdir())
    now_ts = datetime.now().timestamp()

    current_names = {fp.name for fp in files if fp.is_file() and fp.suffix.lower() == ".csv"}
    existing_names = {d.get("original_filename") for d in meta["datasets"].values()}

    # import
    for fp in files:
        if not fp.is_file() or fp.suffix.lower() != ".csv":
            continue
        name = fp.name

        if name in existing_names:
            continue

        if now_ts - fp.stat().st_mtime < MIN_FILE_AGE_SEC:
            continue

        df_std = standardize_csv(fp.read_bytes())
        dtype, code, thickness, label = infer_from_filename(name)

        ds_id = str(uuid.uuid4())
        stored = f"{ds_id}.csv"
        df_std.to_csv(os.path.join(FILES_DIR, stored), index=False)

        meta["datasets"][ds_id] = {
            "id": ds_id,
            "type": dtype,
            "material_code": code,
            "label": label,
            "thickness_mm": thickness,
            "original_filename": name,
            "source_path": str(fp),
            "stored_filename": stored,
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hash": df_hash(df_std),
        }

        if dtype == "baseline":
            meta["baseline_id"] = ds_id

        existing_names.add(name)

    # prune
    for ds_id, d in list(meta["datasets"].items()):
        src = d.get("original_filename")
        if not src:
            continue

        if src in current_names:
            d.pop("missing_count", None)
            continue

        d["missing_count"] = int(d.get("missing_count", 0)) + 1
        if d["missing_count"] >= grace_rounds:
            stored = d.get("stored_filename")
            if stored:
                p_stored = os.path.join(FILES_DIR, stored)
                if os.path.exists(p_stored):
                    os.remove(p_stored)
            meta["datasets"].pop(ds_id, None)

    # baseline fix
    if meta.get("baseline_id") not in meta["datasets"] or (
        meta.get("baseline_id")
        and meta["datasets"].get(meta["baseline_id"], {}).get("type") != "baseline"
    ):
        meta["baseline_id"] = pick_latest_baseline_id(meta)

    save_meta(meta)


# Run sync each run
auto_sync_from_folder(IMPORT_DIR, grace_rounds=GRACE_ROUNDS)


# -----------------------------
# UI: inputs only
# -----------------------------

baseline_id = meta.get("baseline_id")
if not baseline_id or baseline_id not in meta["datasets"]:
    st.error("目前沒有 baseline（請聯絡管理者確認 base* 檔案是否存在）")
    st.stop()

base_curve = load_curve_from_stored(meta["datasets"][baseline_id]["stored_filename"])

st.subheader("查詢條件")
mode = st.radio("查詢模式", ["單頻點", "頻帶"], horizontal=True)
unit = st.selectbox("頻率單位", ["Hz", "kHz", "MHz", "GHz"], index=3)


def to_ghz(v: float, unit: str) -> float:
    u = unit.lower()
    if u == "hz":
        return v / 1e9
    if u == "khz":
        return v / 1e6
    if u == "mhz":
        return v / 1e3
    return v


if mode == "單頻點":
    f0 = st.number_input("頻率", value=1.0, min_value=0.0)
    f0_ghz = to_ghz(f0, unit)
else:
    c1, c2 = st.columns(2)
    with c1:
        f1 = st.number_input("起始頻率", value=0.5, min_value=0.0)
    with c2:
        f2 = st.number_input("終止頻率", value=2.0, min_value=0.0)
    f1_ghz = to_ghz(f1, unit)
    f2_ghz = to_ghz(f2, unit)

# 厚度篩選（可留空=不限；輸入數字=精準匹配 round 到 2 decimals）
th_txt = st.text_input("厚度篩選 (mm，可留空=不限)", value="")
th_filter = None
if th_txt.strip():
    try:
        th_filter = float(th_txt)
    except Exception:
        th_filter = None
        st.warning("厚度輸入不是數字，已視為不限")


# -----------------------------
# Build material groups by material_code (apply thickness filter)
# -----------------------------
materials = {}
for ds_id, d in meta["datasets"].items():
    if d.get("type") != "material":
        continue
    code = d.get("material_code")
    if code in (None, "", "None"):
        continue

    if th_filter is not None:
        t = d.get("thickness_mm")
        if t is None:
            continue
        if round(float(t), 2) != round(float(th_filter), 2):
            continue

    materials.setdefault(str(code), []).append((ds_id, d))

if not materials:
    st.warning("沒有符合條件的材料（可能厚度篩選過嚴或資料尚未匯入）")
    st.stop()


# -----------------------------
# Ranking on material_code level with sample averaging
# -----------------------------

def drop_at_point(delta_df: pd.DataFrame, f0: float):
    x = delta_df["GHz"].values
    y = delta_df["Delta_dB"].values
    if f0 < float(x.min()) or f0 > float(x.max()):
        return None
    d0 = float(np.interp(f0, x, y))
    return -d0, float(f0), float(d0)


def worst_drop_in_band(delta_df: pd.DataFrame, f1: float, f2: float):
    lo, hi = sorted([f1, f2])
    x = delta_df["GHz"].values
    y = delta_df["Delta_dB"].values
    m = (x >= lo) & (x <= hi)
    if not np.any(m):
        return None
    yb = y[m]
    xb = x[m]
    i = int(np.argmax(yb))
    worst_delta = float(yb[i])
    worst_f = float(xb[i])
    return -worst_delta, worst_f, worst_delta


results = []

for code, sample_list in materials.items():
    deltas = []
    thk = None

    for ds_id, d in sample_list:
        mat_curve = load_curve_from_stored(d["stored_filename"])
        dd = compute_delta_on_baseline_grid(base_curve, mat_curve)
        deltas.append(dd)
        if thk is None and d.get("thickness_mm") is not None:
            thk = float(d.get("thickness_mm"))

    # average Δ across samples (same baseline grid)
    x = deltas[0]["GHz"].values
    Y = np.vstack([dd["Delta_dB"].values for dd in deltas])
    mean_delta = np.mean(Y, axis=0)
    delta_avg = pd.DataFrame({"GHz": x, "Delta_dB": mean_delta})

    if mode == "單頻點":
        r = drop_at_point(delta_avg, f0_ghz)
    else:
        r = worst_drop_in_band(delta_avg, f1_ghz, f2_ghz)

    if r is None:
        continue

    drop_db, wf, wd = r

    results.append({
        "material_code": str(code),
        "thickness_mm": thk,
        "sample_count": len(sample_list),
        "drop_db": float(drop_db),
        "worst_freq_ghz": float(wf),
    })

if not results:
    st.warning("沒有任何材料在指定頻率/頻段有有效計算結果")
    st.stop()

results_sorted = sorted(results, key=lambda r: -r["drop_db"])

# rank 欄位
out_rows = []
for i, r in enumerate(results_sorted):
    out_rows.append({
        "rank": i + 1,
        "material_code": r["material_code"],
        "thickness_mm": r.get("thickness_mm"),
        "sample_count": r["sample_count"],
        "drop_db": r["drop_db"],
        "worst_freq_ghz": r["worst_freq_ghz"],
    })

df_out = pd.DataFrame(out_rows)

st.subheader("排行結果（降低 dB 越大越好）")

# ✅ rank 固定在最左：用 index 顯示
view_df = df_out.set_index("rank")
st.dataframe(view_df, width="stretch")
