# -*- coding: utf-8 -*-
"""
微帶線 50Ω 自動調參器（Streamlit）
- 目標固定為 Z0 = 50 Ω（可在進階設定改成其他目標）
- 使用者輸入三個參數，選擇「哪一個是未知數」讓系統自動求解：
  * 相對介電常數 εr（無單位）
  * 板厚 h（mm）
  * 線寬 w（mm）
  * 導體厚度 t（mm）
- 公式：Hammerstad–Jensen 準靜態閉式模型（含厚度修正，完整式）
  參考常見實作形式（u1/ur 厚度修正、a(u)/b(εr) 的 ε_eff、Z_air → Z0）。

注意：本工具為準靜態近似，未含頻散、損耗、阻焊層、粗糙度等；請將結果視為初估。
"""
import math
import streamlit as st

# ------------------------------- H&J 完整公式 -------------------------------
# 參考 NodeLoop 解釋頁之等價寫法（含厚度修正的 u1/ur，a(u)、b(εr) 及 Z_air 形式）
# 為避免極端值造成數值問題，輔以簡單保護。

def _coth(x: float) -> float:
    if x == 0:
        return 1e12
    ex2 = math.exp(2*x)
    return (ex2 + 1.0) / (ex2 - 1.0) if ex2 != 1.0 else 1e12

def _sech(x: float) -> float:
    return 1.0 / math.cosh(x)

# 回傳 (Z0, eps_eff)

def z0_hj_full(w: float, h: float, er: float, t: float) -> tuple:
    # 單位：w,h,t 皆為 mm；公式僅用比值，因此 mm 與常數不相干
    if w <= 0 or h <= 0 or er <= 0 or t < 0:
        return float('nan'), float('nan')

    u = w / h
    th = t / h if h > 0 else 0.0

    # 厚度修正（兩種不同的 u 用於 Z 與 ε_eff）
    sqrt_term = math.sqrt(max(6.517*u, 1e-16))
    delta_u1 = (th / math.pi) * math.log(1.0 + 4*math.e / (max(th,1e-16) * (_coth(sqrt_term)**2)))
    delta_ur = 0.5 * delta_u1 * (1.0 + _sech(math.sqrt(max(er - 1.0, 0.0))))
    u1 = max(u + delta_u1, 1e-12)
    ur = max(u + delta_ur, 1e-12)

    # ε_eff
    a = 1.0 + (1.0/49.0) * math.log( (ur**4 + (ur/52.0)**2) / (ur**4 + 0.432) ) \
        + (1.0/18.7) * math.log(1.0 + (ur/18.1)**3)
    b = 0.564 * ((er - 0.9) / (er + 3.0))**0.053
    eps_eff = (er + 1.0)/2.0 + (er - 1.0)/2.0 * (1.0 + 10.0/ur)**(-a*b)

    # Z_air 與 Z0
    f_u1 = 6.0 + (2.0*math.pi - 6.0) * math.exp(- (30.666/u1)**0.7528)
    Z_air = 60.0 * math.log(f_u1/u1 + math.sqrt(1.0 + (2.0/u1)**2))
    Z0 = Z_air / math.sqrt(eps_eff)
    return Z0, eps_eff

# ------------------------------- 通用二分法 -------------------------------

def bisect_solve(func, lo, hi, tol=1e-9, max_iter=100):
    f_lo, f_hi = func(lo), func(hi)
    # 自動擴張區間（最多 8 次）
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

# ------------------------------- Streamlit UI -------------------------------

st.set_page_config(page_title="微帶線 50Ω 自動調參器", page_icon="🎯", layout="wide")
st.title("🎯 微帶線 50Ω 自動調參器")
st.caption("輸入三個參數，選擇要自動求解的未知數，讓 Z0 命中 50Ω（可於進階設定修改目標）。")

col1, col2 = st.columns([1.2, 1])

with col1:
    unknown = st.radio("選擇要自動求解的參數（其餘請輸入固定值）",
                       ["w (mm)", "h (mm)", "εr", "t (mm)"], horizontal=True)

with col2:
    with st.expander("⚙️ 進階設定"):
        Z_target = st.number_input("目標阻抗 Z0 (Ω)", min_value=1.0, value=50.0, step=0.1)
        # 搜尋上下界可調
        st.markdown("**搜尋上下界（必要時微調）**")
        if unknown == "w (mm)":
            lo_default, hi_default = 1e-4, 200.0
        elif unknown == "h (mm)":
            lo_default, hi_default = 1e-3, 50.0
        elif unknown == "εr":
            lo_default, hi_default = 1.0006, 30.0
        else:  # t
            lo_default, hi_default = 1e-4, 1.0
        lo = st.number_input("下界", min_value=1e-9, value=float(lo_default), format="%.6f")
        hi = st.number_input("上界", min_value=float(lo)+1e-9, value=float(hi_default), format="%.6f")

# 輸入（其餘三個）
cols = st.columns(4)
with cols[0]:
    w = st.number_input("線寬 w (mm)", min_value=1e-6, value=0.50, step=0.01, format="%.6f")
with cols[1]:
    h = st.number_input("板厚 h (mm)", min_value=1e-6, value=0.80, step=0.01, format="%.6f")
with cols[2]:
    er = st.number_input("相對介電常數 εr", min_value=1.0006, value=4.20, step=0.05, format="%.4f")
with cols[3]:
    t = st.number_input("導體厚度 t (mm)", min_value=0.0, value=0.035, step=0.005, format="%.5f")

run = st.button("🚀 計算")

if run:
    try:
        # 目標函式：f(x) = Z0(x) - Z_target
        if unknown == "w (mm)":
            def f(x):
                Z0, _ = z0_hj_full(x, h, er, t)
                return Z0 - Z_target
            sol = bisect_solve(f, lo, hi)
            label = "w (mm)"
        elif unknown == "h (mm)":
            def f(x):
                Z0, _ = z0_hj_full(w, x, er, t)
                return Z0 - Z_target
            sol = bisect_solve(f, lo, hi)
            label = "h (mm)"
        elif unknown == "εr":
            def f(x):
                Z0, _ = z0_hj_full(w, h, x, t)
                return Z0 - Z_target
            sol = bisect_solve(f, lo, hi)
            label = "εr"
        else:  # t
            def f(x):
                Z0, _ = z0_hj_full(w, h, er, x)
                return Z0 - Z_target
            sol = bisect_solve(f, lo, hi)
            label = "t (mm)"

        if sol is None or not math.isfinite(sol):
            st.error("❌ 未能在設定的上下界內找到解，請調整上下界或輸入參數再試一次。")
        else:
            # 回算並展示細節
            if unknown == "w (mm)":
                Z0, ee = z0_hj_full(sol, h, er, t)
                u_eff = (sol / h)  # 這裡完整式中仍會換算 u1/ur；顯示原始 u 供參考
            elif unknown == "h (mm)":
                Z0, ee = z0_hj_full(w, sol, er, t)
                u_eff = (w / sol)
            elif unknown == "εr":
                Z0, ee = z0_hj_full(w, h, sol, t)
                u_eff = (w / h)
            else:
                Z0, ee = z0_hj_full(w, h, er, sol)
                u_eff = (w / h)

            colA, colB, colC = st.columns(3)
            with colA:
                st.success(f"{label} ≈ {sol:.6f}")
            with colB:
                st.metric("達成阻抗 Z0", f"{Z0:.3f} Ω")
            with colC:
                st.caption(f"u = w/h = {u_eff:.5f}，ε_eff ≈ {ee:.5f}")

            with st.expander("📎 提示與限制"):
                st.markdown(
                    """
                    - 模型：Hammerstad–Jensen 準靜態閉式近似（含厚度修正）；僅供**初估**，請以 2D/3D 場解或板廠阻抗表校核。
                    - 搜尋法：二分法求根；若無解，請調整**上下界**或輸入參數（例如 εr 不夠大時可能無法達到 50Ω）。
                    - 單位：w、h、t 以 **mm** 為單位；εr 無單位；Z0 以 **Ω**。
                    """
                )
    except Exception as e:
        st.exception(e)

st.markdown("---")
st.caption("公式依據：Hammerstad–Jensen 微帶線準靜態模型（常見完整式），結果僅供設計初估。")
