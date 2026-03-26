
# -*- coding: utf-8 -*-
"""
Analytical Simulation of Hx(x) Above a Microstrip (Reproducing Fig. 2.1)
------------------------------------------------------------------------
• Model: two edge line-currents + ground-plane image currents (quasi-static).
• Observation height h is measured from the *top of the microstrip*.
• Curves can be peak-normalized; dB scale uses 20*log10(amplitude).

Features:
- Geometry unit toggle (checkbox): single-click to switch between mil and mm
- Adjustable sampling with enforced odd N
- Display floor (default -35 dB) to resemble Fig. 2.1
- Optional probe aperture averaging (loop width along y, thickness along z)
- Metrics: single-sided threshold distance (e.g., -6 dB) & dip-to-dip spacing
- CSV / PNG download
- NEW: Normalize toggle to switch between peak-normalized and absolute curves
"""
# ------------------ imports ------------------
import io
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd

# ------------------ constants ----------------
MM = 1e-3
MIL = 25.4e-6
MIL_TO_MM = 0.0254
MM_TO_MIL = 1.0 / MIL_TO_MM

# ------------------ physics / math ------------------
def hx_profile(x, h, W, h_sub, I=1.0):
    """
    Return Hx(x) at observation height h for a microstrip modeled with:
    - real edge currents at x = ±W/2, z = 0
    - image edge currents at x = ±W/2, z = -2*h_sub
    Hx_i = (I / (2*pi*r_i)) * sin(alpha_i) = (I * h_i) / (2*pi * r_i^2)
    where r_i^2 = (x ± W/2)^2 + h_i^2 and h_i in {h, h+2*h_sub}.
    """
    dxL, dxR = x + W/2.0, x - W/2.0
    h_real, h_img = h, h + 2.0*h_sub
    r1_sq = dxL**2 + h_real**2
    r2_sq = dxR**2 + h_real**2
    r3_sq = dxL**2 + h_img**2
    r4_sq = dxR**2 + h_img**2
    const = I / (2.0*np.pi)
    Hx1 = const * h_real / r1_sq
    Hx2 = const * h_real / r2_sq
    Hx3 = const * h_img  / r3_sq
    Hx4 = const * h_img  / r4_sq
    return Hx1 + Hx2 - Hx3 - Hx4

def hx_aperture_avg(x_center_array, h, W, h_sub, wy, wz, n):
    """
    Aperture averaging over a rectangular loop area:
    - width wy along y (centered at y=0)
    - thickness wz along +z (from loop bottom plane upward)
    - n x n uniform samples
    If wy <= 0 and wz <= 0, falls back to point response.
    """
    if wy <= 0.0 and wz <= 0.0:
        return hx_profile(x_center_array, h, W, h_sub)
    ys = np.array([0.0]) if wy <= 0.0 else np.linspace(-wy/2.0, wy/2.0, int(max(1, n)))
    zs = np.array([0.0]) if wz <= 0.0 else np.linspace(0.0, wz, int(max(1, n)))
    acc = np.zeros_like(x_center_array, dtype=float)
    cnt = 0
    for _y in ys:
        for _z in zs:
            acc += hx_profile(x_center_array, h + _z, W, h_sub)
            cnt += 1
    return acc / max(1, cnt)

def norm_linear(y):
    m = np.max(np.abs(y))
    return np.abs(y) / (m + 1e-18)

def to_db20(y):
    return 20.0 * np.log10(np.maximum(y, 1e-12))

def enforce_odd(n: int, n_min: int = 51) -> int:
    n = int(max(n, n_min))
    return n if (n % 2 == 1) else n + 1

def find_threshold_right(x, y_db, thr_db=-6.0):
    """First intersection (x>=0) with threshold thr_db; return x or None."""
    n = len(x)
    mid = n // 2
    xx, yy = x[mid:], y_db[mid:]
    idxs = np.where(yy <= thr_db)[0]
    if len(idxs) == 0 or idxs[0] == 0:
        return None
    i = idxs[0]
    x1, x2 = xx[i-1], xx[i]
    y1, y2 = yy[i-1], yy[i]
    if y2 == y1:
        return x2
    t = (thr_db - y1) / (y2 - y1)
    return x1 + t*(x2 - x1)

def find_two_dips(x, y_lin):
    """Find nearest dips to the left/right of x=0. Return (xL, xR) or (None, None)."""
    n = len(x); mid = n // 2
    xl, yl = x[:mid], y_lin[:mid]
    xr, yr = x[mid+1:], y_lin[mid+1:]
    def first_min_from_right(xx, yy):
        for i in range(len(xx)-2, 0, -1):
            if yy[i-1] > yy[i] < yy[i+1]:
                return xx[i]
        return None
    def first_min_from_left(xx, yy):
        for i in range(1, len(xx)-1):
            if yy[i-1] > yy[i] < yy[i+1]:
                return xx[i]
        return None
    return first_min_from_right(xl, yl), first_min_from_left(xr, yr)

def make_csv(x_mm, curves_lin, curves_db, heights_mm):
    cols = {"x_mm": x_mm}
    for i, h in enumerate(heights_mm):
        cols[f"H_lin_h{h:.3f}mm"] = curves_lin[i]
        cols[f"H_dB_h{h:.3f}mm"]  = curves_db[i]
    df = pd.DataFrame(cols)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

# ------------------ UI: page config ------------------
st.set_page_config(
    page_title="Analytical Hx(x) Simulation (Fig. 2.1) — Microstrip",
    layout="centered"
)
st.title("Analytical Simulation of $H_x(x)$ Above a Microstrip (Reproducing Fig. 2.1)")
st.caption(
    "Model: two edge currents + image method; h is measured from the trace top. "
    "Curves are peak-normalized. dB uses 20·log10(amplitude)."
)

# ------------------ session defaults ------------------
# Canonical (truth) is always mil
st.session_state.setdefault("W_mil", 16.0)
st.session_state.setdefault("hsub_mil", 8.9)
# UI unit toggle & previous state to detect changes
st.session_state.setdefault("use_mm", False)
st.session_state.setdefault("use_mm_prev", st.session_state["use_mm"])
# Display values (shown in widgets)
st.session_state.setdefault("W_disp", st.session_state["W_mil"])  # same units as current UI
st.session_state.setdefault("hsub_disp", st.session_state["hsub_mil"])  # same units as current UI

# ------------------ UI: sidebar ------------------
with st.sidebar:
    # ---- Geometry header + unit toggle ----
    cols = st.columns([0.7, 0.3])
    with cols[0]:
        st.header("Geometry")
    with cols[1]:
        st.checkbox("Use mm", key="use_mm")  # bound to session_state

    # handle unit toggle (convert display values once)
    unit_changed = (st.session_state["use_mm"] != st.session_state["use_mm_prev"])
    if unit_changed:
        if st.session_state["use_mm"]:
            st.session_state["W_disp"]    = round(st.session_state["W_mil"]   * MIL_TO_MM, 6)
            st.session_state["hsub_disp"] = round(st.session_state["hsub_mil"]* MIL_TO_MM, 6)
        else:
            st.session_state["W_disp"]    = round(st.session_state["W_mil"], 4)
            st.session_state["hsub_disp"] = round(st.session_state["hsub_mil"], 4)
        st.session_state["use_mm_prev"] = st.session_state["use_mm"]

    # show inputs (always write back to canonical mil)
    if st.session_state["use_mm"]:
        W_label = "Microstrip width W [mm]"
        H_label = "Dielectric thickness h_sub [mm]"
        W_step, H_step = 0.01, 0.01
        W_min,  H_min  = 0.001, 0.001
        st.session_state["W_disp"]    = float(st.session_state["W_disp"])
        st.session_state["hsub_disp"] = float(st.session_state["hsub_disp"])
        st.number_input(W_label, min_value=W_min, value=st.session_state["W_disp"], step=W_step, key="W_disp")
        st.number_input(H_label, min_value=H_min, value=st.session_state["hsub_disp"], step=H_step, key="hsub_disp")
        st.session_state["W_mil"]    = float(st.session_state["W_disp"])    * MM_TO_MIL
        st.session_state["hsub_mil"] = float(st.session_state["hsub_disp"]) * MM_TO_MIL
        st.caption(f"Current: W = {st.session_state['W_mil']:.4f} mil | h_sub = {st.session_state['hsub_mil']:.4f} mil")
    else:
        W_label = "Microstrip width W [mil]"
        H_label = "Dielectric thickness h_sub [mil]"
        W_step, H_step = 0.5, 0.1
        W_min,  H_min  = 0.1, 0.1
        st.session_state["W_disp"]    = float(st.session_state["W_disp"])
        st.session_state["hsub_disp"] = float(st.session_state["hsub_disp"])
        st.number_input(W_label, min_value=W_min, value=st.session_state["W_disp"], step=W_step, key="W_disp")
        st.number_input(H_label, min_value=H_min, value=st.session_state["hsub_disp"], step=H_step, key="hsub_disp")
        st.session_state["W_mil"]    = float(st.session_state["W_disp"])
        st.session_state["hsub_mil"] = float(st.session_state["hsub_disp"])
        st.caption(f"Current: W = {st.session_state['W_mil']*MIL_TO_MM:.6f} mm | h_sub = {st.session_state['hsub_mil']*MIL_TO_MM:.6f} mm")

    # ---- Measurement block ----
    st.header("Measurement")
    heights_str = st.text_input("Heights h [mm] (comma-separated)", value="1.0, 0.5")
    x_min = st.number_input("x min [mm]", value=-4.0, step=0.5)
    x_max = st.number_input("x max [mm]", value= 4.0, step=0.5)
    npts_ui = st.number_input("Samples (odd)", min_value=51, value=2001, step=50)
    thr_db  = st.number_input("Threshold for single-sided distance [dB]", value=-6.0, step=0.5)

    # ---- Display options ----
    st.header("Display")
    scale_mode = st.selectbox("Y-axis scale", ["20log amplitude (dB)", "Linear amplitude"], index=0)
    normalize  = st.checkbox("Normalize to peak (0 dB)", value=True)  # NEW
    ymin_db    = st.number_input("Y-axis min (dB display)", value=-35.0, step=1.0)
    clip_floor = st.checkbox("Clip display floor at Y-min", value=True)
    show_thr   = st.checkbox("Mark threshold vertical line", value=True)
    show_dips  = st.checkbox("Mark left/right dips", value=True)
    grid_on    = st.checkbox("Show grid", value=True)

    # ---- Aperture averaging ----
    st.header("Probe aperture averaging (optional)")
    loop_w_mm = st.number_input("Loop width along y [mm] (0 = none)",  value=0.0, step=0.1)
    loop_h_mm = st.number_input("Loop thickness along z [mm] (0 = none)", value=0.0, step=0.1)
    grid_n    = st.slider("Aperture samples per side (odd recommended)", min_value=1, max_value=51, value=11, step=2)

    # ---- Quick preset ----
    if st.button("Apply Fig. 2.1 defaults"):
        st.session_state["W_mil"] = 16.0
        st.session_state["hsub_mil"] = 8.9
        heights_str = "1.0, 0.5"
        x_min, x_max = -4.0, 4.0
        npts_ui = 2001
        thr_db = -6.0
        ymin_db = -35.0
        clip_floor = True
        if st.session_state["use_mm"]:
            st.session_state["W_disp"]    = round(st.session_state["W_mil"]   * MIL_TO_MM, 6)
            st.session_state["hsub_disp"] = round(st.session_state["hsub_mil"]* MIL_TO_MM, 6)
        else:
            st.session_state["W_disp"]    = round(st.session_state["W_mil"], 4)
            st.session_state["hsub_disp"] = round(st.session_state["hsub_mil"], 4)

# Parse heights
try:
    heights_mm = [float(s.strip()) for s in heights_str.split(",") if s.strip()]
    assert len(heights_mm) > 0
except Exception:
    st.error("Please enter at least one height in 'Heights h [mm]'. Example: 1.0, 0.5")
    st.stop()

# Enforce odd samples & make axis
npts = enforce_odd(int(npts_ui), n_min=51)
x_mm = np.linspace(x_min, x_max, npts)
x = x_mm * MM

# Geometry to SI (canonical in mil)
W = st.session_state["W_mil"] * MIL
hsub = st.session_state["hsub_mil"] * MIL

# Aperture in SI
wy = loop_w_mm * MM
wz = loop_h_mm * MM

# Compute curves (with normalization toggle)
curves_lin, curves_db, metrics = [], [], []
for h_mm in heights_mm:
    h_SI = h_mm * MM
    if wy > 0.0 or wz > 0.0:
        H = hx_aperture_avg(x, h_SI, W, hsub, wy, wz, int(grid_n))
    else:
        H = hx_profile(x, h_SI, W, hsub, I=1.0)

    H_abs = np.abs(H)
    H_rel = norm_linear(H)

    # choose which to display
    H_disp_lin = H_rel if normalize else H_abs
    H_disp_db  = to_db20(H_rel) if normalize else to_db20(H_abs)

    curves_lin.append(H_disp_lin)
    curves_db.append(H_disp_db)

    # metrics use relative-to-peak always for robustness
    x_thr = find_threshold_right(x_mm, to_db20(H_rel), thr_db) if scale_mode.startswith("20log") else None
    dipL, dipR = find_two_dips(x_mm, H_rel)
    dipDist = (dipR - dipL) if (dipL is not None and dipR is not None) else None
    metrics.append((h_mm, x_thr, dipL, dipR, dipDist))

# Plot
fig, ax = plt.subplots(figsize=(7.8, 4.8), dpi=150)
for i, h_mm in enumerate(heights_mm):
    if scale_mode.startswith("20log"):
        y = curves_db[i].copy()
        if clip_floor:
            # if normalized: clip to [ymin, 0]; else: only floor to ymin
            y = np.clip(y, ymin_db, 0.0) if normalize else np.maximum(y, ymin_db)
        ax.plot(x_mm, y, lw=2, label=f"h = {h_mm:.3f} mm")
    else:
        ax.plot(x_mm, curves_lin[i], lw=2, label=f"h = {h_mm:.3f} mm")

if scale_mode.startswith("20log"):
    ax.axhline(thr_db, color="k", ls="--", lw=1, alpha=0.7, label=f"{thr_db:g} dB")

for i, (h_mm, x_thr, dipL, dipR, _) in enumerate(metrics):
    color = ax.get_lines()[i].get_color()
    if show_thr and scale_mode.startswith("20log") and x_thr is not None:
        ax.axvline(x_thr, color=color, ls=":", lw=1)
    if show_dips:
        if dipL is not None: ax.axvline(dipL, color=color, ls="--", lw=1, alpha=0.5)
        if dipR is not None: ax.axvline(dipR, color=color, ls="--", lw=1, alpha=0.5)

# labels and limits
if scale_mode.startswith("20log"):
    ax.set_ylabel("Normalized $H_x$ [20log10]" if normalize else "$|H_x|$ [dB re 1 A/m]")
else:
    ax.set_ylabel("Normalized $H_x$ [linear]" if normalize else "$|H_x|$ [linear]")

ax.set_xlabel("x position [mm]")
ax.set_title("Microstrip-Top $H_x(x)$ Profile (Analytical: Edge Currents + Image Method)")
ax.legend()
ax.grid(grid_on, alpha=0.25)
if scale_mode.startswith("20log"):
    ax.set_ylim(ymin_db, 0.0 if normalize else None)
fig.tight_layout()
st.pyplot(fig)

# Metrics table
rows = []
for (h_mm, x_thr, dipL, dipR, dipDist) in metrics:
    rows.append({
        "h [mm]": h_mm,
        "Single-sided threshold x [mm]": None if x_thr is None else float(x_thr),
        "Left dip xL [mm]": None if dipL is None else float(dipL),
        "Right dip xR [mm]": None if dipR is None else float(dipR),
        "Dip spacing [mm]": None if dipDist is None else float(dipDist),
    })
st.subheader("Metrics")
st.dataframe(pd.DataFrame(rows))

# Downloads
csv_text = make_csv(x_mm, curves_lin, curves_db, heights_mm)
st.download_button("Download CSV (x, linear & 20log curves)", csv_text, file_name="hx_profiles.csv", mime="text/csv")

buf = io.BytesIO()
fig.savefig(buf, format="png", dpi=300, bbox_inches="tight")
st.download_button("Download PNG (300 dpi)", data=buf.getvalue(), file_name="hx_profiles.png", mime="image/png")

# Notes
with st.expander("Model notes / assumptions"):
    st.markdown(r"""
**Analytical model**
\[
H_x(x;h) = \sum_{	ext{edges}} rac{I}{2\pi}rac{h}{(x\mp W/2)^2+h^2}
          \;-\; \sum_{	ext{images}} rac{I}{2\pi}rac{h+2h_{	ext{sub}}}{(x\mp W/2)^2+(h+2h_{	ext{sub}})^2}.
\]
- Observation height \(h\) is measured from the microstrip *top surface*.
- With the 20log scale, **−6 dB corresponds to half-amplitude** (not half power).
- Copper thickness, finite ground, loss, and non-ideal edge current distribution are ignored; probe aperture averaging (optional) lifts the dips and better matches practical measurements.
""")
