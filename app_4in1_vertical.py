# -*- coding: utf-8 -*-
"""
微帶線 4 求 1（垂直輸入 / 右側結果）— Hammerstad–Jensen 完整式（含厚度）
- 可解未知數：Z0、w、h、εr、t；其他四個作為輸入
- 介面：左側「所有輸入直的一排」，右側顯示結果；**進階（搜尋上下界）已移到結果上方**
- 模型：Hammerstad–Jensen 準靜態閉式（含厚度修正 u1/ur、a(u)/b(εr)、Z_air → Z0）
- 用途：單端外層微帶尺寸初估/反算；未含頻散、損耗、阻焊層、粗糙度等
"""
import math
import streamlit as st

# ------------------ H&J 完整公式 ------------------

def _coth(x: float) -> float:
    if x == 0:
        return 1e12
    ex2 = math.exp(2*x)
    return (ex2 + 1.0) / (ex2 - 1.0) if ex2 != 1.0 else 1e12

def _sech(x: float) -> float:
    return 1.0 / math.cosh(x)

# 回傳 (Z0, eps_eff)

def z0_hj_full(w: float, h: float, er: float, t: float) -> tuple:
    if w <= 0 or h <= 0 or er <= 0 or t < 0:
        return float('nan'), float('nan')
    u = w / h
    th = t / h if h > 0 else 0.0
    sqrt_term = math.sqrt(max(6.517*u, 1e-16))
    delta_u1 = (th / math.pi) * math.log(1.0 + 4*math.e / (max(th,1e-16) * (_coth(sqrt_term)**2)))
    delta_ur = 0.5 * delta_u1 * (1.0 + _sech(math.sqrt(max(er - 1.0, 0.0))))
    u1 = max(u + delta_u1, 1e-12)
    ur = max(u + delta_ur, 1e-12)
    a = 1.0 + (1.0/49.0) * math.log( (ur**4 + (ur/52.0)**2) / (ur**4 + 0.432) ) \
        + (1.0/18.7) * math.log(1.0 + (ur/18.1)**3)
    b = 0.564 * ((er - 0.9) / (er + 3.0))**0.053
    eps_eff = (er + 1.0)/2.0 + (er - 1.0)/2.0 * (1.0 + 10.0/ur)**(-a*b)
    f_u1 = 6.0 + (2.0*math.pi - 6.0) * math.exp(- (30.666/u1)**0.7528)
    Z_air = 60.0 * math.log(f_u1/u1 + math.sqrt(1.0 + (2.0/u1)**2))
    Z0 = Z_air / math.sqrt(eps_eff)
    return Z0, eps_eff

# ------------------ 二分法求解 ------------------

def bisect_solve(func, lo, hi, tol=1e-9, max_iter=100):
    f_lo, f_hi = func(lo), func(hi)
    expand = 0
    while (math.isnan(f_lo) or math.isnan(f_hi) or f_lo * f_hi > 0) and expand < 8:
        width = hi - lo
        lo = max(lo - width, 1e-12)
        hi = hi + width
        f_lo, f_hi = func(lo), func(hi)
        expand += 1
    if math.isnan(f_lo) or math.isnan(f_hi) or f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = func(mid)
        if math.isnan(f_mid):
            return None
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)

# ------------------ UI 佈局 ------------------

st.set_page_config(page_title="微帶線 4 求 1（垂直輸入）", page_icon="📐", layout="wide")
st.title("📐 微帶線 4 求 1 — 垂直輸入 / 右側結果（H&J 完整式）")

left, right = st.columns([1.05, 1.0])

# --- 左側：直排輸入 ---
with left:
    st.subheader("輸入參數")
    unknown = st.radio("要求解的未知數", ["Z0 (Ω)", "w (mm)", "h (mm)", "εr (-)", "t (mm)"], horizontal=True)

    w = st.number_input("線寬 w (mm)", min_value=1e-9, value=0.50, step=0.01, format="%.6f")
    h = st.number_input("板厚 h (mm)", min_value=1e-9, value=0.80, step=0.01, format="%.6f")
    er = st.number_input("相對介電常數 εr", min_value=1.0006, value=4.20, step=0.05, format="%.4f")
    t = st.number_input("導體厚度 t (mm)", min_value=0.0, value=0.035, step=0.005, format="%.5f")
    z0_target = st.number_input("特性阻抗 Z0 (Ω)", min_value=1.0, value=50.0, step=0.1)

    run = st.button("🚀 計算")

# --- 右側：先放 進階，再放 結果 ---
with right:
    st.subheader("設定 & 結果")

    # ⬇⬇ 進階（移到結果上方）
    if unknown in ("w (mm)", "h (mm)", "εr (-)", "t (mm)"):
        with st.expander("⚙️ 進階：搜尋上下界（僅在求 w/h/εr/t 時使用）", expanded=False):
            if unknown == "w (mm)":
                lo = st.number_input("w 下界 (mm)", value=1e-4, format="%.6f")
                hi = st.number_input("w 上界 (mm)", value=200.0, format="%.6f")
            elif unknown == "h (mm)":
                lo = st.number_input("h 下界 (mm)", value=1e-3, format="%.6f")
                hi = st.number_input("h 上界 (mm)", value=50.0, format="%.6f")
            elif unknown == "εr (-)":
                lo = st.number_input("εr 下界", value=1.0006, format="%.6f")
                hi = st.number_input("εr 上界", value=30.0, format="%.6f")
            else:  # t
                lo = st.number_input("t 下界 (mm)", value=1e-4, format="%.6f")
                hi = st.number_input("t 上界 (mm)", value=1.0, format="%.6f")
    else:
        lo = hi = None

    # ⬇⬇ 結果容器
    result_box = st.container()

# ------------------ 計算與輸出 ------------------

if run:
    try:
        if unknown == "Z0 (Ω)":
            Z0, ee = z0_hj_full(w, h, er, t)
            with result_box:
                st.success(f"Z0 ≈ {Z0:.3f} Ω")
                st.caption(f"ε_eff ≈ {ee:.5f}，u = w/h = {w/h:.6f}")
        elif unknown == "w (mm)":
            def f(x):
                z, _ = z0_hj_full(x, h, er, t)
                return z - z0_target
            sol = bisect_solve(f, lo, hi)
            with result_box:
                if sol is None or not math.isfinite(sol):
                    st.error("未能在上下界內找到 w，請調整上下界或輸入參數")
                else:
                    Z0, ee = z0_hj_full(sol, h, er, t)
                    st.success(f"w ≈ {sol:.6f} mm  （Z0={Z0:.3f} Ω）")
                    st.caption(f"ε_eff ≈ {ee:.5f}，u = w/h = {sol/h:.6f}")
        elif unknown == "h (mm)":
            def f(x):
                z, _ = z0_hj_full(w, x, er, t)
                return z - z0_target
            sol = bisect_solve(f, lo, hi)
            with result_box:
                if sol is None or not math.isfinite(sol):
                    st.error("未能在上下界內找到 h，請調整上下界或輸入參數")
                else:
                    Z0, ee = z0_hj_full(w, sol, er, t)
                    st.success(f"h ≈ {sol:.6f} mm  （Z0={Z0:.3f} Ω）")
                    st.caption(f"ε_eff ≈ {ee:.5f}，u = w/h = {w/sol:.6f}")
        elif unknown == "εr (-)":
            def f(x):
                z, _ = z0_hj_full(w, h, x, t)
                return z - z0_target
            sol = bisect_solve(f, lo, hi)
            with result_box:
                if sol is None or not math.isfinite(sol):
                    st.error("未能在上下界內找到 εr，請調整上下界或輸入參數")
                else:
                    Z0, ee = z0_hj_full(w, h, sol, t)
                    st.success(f"εr ≈ {sol:.6f}  （Z0={Z0:.3f} Ω）")
                    st.caption(f"ε_eff ≈ {ee:.5f}，u = w/h = {w/h:.6f}")
        else:  # t
            def f(x):
                z, _ = z0_hj_full(w, h, er, x)
                return z - z0_target
            sol = bisect_solve(f, lo, hi)
            with result_box:
                if sol is None or not math.isfinite(sol):
                    st.error("未能在上下界內找到 t，請調整上下界或輸入參數")
                else:
                    Z0, ee = z0_hj_full(w, h, er, sol)
                    st.success(f"t ≈ {sol:.6f} mm  （Z0={Z0:.3f} Ω）")
                    st.caption(f"ε_eff ≈ {ee:.5f}，u = w/h = {w/h:.6f}")

        with result_box.expander("📎 提示與限制"):
            st.write(
                "- 準靜態近似；高速/嚴格容差請用 2D/3D 場解或板廠阻抗表校核\n"
                "- 若無解：請調整**搜尋上下界**或輸入組合（例如 εr 上限不足時）\n"
                "- 單位：w、h、t 皆為 mm；Z0 為 Ω；εr 無單位\n"
            )
    except Exception as e:
        with result_box:
            st.exception(e)

st.markdown("---")
st.caption("H&J 準靜態閉式（含厚度修正），僅供設計初估與快速迭代使用。")
