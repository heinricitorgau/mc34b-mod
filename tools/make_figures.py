#!/usr/bin/env python3
"""
make_figures.py -- regenerate every figure in docs/figures/ from the repo's
own SPICE model library and channel netlist.

    python tools/make_figures.py            # all figures
    python tools/make_figures.py fig4 fig5  # only some

Requires: ngspice (>= 38) on PATH, Python 3.9+, numpy, matplotlib.
The channel netlist (simulations/ltspice/amp_channel_v1.cir) is the single
source of truth: this script copies its circuit section, overrides .param
values with regex, and appends ngspice analyses. LTspice users can run the
same netlist directly; the numbers agree.
"""
import os, re, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INC = os.path.join(ROOT, "models", "tubes_amp.inc").replace("\\", "/")
CIR = os.path.join(ROOT, "simulations", "ltspice", "amp_channel_v1.cir")
OUT = os.path.join(ROOT, "docs", "figures")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- style
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"   # fixed order
BLUE_RAMP = ["#0d3a73", "#14509b", "#1d64bd", "#2a78d6", "#4f93e3",
             "#76abea", "#9cc3f0", "#bcd6f5", "#d6e6f9"]
plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "text.color": INK, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 10.5, "axes.titlesize": 12.5,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
    "lines.linewidth": 2, "legend.frameon": False, "figure.dpi": 110,
})


def save(fig, name, note=None):
    if note:
        fig.canvas.draw()
        bb = fig.get_tightbbox(fig.canvas.get_renderer())   # inches, includes legends
        y = (bb.y0 - 0.08) / fig.get_figheight()
        fig.text(0.01, y, note, fontsize=8.5, color=INK2, ha="left", va="top")
    fig.savefig(os.path.join(OUT, name), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  wrote docs/figures/" + name)


# ---------------------------------------------------------------- ngspice
# On Windows the batch-capable binary is ngspice_con.exe
NGSPICE = shutil.which("ngspice_con") or shutil.which("ngspice")
if not NGSPICE:
    sys.exit("ngspice not found on PATH (Windows: add the folder containing ngspice_con.exe)")

def ngspice(netlist):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "x.sp")
        with open(f, "w") as fh:
            fh.write(netlist)
        with open(os.path.join(d, ".spiceinit"), "w") as fh:
            fh.write("set ngbehavior=ltpsa\n")
        r = subprocess.run([NGSPICE, "-b", f], capture_output=True, text=True, cwd=d)
        return r.stdout + r.stderr, d


def ng_wrdata(body, analysis, vectors):
    """Run analysis, return numpy array [x, v1, v2, ...]."""
    with tempfile.TemporaryDirectory() as d:
        dat = os.path.join(d, "o.dat").replace("\\", "/")
        net = f"{body}\n.control\nset wr_singlescale\nset wr_vecnames\n{analysis}\n" \
              f"wrdata {dat} {' '.join(vectors)}\n.endc\n.end\n"
        f = os.path.join(d, "x.sp")
        open(f, "w").write(net)
        open(os.path.join(d, ".spiceinit"), "w").write("set ngbehavior=ltpsa\n")
        r = subprocess.run([NGSPICE, "-b", f], capture_output=True, text=True, cwd=d)
        if not os.path.exists(dat):
            sys.exit("ngspice failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
        return np.loadtxt(dat, skiprows=1)


def channel(**over):
    """Circuit section of amp_channel_v1.cir with .param overrides."""
    txt = open(CIR, encoding="utf-8").read().replace("\r\n", "\n")
    txt = txt.split("* ---- stimulus")[0]
    txt = re.sub(r"(?im)^\.include\s+\S+", f".include {INC}", txt)
    txt = re.sub(r";.*", "", txt)                      # strip LTspice comments
    txt = re.sub(r"(?im)^\.options.*$", "", txt)
    for k, v in over.items():
        txt, n = re.subn(rf"(?m)(\.param\b[^\n]*\b{k}=)\S+", rf"\g<1>{v}", txt)
        if n == 0:
            sys.exit(f"param {k} not found in netlist")
    return txt


def tran_point(amp, **over):
    """One 1 kHz tone: returns (Pout W, THD %)."""
    settle = 0.6 if over.get("RKO", "1") != "1" else 0.12
    body = channel(**over) + f"VIN in 0 SIN(0 {amp} 1k)\n"
    net = (f"{body}.control\ntran 10u {settle+0.02} {settle} 10u\n"
           f"fourier 1k v(out)\nmeas tran vr rms v(out) from={settle} to={settle+0.02}\n"
           ".endc\n.end\n")
    for opts in ("", ".options method=gear reltol=2e-3\n"):
        o, _ = ngspice(net.replace(".control", opts + ".control", 1))
        m1, m2 = re.search(r"THD: (\S+)", o), re.search(r"vr\s+=\s+(\S+)", o)
        if m1 and m2:
            vr = float(m2.group(1))
            return vr * vr / 4, float(m1.group(1))
    print(f"    ! no convergence at {amp} Vpk {over} - point skipped")
    return None


# ---------------------------------------------------------------- figures
def plate_family(sub, pins, vgs, vmax, extra=""):
    curves = []
    for vg in vgs:
        body = f".include {INC}\nX1 {pins}\nVa a 0 0\nVg g 0 {vg}\n{extra}"
        d = ng_wrdata(body, f"dc Va 0 {vmax} 2", ["-i(Va)"])
        curves.append((vg, d[:, 0], d[:, 1] * 1e3))
    return curves


def draw_family(ax, curves, ymax, unit="V"):
    ax.set_title(" ", pad=18)  # room for top-edge labels
    n = len(curves)
    for i, (vg, x, y) in enumerate(curves):
        col = BLUE_RAMP[min(i * (len(BLUE_RAMP) - 1) // max(n - 1, 1), len(BLUE_RAMP) - 1)]
        ax.plot(x, y, color=col, lw=1.6)
        # direct label: at the top edge if the curve leaves the plot, else at the right end
        over = np.nonzero(y >= ymax)[0]
        if len(over):
            ax.text(x[over[0]], ymax * 1.01, f"{vg:g}", ha="center", va="bottom",
                    fontsize=8.5, color=INK2)
        else:
            ax.text(x[-1] + 4, y[-1], f"{vg:g} {unit}", va="center", fontsize=8.5, color=INK2)
    ax.set_ylim(0, ymax)


def fig1():
    vgs = [0, -0.5, -1, -1.5, -2, -2.5, -3]
    c = plate_family("6N2", "a g 0 6N2", vgs, 400)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    draw_family(ax, c, 2.5)
    B3, R = 358.4, 330e3 + 1.6e3
    ax.plot([0, B3], [B3 / R * 1e3, 0], color=C2, lw=2, label="DC load line 330k (B3 = 358 V)")
    ax.plot([148.9], [0.63], "o", ms=8, color=INK, mec=SURF, mew=2, zorder=5)
    ax.annotate("Q: 149 V, 0.63 mA, Vgk -1.0 V", (148.9, 0.63), (175, 1.15),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=1), fontsize=9.5)
    ax.set_title("V1  6N2 plate curves & operating point", pad=18)
    ax.set( xlabel="Plate-cathode voltage (V)",
           ylabel="Plate current (mA)", xlim=(0, 430))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    save(fig, "fig1_6N2_plate.png", "Curves: fitted Koren model (models/tubes_amp.inc), grid steps 0.5 V.")


def fig2():
    vgs = [0, -1, -2, -3, -4, -5, -6, -7, -8]
    c = plate_family("6N1", "a g 0 6N1", vgs, 400)
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    draw_family(ax, c, 20)
    v = np.linspace(60, 400, 200)
    ax.plot(v, 2.2 / v * 1e3, color=C4, lw=2, ls="--", label="Pa = 2.2 W / section (check datasheet)")
    ax.plot([143.2], [5.07], "o", ms=8, color=INK, mec=SURF, mew=2, zorder=5)
    ax.annotate("Q (each LTP triode): 143 V, 5.1 mA, Vgk -2.1 V", (143.2, 5.07), (160, 16.5),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=1), fontsize=9.5)
    ax.set_title("V2  6N1 plate curves & LTP operating point", pad=18)
    ax.set( xlabel="Plate-cathode voltage (V)",
           ylabel="Plate current (mA)", xlim=(0, 430))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    save(fig, "fig2_6N1_plate.png", "Curves: fitted Koren model, grid steps 1 V.")


def fig3():
    vgs = [0, -5, -10, -15, -20, -25, -30, -35, -40, -45]
    c = plate_family("6P3S-E", "a s g 0 6P3S-E", vgs, 600, "Vs s 0 397\n")
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    draw_family(ax, c, 300)
    v = np.linspace(60, 600, 300)
    ax.plot(v, 20 / v * 1e3, color=C4, lw=2, ls="--", label="Pa = 20 W")
    B = 397
    ax.plot([0, B], [B / 1500 * 1e3, 0], color=C2, lw=2, label="Class-B load line Raa/4 = 1.5k")
    ax.plot([B], [34.4], "o", ms=8, color=INK, mec=SURF, mew=2, zorder=5)
    ax.annotate("Idle: 397 V, 34.4 mA, Vg -42 V (13.7 W)", (B, 34.4), (420, 110),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=1), fontsize=9.5)
    ax.set_title("V3/V4  6P3S-E plate curves, Vg2 = 397 V", pad=18)
    ax.set( xlabel="Plate-cathode voltage (V)",
           ylabel="Plate current (mA)", xlim=(0, 640))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    save(fig, "fig3_6P3S-E_plate.png",
         "Koren 6L6GC parameters (~10 % hot vs. data sheet). Screen fixed at idle value; real UL screen swings with plate.")


def fig4():
    sets = [("Open loop (no NFB)", dict(RFB="1e9"), C1),
            ("NFB 2.7k, no lead cap", dict(RFB="2.7k", CFB="1p"), C2),
            ("NFB 2.7k || 1nF  (v1 design)", dict(RFB="2.7k", CFB="1n"), C3)]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for lab, ov, col in sets:
        d = ng_wrdata(channel(**ov) + "VIN in 0 AC 1\n", "ac dec 40 1 1e6", ["vdb(out)"])
        ax.semilogx(d[:, 0], d[:, 1], color=col, label=lab)
    ax.axvspan(20, 20e3, color=GRID, alpha=0.45, lw=0)
    ax.text(640, 53, "audio band 20 Hz-20 kHz", color=INK2, fontsize=9, ha="center", va="top")
    ax.set(title="Frequency response, input -> 4 ohm load", xlabel="Frequency (Hz)",
           ylabel="Voltage gain (dB)", xlim=(1, 1e6), ylim=(5, 55))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    save(fig, "fig4_freq_response.png",
         "OPT model: 40 H primary, k = 0.9995, 43 % UL. Lead cap removes the +4.7 dB peak near 130 kHz.")


def fig5():
    amps = [0.03, 0.06, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.58, 0.61, 0.64, 0.67]
    modes = [("Fixed bias, Vg = -42 V", dict(), C1),
             ("Cathode bias, Rk = 1.1k || 220 uF", dict(VB="0", RKO="1.1k", CKO="220u"), C2)]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for lab, ov, col in modes:
            res = [r for r in ex.map(lambda a: tran_point(a, **ov), amps) if r]
            P, T = zip(*res)
            ax.loglog(P, T, "o-", color=col, ms=5, label=lab, mec=SURF, mew=1)
    ax.axhline(1, color=INK2, lw=1, ls=":")
    ax.text(0.06, 1.12, "1 % THD", color=INK2, fontsize=9)
    ax.set(title="THD vs output power, 1 kHz into 4 ohm", xlabel="Output power (W)",
           ylabel="THD (%)", xlim=(0.05, 40))
    ax.legend(loc="upper left")
    save(fig, "fig5_thd_vs_power.png",
         "Ideal 400 V supply (no PT sag) - real amp will clip earlier, at roughly 20 W.")


def fig6():
    body = channel() + "VIN in 0 SIN(0 0.5 1k)\n"
    d = ng_wrdata(body, "tran 5u 0.124 0.12 5u", ["v(out)", "v(gsa)", "v(gsb)"])
    t = (d[:, 0] - d[0, 0]) * 1e3
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 5.4), sharex=True,
                                 gridspec_kw=dict(height_ratios=[1, 1.1]))
    a1.plot(t, d[:, 1], color=C1)
    a1.set(title="Waveforms at ~19 W (0.5 Vpk input, 1 kHz)", ylabel="Speaker (V)")
    a2.plot(t, d[:, 2], color=C1, label="V3 grid")
    a2.plot(t, d[:, 3], color=C2, label="V4 grid")
    a2.axhline(0, color=INK2, lw=1, ls=":")
    a2.set(xlabel="Time (ms)", ylabel="Output-tube grid (V)", xlim=(0, 4))
    a2.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)
    fig.align_ylabels()
    save(fig, "fig6_waveforms.png", "Grids stay below 0 V: the 6N1 LTP still has drive headroom at this level.")


def fig7():
    vbs = np.arange(-50, -33.5, 1.0)
    ik = []
    for vb in vbs:
        o, _ = ngspice(channel(VB=f"{vb}") + "VIN in 0 0\n.control\nop\nprint v(ka)\n.endc\n.end\n")
        ik.append(float(re.search(r"v\(ka\) = (\S+)", o).group(1)) * 1e3)
    ik = np.array(ik)
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.axhspan(33, 35, color=C3, alpha=0.18, lw=0)
    ax.text(-49.6, 35.6, "target 33-35 mA", color=INK2, fontsize=9)
    ax.plot(vbs, ik, "o-", color=C1, ms=6, mec=SURF, mew=1)
    ax.axhline(20 / 0.397, color=C4, lw=2, ls="--")
    ax.text(-49.6, 20 / 0.397 + 1.2, "Pa = 20 W at 397 V  (50 mA)", color=INK2, fontsize=9)
    ax.set(title="Idle current per output tube vs fixed bias voltage", xlabel="Grid bias (V)",
           ylabel="Cathode current (mA)", ylim=(0, 70))
    save(fig, "fig7_bias_sweep.png",
         "Model value. Real 6P3S-E / 6P3P differ tube-to-tube - set each tube with its own pot and 1 ohm sense resistor.")


ALL = dict(fig1=fig1, fig2=fig2, fig3=fig3, fig4=fig4, fig5=fig5, fig6=fig6, fig7=fig7)
if __name__ == "__main__":
    for k in (sys.argv[1:] or ALL):
        print(k)
        ALL[k]()
