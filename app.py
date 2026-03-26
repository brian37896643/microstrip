import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import io
import pandas as pd

# ---------------------------------
# Default settings (paper-like)
# ---------------------------------
Z_SCAN_MM   = 10.0     # probe height z = 10 mm (paper)
Y_SPAN_MM   = 30.0     # cross-line span ±30 mm (paper)
DY_MM       = 1.0      # step 1 mm (paper)
PIN_DBM     = 0.0      # 0 dBm (paper)
USE_EDGE    = True     # edge-current crowding ON
INCLUDE_RET = True     # include ground return (z = -h)
PROBE_DIAM_MM = 10.0   # loop aperture averaging (approx 10 mm loop)
FREQ_LIST_GHZ_DEFAULT = '0.5, 1.0, 1.5, 2.0, 2.5, 3.0'

# ---------------------------------
# Streamlit layout
# ---------------------------------
st.set_page_config(page_title='Microstrip Hy Cross-Line (Freq Panels)', layout='wide')
st.title('Microstrip Near-Field (Hy) — Cross-Line Profile with Frequency Panels')

st.markdown(
    '只輸入 4 個必要參數：**εr、h、w、t**。其他皆為常見/論文一致的預設值（z=10 mm、±30 mm@1 mm、Pin=0 dBm；含接地回流與邊緣電流擁擠）。' \
    '下方可輸入**頻率清單（GHz）**，會以 2×3 或 1×N 面板方式呈現；此準靜態橫向模型與頻率無強耦合，' \
    '因此不同頻率的曲線**形狀相同**（主要差在標題/面板與未來可擴充的頻率效應）。'
)

# ---- Inputs ----
row1 = st.columns(4)
er = row1[0].number_input('Relative permittivity εr', value=4.35, min_value=1.0, step=0.01)
h  = row1[1].number_input('Substrate height h [mm]', value=1.6, min_value=0.01, step=0.01) * 1e-3
w  = row1[2].number_input('Trace width w [mm]', value=3.05, min_value=0.01, step=0.01) * 1e-3
t  = row1[3].number_input('Copper thickness t [µm]', value=35.0, min_value=1.0, step=1.0) * 1e-6

row2 = st.columns(2)
freq_text = row2[0].text_input('Frequency list [GHz] (comma-separated)', value=FREQ_LIST_GHZ_DEFAULT)
probe_diam_mm = row2[1].slider('Probe loop diameter for averaging [mm]', 0.0, 15.0, PROBE_DIAM_MM, 0.5)

# ---- Internal defaults ----
z_scan = Z_SCAN_MM * 1e-3
y_span = Y_SPAN_MM * 1e-3
DY = DY_MM * 1e-3
Pin_dBm = PIN_DBM

# ---------------------------------
# Formulas (Hammerstad–Jensen & Biot–Savart)
# ---------------------------------

def eps_eff_hj(er, w, h):
    u = w/h
    ee = (er + 1)/2 + (er - 1)/2 * 1/np.sqrt(1 + 12/u)
    if u > 1:
        ee = (er + 1)/2 + (er - 1)/2 * (1/np.sqrt(1 + 12/u) + 0.04*(1 - u)**2)
    return ee


def Z0_hj(er, w, h):
    u = w/h
    ee = eps_eff_hj(er, w, h)
    if u <= 1:
        Z0 = (60/np.sqrt(ee)) * np.log(8*h/w + w/(4*h))
    else:
        Z0 = (120*np.pi) / (np.sqrt(ee) * (u + 1.393 + 0.667*np.log(u + 1.444)))
    return Z0, ee


def Hy_kernel(y, z, y0, z0):
    return (z - z0) / ((y - y0)**2 + (z - z0)**2)


def J_uniform(y0, w):
    return np.where(np.abs(y0) <= w/2, 1.0, 0.0)


def J_edge(y0, w, eps=1e-9):
    val = np.zeros_like(y0)
    mask = np.abs(y0) < (w/2 - 1e-9)
    yy = y0[mask]
    denom = np.sqrt(np.maximum(1.0 - (2*yy/w)**2, eps))
    val[mask] = 1.0/denom
    return val


def normalize(y0, J):
    area = np.trapz(J, y0)
    return J/area if area != 0 else J


def moving_avg_1d(x, win_pts):
    if win_pts <= 1:
        return x
    k = np.ones(2*win_pts+1)
    k /= k.sum()
    return np.convolve(x, k, mode='same')

# ---------------------------------
# Compute Hy once (quasi-static cross-line) and reuse for all panels
# ---------------------------------
Z0, eeff = Z0_hj(er, w, h)
Pin_W = 1e-3 * 10**(Pin_dBm/10)
I_rms = np.sqrt(Pin_W / Z0)

y = np.arange(-y_span, y_span + 1e-12, DY)
Ny = max(1201, int(401 * (w / (0.5e-3) + 1)))  # integration density adapts with width
y0 = np.linspace(-w/2, w/2, Ny)

# Edge-current crowding + return current
Jw   = normalize(y0, J_edge(y0, w) if USE_EDGE else J_uniform(y0, w))
Jret = Jw.copy() if INCLUDE_RET else np.zeros_like(Jw)

Hy = np.zeros_like(y)
for i, yy in enumerate(y):
    Hy_fwd = np.trapz(Hy_kernel(yy, z_scan, y0, 0.0) * Jw,   y0)
    Hy_ret = np.trapz(Hy_kernel(yy, z_scan, y0, -h)  * Jret, y0)
    Hy[i]  = (I_rms/(2*np.pi)) * (Hy_fwd - Hy_ret)

# Probe aperture averaging
R = (probe_diam_mm * 1e-3) / 2.0
win_pts = int(np.ceil(R / DY))
Hy = moving_avg_1d(Hy, win_pts)

H_uA = np.maximum(np.abs(Hy) * 1e6, 1e-6)
Hy_dB = 20*np.log10(H_uA)

# Parse frequencies
try:
    freqs = [float(s.strip()) for s in freq_text.split(',') if s.strip()]
except Exception:
    freqs = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

nF = len(freqs)

# Determine subplot grid
if nF <= 3:
    nrow, ncol = 1, nF
elif nF <= 6:
    nrow, ncol = 2, (3 if nF>3 else nF)
else:
    ncol = 3
    nrow = int(np.ceil(nF / ncol))

fig, axes = plt.subplots(nrow, ncol, figsize=(4.2*ncol+0.4, 3.3*nrow+0.6), sharex=True, sharey=True)
axes = np.array(axes).reshape(-1)

for k, f in enumerate(freqs):
    if k >= len(axes):
        break
    ax = axes[k]
    ax.plot(y*1e3, Hy_dB, 'k--', lw=1.8, label='Simulated (quasi-static)')
    ax.set_title(f'f = {f:.3g} GHz')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-Y_SPAN_MM, Y_SPAN_MM)
    if (k % ncol) == 0:
        ax.set_ylabel(r'$H_y$ [dB $\mu$A/m]')
    if k // ncol == (nrow-1):
        ax.set_xlabel('Position y [mm]')

# Hide any unused axes
for j in range(k+1, len(axes)):
    axes[j].axis('off')

if len(freqs) > 0:
    axes[min(1, len(axes)-1)].legend(loc='lower left', fontsize=9, frameon=False)

plt.tight_layout()
st.pyplot(fig, clear_figure=True)

# Metrics and CSV
m1, m2, m3, m4 = st.columns(4)
m1.metric('Z0 [Ω] (est.)', f'{Z0:.2f}')
m2.metric('ε_eff (est.)', f'{eeff:.3f}')
m3.metric('I_rms on line [mA]', f'{I_rms*1e3:.3f}')
m4.metric('Defaults', f'z={Z_SCAN_MM:.1f} mm, span=±{Y_SPAN_MM:.0f} mm, dy={DY_MM:.1f} mm, Pin={PIN_DBM:.1f} dBm')

csv_df = pd.DataFrame({'y_mm': y*1e3, 'Hy_A_per_m': Hy, 'Hy_dB_uA_per_m': Hy_dB})
buf = io.StringIO(); csv_df.to_csv(buf, index=False)
st.download_button('Download CSV (single profile reused across panels)', buf.getvalue(), file_name='Hy_crossline_profile.csv', mime='text/csv')
