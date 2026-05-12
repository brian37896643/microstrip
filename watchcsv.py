import io
import hashlib

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# -------------------------
# Page
# -------------------------
st.set_page_config(page_title="WatchCSV Plotter", layout="wide")
st.title("CSV 疊圖（Plotly）")
st.caption("✅ 放大後下載 PNG：請按圖右上角 Fullscreen → 相機（Download plot as png）")


# -------------------------
# Helpers
# -------------------------
def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp950"):
        try:
            return raw.decode(enc, errors="strict")
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def read_csv_robust_bytes(raw: bytes) -> pd.DataFrame:
    """讀取含 '#' 註解行的儀器 CSV，並做編碼容錯。"""
    text = _decode_bytes(raw)
    df = pd.read_csv(io.StringIO(text), comment="#", engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def coerce_numeric(df: pd.DataFrame, good_ratio: float = 0.8) -> pd.DataFrame:
    """只針對 object 欄位嘗試轉數字；若大多數可轉才採用 numeric。"""
    out = df.copy()
    for c in out.columns:
        s = out[c]
        if s.dtype == "object":
            s2 = s.astype(str).str.strip()
            numeric = pd.to_numeric(s2, errors="coerce")
            non_empty = s2.replace("", np.nan).notna().sum()
            good = numeric.notna().sum()
            if non_empty > 0 and (good / non_empty) >= good_ratio:
                out[c] = numeric
    return out


def unit_scale(unit: str) -> float:
    return {"Hz": 1.0, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9}[unit]


def pick_default_xy(df: pd.DataFrame):
    """自動挑 Frequency 當 x；y 會避開幾乎全 0 的欄，偏好變化較大的欄。"""
    cols = list(df.columns)

    x_default = None
    for cand in ["Frequency", "Freq", "frequency", "freq", "Hz"]:
        if cand in cols:
            x_default = cand
            break

    if x_default is None:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        x_default = numeric_cols[0] if numeric_cols else cols[0]

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    candidates = [c for c in numeric_cols if c != x_default]

    def score(col):
        s = df[col].dropna()
        if len(s) == 0:
            return -1
        zero_frac = float((s == 0).mean())
        std = float(s.std())
        return std * (1.0 - zero_frac)

    if candidates:
        y_default = max(candidates, key=score)
    else:
        y_default = cols[1] if len(cols) > 1 else cols[0]

    return x_default, y_default


def downsample_df(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if max_points <= 0 or len(df) <= max_points:
        return df
    idx = np.linspace(0, len(df) - 1, max_points).astype(int)
    return df.iloc[idx].copy()


def make_trace_id(filename: str, raw: bytes) -> str:
    """用 (檔名 + 檔案內容hash) 當 id，避免同名覆蓋。"""
    h = hashlib.md5(raw).hexdigest()[:10]
    return f"{filename}__{h}"


# -------------------------
# State
# -------------------------
if "trace_store" not in st.session_state:
    # trace_id -> {file_name: str, raw: bytes}
    st.session_state.trace_store = {}


# -------------------------
# Uploader
# -------------------------
uploaded_files = st.file_uploader(
    "上傳 CSV（可多選；用來『新增』資料）",
    type=["csv", "CSV"],
    accept_multiple_files=True,
)

# 將新上傳的檔案加入 store（不會因為你從 uploader 刪除就消失）
if uploaded_files:
    for uf in uploaded_files:
        raw = uf.getvalue()
        tid = make_trace_id(uf.name, raw)
        if tid not in st.session_state.trace_store:
            st.session_state.trace_store[tid] = {"file_name": uf.name, "raw": raw}

left, right = st.columns([1, 2], gap="large")


# -------------------------
# Left: settings & delete
# -------------------------
with left:
    st.subheader("設定")

    store = st.session_state.trace_store
    trace_ids = list(store.keys())

    if not trace_ids:
        st.info("請先用上方 uploader 上傳一個或多個 CSV。")

    def _fmt_tid(tid: str) -> str:
        return store.get(tid, {}).get("file_name", tid)

    with st.expander("🗑️ 刪除資料（從記憶中移除）", expanded=False):
        del_ids = st.multiselect(
            "選擇要刪除的資料",
            options=trace_ids,
            default=[],
            format_func=_fmt_tid,
            key="del_ids",
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("刪除選取", type="primary", disabled=(len(del_ids) == 0)):
                for tid in del_ids:
                    store.pop(tid, None)
                    st.session_state.pop(f"show_{tid}", None)
                    st.session_state.pop(f"label_{tid}", None)
                st.session_state.del_ids = []
                st.rerun()
        with c2:
            if st.button("清空全部", disabled=(len(trace_ids) == 0)):
                store.clear()
                for k in list(st.session_state.keys()):
                    if str(k).startswith("show_") or str(k).startswith("label_"):
                        st.session_state.pop(k, None)
                st.session_state.del_ids = []
                st.rerun()

    st.divider()

    x_scale_mode = st.radio("X 軸尺度", ["線性", "對數 Log（預設）"], index=1)
    freq_unit = st.selectbox("頻率顯示單位", ["Hz", "kHz", "MHz", "GHz"], index=2)
    max_points = st.number_input("每條線最多點數（downsample，0=不限制）", min_value=0, value=5000, step=500)
    chart_height = st.slider("圖高度（px）", min_value=500, max_value=1200, value=850, step=50)

    st.divider()

    plot_mode = st.radio(
        "疊圖模式",
        ["每個檔案一條線（選一個 Y 欄）", "同一檔案內多個 Y 欄都畫"],
        index=0,
    )
    ignore_all_zero = st.checkbox("忽略『幾乎全 0』的 Y 欄（建議開）", value=True)
    zero_threshold = st.slider("判定『幾乎全 0』門檻（0 佔比）", 0.80, 1.00, 0.98, 0.01)

    show_markers = st.checkbox("顯示 marker（點）", value=False)
    show_preview = st.checkbox("顯示資料預覽", value=False)

    st.divider()

    st.markdown("**相機下載 PNG（放大後最準）**")
    modebar_png_scale = st.number_input(
        "相機下載 PNG 的解析度倍率（scale）",
        min_value=1.0, max_value=6.0, value=3.0, step=0.5
    )
    modebar_png_name = st.text_input("相機下載 PNG 的檔名", value="plot_fullscreen")
    st.caption("提示：要下載「放大後的圖」，請先按右上角 Fullscreen，再按相機。")


# -------------------------
# Right: plot + HTML download only
# -------------------------
with right:
    st.subheader("疊圖結果")

    store = st.session_state.trace_store
    trace_ids = list(store.keys())

    if not trace_ids:
        st.info("請先上傳 CSV。")
        st.stop()

    df0 = coerce_numeric(read_csv_robust_bytes(store[trace_ids[0]]["raw"]))
    x_def, y_def = pick_default_xy(df0)

    all_cols = list(df0.columns)
    numeric_cols0 = df0.select_dtypes(include=[np.number]).columns.tolist()

    x_col = st.selectbox(
        "X 軸欄位（頻率）",
        all_cols,
        index=all_cols.index(x_def) if x_def in all_cols else 0,
    )

    if plot_mode == "每個檔案一條線（選一個 Y 欄）":
        if numeric_cols0:
            y_idx = numeric_cols0.index(y_def) if y_def in numeric_cols0 else 0
            y_col = st.selectbox("Y 軸欄位（dB）", numeric_cols0, index=y_idx)
        else:
            y_col = st.selectbox("Y 軸欄位（dB）", all_cols, index=1 if len(all_cols) > 1 else 0)
    else:
        y_col = None

    st.markdown("**資料顯示（勾選）與圖例名稱（可手動改）**")

    b1, b2, _ = st.columns([1, 1, 6])
    with b1:
        if st.button("全選", key="btn_show_all"):
            for tid in trace_ids:
                st.session_state[f"show_{tid}"] = True
            st.rerun()
    with b2:
        if st.button("全不選", key="btn_hide_all"):
            for tid in trace_ids:
                st.session_state[f"show_{tid}"] = False
            st.rerun()

    show_map = {}
    name_map = {}

    for tid in trace_ids:
        fname = store[tid]["file_name"]
        show_key = f"show_{tid}"
        label_key = f"label_{tid}"

        if show_key not in st.session_state:
            st.session_state[show_key] = True
        if label_key not in st.session_state:
            st.session_state[label_key] = fname

        col_chk, col_name = st.columns([0.10, 0.90], vertical_alignment="center")
        with col_chk:
            show_map[tid] = st.checkbox("顯示", key=show_key, label_visibility="collapsed")
        with col_name:
            name_map[tid] = st.text_input(fname, key=label_key)

    selected_ids = [tid for tid in trace_ids if show_map.get(tid, True)]
    if not selected_ids:
        st.info("目前沒有勾選任何資料可畫圖。請勾選要顯示的資料。")
        st.stop()

    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        height=int(chart_height),
        legend_title_text="Trace",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=10, b=20),
    )

    scale_u = unit_scale(freq_unit)

    for tid in selected_ids:
        fname = store[tid]["file_name"]
        df = coerce_numeric(read_csv_robust_bytes(store[tid]["raw"]))

        if x_col not in df.columns:
            st.warning(f"檔案 {fname} 沒有欄位 {x_col}，已略過。")
            continue

        x_raw = pd.to_numeric(df[x_col], errors="coerce")
        tmp = df.copy()
        tmp[x_col] = x_raw
        tmp = tmp.dropna(subset=[x_col]).sort_values(by=x_col)

        tmp = downsample_df(tmp, int(max_points))
        x = tmp[x_col].to_numpy(dtype=float) / scale_u

        if plot_mode == "每個檔案一條線（選一個 Y 欄）":
            if y_col not in tmp.columns:
                st.warning(f"檔案 {fname} 沒有欄位 {y_col}，已略過。")
                continue

            y = pd.to_numeric(tmp[y_col], errors="coerce").to_numpy(dtype=float)
            mask = np.isfinite(x) & np.isfinite(y)

            if x_scale_mode.startswith("對數"):
                mask = mask & (x > 0)

            x2, y2 = x[mask], y[mask]
            if len(x2) == 0:
                st.warning(f"檔案 {fname} 在目前設定下沒有可畫的點（可能是 Log 模式且 x<=0）。")
                continue

            fig.add_trace(
                go.Scatter(
                    x=x2, y=y2,
                    mode=("lines+markers" if show_markers else "lines"),
                    name=name_map.get(tid, fname),
                )
            )
        else:
            numeric_cols = tmp.select_dtypes(include=[np.number]).columns.tolist()
            y_cols = [c for c in numeric_cols if c != x_col]
            if not y_cols:
                st.warning(f"檔案 {fname} 沒有可用的數值 Y 欄，已略過。")
                continue

            for yc in y_cols:
                s = pd.to_numeric(tmp[yc], errors="coerce")
                non_na = s.dropna()

                if ignore_all_zero and len(non_na) > 0:
                    zero_frac = float((non_na == 0).mean())
                    if zero_frac >= float(zero_threshold):
                        continue

                y = s.to_numpy(dtype=float)
                mask = np.isfinite(x) & np.isfinite(y)
                if x_scale_mode.startswith("對數"):
                    mask = mask & (x > 0)

                x2, y2 = x[mask], y[mask]
                if len(x2) == 0:
                    continue

                fig.add_trace(
                    go.Scatter(
                        x=x2, y=y2,
                        mode=("lines+markers" if show_markers else "lines"),
                        name=f"{name_map.get(tid, fname)} : {yc}",
                    )
                )

        if show_preview:
            with st.expander(f"預覽：{fname}", expanded=False):
                st.write(df.head(30))

    fig.update_xaxes(title=f"{x_col} ({freq_unit})")
    if plot_mode == "每個檔案一條線（選一個 Y 欄）":
        fig.update_yaxes(title=f"{y_col} (dB)")
    else:
        fig.update_yaxes(title="dB（多欄疊圖）")

    if x_scale_mode.startswith("對數"):
        fig.update_xaxes(type="log")

    plotly_cfg = {
        "displayModeBar": True,
        "displaylogo": False,
        "responsive": True,
        "toImageButtonOptions": {
            "format": "png",
            "filename": modebar_png_name,
            "scale": float(modebar_png_scale),
        },
    }

    st.plotly_chart(fig, width="stretch", config=plotly_cfg)
    st.success("要下載「放大後的圖」：請先按右上角 Fullscreen，再按相機（Download plot as png）。")

    # ✅ 只保留 HTML 下載
    st.markdown("## 下載互動圖（HTML）")
    html = fig.to_html(include_plotlyjs="cdn")
    st.download_button(
        "下載互動圖（HTML）",
        data=html.encode("utf-8"),
        file_name="plot.html",
        mime="text/html",
    )
