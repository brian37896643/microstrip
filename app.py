# -*- coding: utf-8 -*-
"""
Microstrip 計算器（Streamlit）
- 可選未知數：阻抗 Z0、線寬 w、板厚 h、相對介電常數 εr
- 其餘三個參數作為輸入，透過 Hammerstad-Jensen（準靜態）公式求解
- 可選擇是否考慮導體厚度 t 的寬度修正（預設 0，單位 mm）

注意：
- 本程式採用常見、工業界廣泛使用的微帶線近似公式（準靜態，未建模頻散、損耗、綠漆影響）。
- 作為尺寸初估與快速設計迭代之用；關鍵鏈路仍建議以 2D/3D 場解或板廠阻抗表驗證。
"""
import math
import numpy as np
import streamlit as st

# ------------------------------- 基本設定 -------------------------------
st.set_page_config(
    page_title="微帶線計算器 (Hammerstad-Jensen)",
    page_icon="📐",
    layout="wide",
)

st.title("📐 微帶線計算器 — Hammerstad‑Jensen 準靜態公式")
st.caption("輸入三個參數，解出另一個未知數。單位：幾何量用 mm，阻抗用 Ω。")

# ------------------------------- 公式函式 -------------------------------
# 厚度修正：將實際寬度 w 換算為等效寬度 w_eff（t=0 則不修正）
def effective_width(w: float, h: float, t: float) -> float:
    if t is None or t <= 0:
        return w
    # 典型 Hammerstad 厚度修正：w' = w + (t/π) * (1 + ln(2h/t))
    # 保護：避免 t>2h 時取 log(負)；此情形使用最小下界
    ratio = max(2*h/t, 1e-9)
    return w + (t/math.pi) * (1 + math.log(ratio))

# 有效介電常數 ε_eff（常見簡化形式，u = w_eff/h）
def epsilon_eff(er: float, w: float, h: float, t: float = 0.0) -> float:
    w_eff = effective_width(w, h, t)
    u = max(w_eff / h, 1e-12)
    base = (er + 1)/2
    # 補償項在 u<1 時加入 0.04*(1-u)^2
    corr = 0.04*(1 - u)**2 if u < 1 else 0.0
    return base + (er - 1)/2 * (1/math.sqrt(1 + 12/u) + corr)

# 特性阻抗 Z0（piecewise 形式）
# 參考常見 Wheeler/Hammerstad-Jensen 準靜態近似
# u = w_eff/h

def z0_from_wh_er(w: float, h: float, er: float, t: float = 0.0) -> float:
    assert w > 0 and h > 0 and er > 0
    w_eff = effective_width(w, h, t)
    u = max(w_eff / h, 1e-12)
    eeff = epsilon_eff(er, w, h, t)
    if u <= 1:
        return (60.0/math.sqrt(eeff)) * math.log(8.0/u + 0.25*u)
    else:
        return (120.0*math.pi) / (math.sqrt(eeff) * (u + 1.393 + 0.667*math.log(u + 1.444)))

# ------------------------------- 數值解 -------------------------------
# 通用二分法求根：在 [lo, hi] 內找 f(x)=0

def bisect_solve(f, lo, hi, tol=1e-9, max_iter=100):
    f_lo = f(lo)
    f_hi = f(hi)
    if math.isnan(f_lo) or math.isnan(f_hi):
        return None
    # 如端點同號，嘗試逐步擴張區間（最多 6 次）
    expand = 0
    while f_lo * f_hi > 0 and expand < 6:
        width = hi - lo
        lo = max(lo - width, 1e-12)
        hi = hi + width
        f_lo, f_hi = f(lo), f(hi)
        expand += 1
    if f_lo * f_hi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = f(mid)
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)

# 解 w：給定 Z0, er, h -> w

def solve_w(z0_target: float, er: float, h: float, t: float, w_min=1e-6, w_max=None):
    if w_max is None:
        w_max = 1e3 * h  # 非常寬的上界
    def f(w):
        return z0_from_wh_er(w, h, er, t) - z0_target
    return bisect_solve(f, w_min, w_max)

# 解 εr：給定 Z0, w, h -> er

def solve_er(z0_target: float, w: float, h: float, t: float, er_min=1.0006, er_max=30.0):
    def f(er):
        return z0_from_wh_er(w, h, er, t) - z0_target
    return bisect_solve(f, er_min, er_max)

# 解 h：給定 Z0, w, er -> h

def solve_h(z0_target: float, w: float, er: float, t: float, h_min=1e-4, h_max=50.0):
    # mm 為單位，預設上界 50 mm 已非常厚
    def f(h):
        return z0_from_wh_er(w, h, er, t) - z0_target
    return bisect_solve(f, h_min, h_max)

# ------------------------------- UI：輸入 -------------------------------
colL, colR = st.columns([1, 1])
with colL:
    solve_for = st.radio(
        "選擇要求解的未知數",
        options=["Z0 (Ω)", "w (mm)", "h (mm)", "εr (-)"],
        horizontal=True,
    )
with colR:
    t = st.number_input("導體厚度 t (mm，可選，0 代表忽略厚度修正)", min_value=0.0, value=0.0, step=0.005, format="%.5f")

st.markdown("---")

# 共用預設值
_default = {
    "Z0": 50.0,
    "w": 0.5,
    "h": 0.8,
    "er": 4.2,
}

if solve_for == "Z0 (Ω)":
    w = st.number_input("線寬 w (mm)", min_value=1e-6, value=_default["w"], step=0.01, format="%.6f")
    h = st.number_input("板厚 h (mm)", min_value=1e-6, value=_default["h"], step=0.01, format="%.6f")
    er = st.number_input("相對介電常數 εr", min_value=1.0006, value=_default["er"], step=0.1, format="%.4f")
elif solve_for == "w (mm)":
    z0 = st.number_input("特性阻抗 Z0 (Ω)", min_value=1.0, value=_default["Z0"], step=0.5)
    h = st.number_input("板厚 h (mm)", min_value=1e-6, value=_default["h"], step=0.01, format="%.6f")
    er = st.number_input("相對介電常數 εr", min_value=1.0006, value=_default["er"], step=0.1, format="%.4f")
elif solve_for == "h (mm)":
    z0 = st.number_input("特性阻抗 Z0 (Ω)", min_value=1.0, value=_default["Z0"], step=0.5)
    w = st.number_input("線寬 w (mm)", min_value=1e-6, value=_default["w"], step=0.01, format="%.6f")
    er = st.number_input("相對介電常數 εr", min_value=1.0006, value=_default["er"], step=0.1, format="%.4f")
else:  # εr
    z0 = st.number_input("特性阻抗 Z0 (Ω)", min_value=1.0, value=_default["Z0"], step=0.5)
    w = st.number_input("線寬 w (mm)", min_value=1e-6, value=_default["w"], step=0.01, format="%.6f")
    h = st.number_input("板厚 h (mm)", min_value=1e-6, value=_default["h"], step=0.01, format="%.6f")

solve_btn = st.button("🚀 開始計算")

# ------------------------------- UI：輸出 -------------------------------
if solve_btn:
    try:
        if solve_for == "Z0 (Ω)":
            z0 = z0_from_wh_er(w, h, er, t)
            eeff = epsilon_eff(er, w, h, t)
            st.success(f"Z0 ≈ {z0:.3f} Ω")
            st.caption(f"u = w_eff/h = {effective_width(w,h,t)/h:.5f}，ε_eff ≈ {eeff:.5f}")
        elif solve_for == "w (mm)":
            w_sol = solve_w(z0, er, h, t)
            if w_sol is None or not math.isfinite(w_sol):
                st.error("無法在合理範圍內收斂求得線寬，請調整輸入或上、下界。")
            else:
                eeff = epsilon_eff(er, w_sol, h, t)
                st.success(f"w ≈ {w_sol:.6f} mm")
                st.caption(f"u = w_eff/h = {effective_width(w_sol,h,t)/h:.5f}，ε_eff ≈ {eeff:.5f}")
        elif solve_for == "h (mm)":
            h_sol = solve_h(z0, w, er, t)
            if h_sol is None or not math.isfinite(h_sol):
                st.error("無法在合理範圍內收斂求得板厚，請調整輸入或上、下界。")
            else:
                eeff = epsilon_eff(er, w, h_sol, t)
                st.success(f"h ≈ {h_sol:.6f} mm")
                st.caption(f"u = w_eff/h = {effective_width(w,h_sol,t)/h_sol:.5f}，ε_eff ≈ {eeff:.5f}")
        else:  # εr
            er_sol = solve_er(z0, w, h, t)
            if er_sol is None or not math.isfinite(er_sol):
                st.error("無法在合理範圍內收斂求得 εr，請調整輸入或上、下界。")
            else:
                eeff = epsilon_eff(er_sol, w, h, t)
                st.success(f"εr ≈ {er_sol:.6f}")
                st.caption(f"u = w_eff/h = {effective_width(w,h,t)/h:.5f}，ε_eff ≈ {eeff:.5f}")

        with st.expander("📎 提示與限制"):
            st.markdown(
                """
                - 本計算為**準靜態**模型，未含頻散、損耗、表面粗糙度、綠漆/阻焊層影響；高頻或嚴格容限請用 2D 場解或板廠阻抗表校核。
                - 厚度修正採常見近似：$w_\text{eff} = w + \frac{t}{\pi}\big(1 + \ln\frac{2h}{t}\big)$（t=0 則不修正）。
                - 典型適用範圍：$10^{-3} \lesssim w/h \lesssim 10^{3}$，$1 \leq \varepsilon_r \leq 30$；超出時結果僅供參考。
                """
            )

    except Exception as e:
        st.exception(e)

with st.expander("📚 公式說明（簡要）"):
    st.markdown(
        r"""
        **特性阻抗**（以等效寬度 $w_\text{eff}$ 和 $u=w_\text{eff}/h$ 表示）：
        $$
        Z_0 = \begin{cases}
        \dfrac{60}{\sqrt{\varepsilon_\text{eff}}}\ln\!\left(\dfrac{8}{u}+0.25u\right), & u\le 1 \\
        \dfrac{120\pi}{\sqrt{\varepsilon_\text{eff}}\,\big(u+1.393+0.667\ln(u+1.444)\big)}, & u>1
        \end{cases}
        $$
        **有效介電常數**（常見近似）：
        $$
        \varepsilon_\text{eff} \approx \frac{\varepsilon_r+1}{2} + \frac{\varepsilon_r-1}{2}\left(\frac{1}{\sqrt{1+12/u}} + \delta\right),\quad \delta = \begin{cases}0.04(1-u)^2,& u<1\\ 0,& u\ge 1\end{cases}
        $$
        **厚度修正**：$\;w_\text{eff} = w + \dfrac{t}{\pi}\big(1+\ln\tfrac{2h}{t}\big)$（當 $t>0$ 時）。
        """
    )

st.markdown("---")
st.caption("© 計算公式：Hammerstad-Jensen 準靜態閉式近似；結果僅供設計初估。")
