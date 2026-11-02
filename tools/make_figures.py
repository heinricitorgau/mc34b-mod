#!/usr/bin/env python3
"""
make_figures.py -- regenerate every figure in docs/figures/ from the repo's
own SPICE model library and channel netlist.

    python tools/make_figures.py            # all figures
    python tools/make_figures.py fig4 fig5  # only some
    python tools/make_figures.py stereo     # only (re)write amp_stereo_psu_v1.cir

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
PSU = os.path.join(ROOT, "simulations", "ltspice", "psu_v1.cir")
STEREO = os.path.join(ROOT, "simulations", "ltspice", "amp_stereo_psu_v1.cir")
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

def ngspice(netlist, timeout=180):
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "x.sp")
        with open(f, "w") as fh:
            fh.write(netlist)
        with open(os.path.join(d, ".spiceinit"), "w") as fh:
            fh.write("set ngbehavior=ltpsa\n")
        try:
            r = subprocess.run([NGSPICE, "-b", f], capture_output=True, text=True,
                               cwd=d, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "", d          # caller retries with a stiffer solver
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


def channel_op(**over):
    """DC operating point of the full closed-loop channel -> {node: volts}."""
    nodes = ["b2", "b3", "v1a", "v1k", "lk", "la", "lb", "ka", "pa"]
    o, _ = ngspice(channel(**over) + "VIN in 0 0\n.control\nop\n" +
                   "".join(f"print v({n})\n" for n in nodes) + ".endc\n.end\n")
    return {n: float(re.search(rf"v\({n}\) = (\S+)", o).group(1)) for n in nodes}


def param(name):
    txt = open(CIR, encoding="utf-8").read()
    v = re.search(rf"\b{name}=(\S+)", txt).group(1)
    mult = {"k": 1e3, "meg": 1e6, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
    m = re.match(r"([-\d.e+]+)([a-z]*)", v.lower())
    return float(m.group(1)) * mult.get(m.group(2), 1)


def tran_point(amp, **over):
    """One 1 kHz tone: returns (Pout W, THD %)."""
    settle = 0.6 if over.get("RKO", "1") != "1" else 0.12
    body = channel(**over) + f"VIN in 0 SIN(0 {amp} 1k)\n"
    net = (f"{body}.control\ntran 10u {settle+0.02} {settle} 10u\n"
           f"fourier 1k v(out)\nmeas tran vr rms v(out) from={settle} to={settle+0.02}\n"
           ".endc\n.end\n")
    for opts in ("", ".options method=gear reltol=2e-3\n",
                 ".options method=gear reltol=5e-3 itl4=200\n"):
        o, _ = ngspice(net.replace(".control", opts + ".control", 1), timeout=40)  # normal run ~2 s
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
    op = channel_op()
    B3, RA1 = op["b3"], param("RA1")
    ia = (B3 - op["v1a"]) / RA1 * 1e3
    vak = op["v1a"] - op["v1k"]
    i0 = ia * B3 / (B3 - vak)            # DC load line through (B3, 0) and Q
    ax.plot([0, B3], [i0, 0], color=C2, lw=2,
            label=f"DC load line {RA1/1e3:g}k (B3 = {B3:.0f} V)")
    ax.plot([vak], [ia], "o", ms=8, color=INK, mec=SURF, mew=2, zorder=5)
    ax.annotate(f"Q: {vak:.0f} V, {ia:.2f} mA, Vgk {-op['v1k']:.2f} V", (vak, ia), (vak + 30, ia + 0.55),
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
    op = channel_op()
    ia = (op["b2"] - op["la"]) / param("RLA") * 1e3
    vak, vgk = op["la"] - op["lk"], op["v1a"] - op["lk"]
    ax.plot([vak], [ia], "o", ms=8, color=INK, mec=SURF, mew=2, zorder=5)
    ax.annotate(f"Q (each LTP triode): {vak:.0f} V, {ia:.1f} mA, Vgk {vgk:.1f} V", (vak, ia), (160, 16.5),
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
         "Koren 6L6GC parameters (~10 % hot vs. data sheet). Screen held at idle value here; in the UL circuit it swings with the plate.")


def fig4():
    sets = [("Open loop (v1.3 forward path)", dict(RFB="1e9"), C1, "-"),
            ("NFB 2.7k, no lead cap", dict(RFB="2.7k", CFB="1p", RZOB="1e9", RSTEP="1e9"), C2, "-"),
            ("v1.1: NFB 2.7k || 1nF", dict(RZOB="1e9", RSTEP="1e9"), C4, "--"),
            ("v1.3: + step 3.3k/470p + Zobel 4.7R/100n", dict(), C3, "-")]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for lab, ov, col, ls in sets:
        d = ng_wrdata(channel(**ov) + "VIN in 0 AC 1\n", "ac dec 100 1 5e6", ["vdb(out)"])
        ax.semilogx(d[:, 0], d[:, 1], color=col, ls=ls, label=lab)
    ax.axvspan(20, 20e3, color=GRID, alpha=0.45, lw=0)
    ax.text(640, 53, "audio band 20 Hz-20 kHz", color=INK2, fontsize=9, ha="center", va="top")
    ax.set(title="Frequency response, input -> 4 ohm load", xlabel="Frequency (Hz)",
           ylabel="Voltage gain (dB)", xlim=(1, 5e6), ylim=(-10, 55))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    save(fig, "fig4_freq_response.png",
         "OPT model: 40 H primary, k = 0.9995, 43 % UL, 6 k. HF compensation choice: README section 4.3.")


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
         "Ideal 400 V supply: no transformer sag is modelled yet.")


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
    ax.text(-49.6, 35.6, "design point 33-35 mA", color=INK2, fontsize=9)
    ax.plot(vbs, ik, "o-", color=C1, ms=6, mec=SURF, mew=1)
    ax.axhline(20 / 0.397, color=C4, lw=2, ls="--")
    ax.text(-49.6, 20 / 0.397 + 1.2, "Pa = 20 W at 397 V  (50 mA)", color=INK2, fontsize=9)
    ax.set(title="Idle current per output tube vs fixed bias voltage", xlabel="Grid bias (V)",
           ylabel="Cathode current (mA)", ylim=(0, 70))
    save(fig, "fig7_bias_sweep.png",
         "Model value, ideal 400 V supply. Sweep KG1 in models/tubes_amp.inc to see tube-to-tube spread.")


# ---------------------------------------------------------------- stereo + PSU
def to_ngspice(txt):
    """LTspice-flavoured netlist text -> ngspice batch text."""
    txt = re.sub(r";.*", "", txt)
    txt = re.sub(r"(?im)^\.options.*$", "", txt)
    txt = re.sub(r"(?im)^\.tran\s+0\s+", ".tran 20u ", txt)
    txt = re.sub(r"(?i)\bFROM\s+(\S+)\s+TO\s+(\S+)", r"from=\1 to=\2", txt)
    txt = re.sub(r"(?im)^\.ic .*$", lambda m: m.group(0).replace(":", "."), txt)  # V(xl:b2) -> v(xl.b2)
    return txt


def build_stereo():
    """Generate simulations/ltspice/amp_stereo_psu_v1.cir from the two sources:
    amp_channel_v1.cir (channel circuit, used twice as subckt AMPCH) and
    psu_v1.cir (transformer, bridge, CRC). Never edit the generated file."""
    ch = open(CIR, encoding="utf-8").read().replace("\r\n", "\n").split("* ---- stimulus")[0]
    head, body = ch.split("* ---- power supply", 1)
    body = "* ---- power supply" + body
    params = re.findall(r"(?m)^\.param .*$", head + body)
    lines = [l for l in body.split("\n")
             if l.strip() and not re.match(r"(?i)^(\.param|VBP\b|RBP\b|\* ---- power supply)", l)]
    params = [re.sub(r"^\.param VB=(\S+)", r".param VBN=\1", p) for p in params]
    params = [p for p in params if not p.startswith((".param AMP=", ".param VBPLUS="))]  # B+ comes from psu_v1
    psu = open(PSU, encoding="utf-8").read().replace("\r\n", "\n")
    pparams = [p for p in re.findall(r"(?m)^\.param .*$", psu) if "ILOAD" not in p]
    pcirc = psu.split("* ---- transformer", 1)[1].split("* ---- load", 1)[0]
    out = f"""* =====================================================================
*  amp_stereo_psu_v1.cir  --  GENERATED by tools/make_figures.py, do not edit.
*  Sources: amp_channel_v1.cir (channel, used twice) + psu_v1.cir (B+ supply).
*  Both channels share one transformer / bridge / CRC (B+ node "bp");
*  each channel keeps its own RD1-CD1-RD2-CD2 decoupling (dual-mono style).
*  Fixed bias tracks the mains (VB = VBN * MAINS), as a bias winding on the
*  same transformer would.  .ic starts the supply near steady state.
* =====================================================================
.include ../../models/tubes_amp.inc
.options plotwinsize=0 numdgt=7
* ---- channel parameters (from amp_channel_v1.cir) ----
{chr(10).join(params)}
.param VB={{VBN*MAINS}}
* ---- supply parameters (from psu_v1.cir) ----
{chr(10).join(pparams)}
* ---- shared B+ supply ----
* ---- transformer{pcirc.rstrip()}
* ---- one channel ----
.subckt AMPCH in out bp
{chr(10).join(lines)}
.ends AMPCH
XL inL outL bp AMPCH
XR inR outR bp AMPCH
* ---- start near steady state (released after the operating point) ----
.ic V(raw)=407 V(bp)=400 V(xl:b2)=389 V(xl:b3)=358 V(xr:b2)=389 V(xr:b3)=358
* ---- stimulus & analysis (both channels driven, in phase) ----
.param AMP=0.5
VINL inL 0 SIN(0 {{AMP}} 1k)
VINR inR 0 SIN(0 {{AMP}} 1k)
.tran 0 0.42 0.4 10u
.four 1k 9 V(outL)
.meas TRAN VrmsL RMS V(outL) FROM 0.4 TO 0.42
.meas TRAN Bplus AVG V(bp) FROM 0.4 TO 0.42
.end
"""
    with open(STEREO, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    return out


def stereo(amp=0.0, mains=1.0, tstop=0.42, tstart=0.4, ic=True, **over):
    """ngspice text of the stereo+PSU netlist, analysis lines removed."""
    txt = build_stereo().split("* ---- stimulus")[0]
    txt = re.sub(r"(?im)^\.include\s+\S+", f".include {INC}", txt)
    if not ic:
        txt = re.sub(r"(?im)^\.ic .*$", "", txt)
    txt = to_ngspice(txt)            # strip comments first: they may contain "KGB=..." text
    over = dict(MAINS=mains, **over)
    for k, v in over.items():
        txt, n = re.subn(rf"(?m)(\.param\b[^\n]*\b{k}=)\S+", rf"\g<1>{v}", txt)
        if n == 0:
            sys.exit(f"param {k} not found in stereo netlist")
    txt += f"VINL inL 0 SIN(0 {amp} 1k)\nVINR inR 0 SIN(0 {amp} 1k)\n"
    return txt


def stereo_point(amp, mains=1.0):
    """Both channels driven: (Pout per channel W, THD %, mean B+ V)."""
    net = (stereo(amp, mains) + ".control\ntran 10u 0.42 0.4 10u\nfourier 1k v(outl)\n"
           "meas tran vr rms v(outl) from=0.4 to=0.42\nmeas tran bp avg v(bp) from=0.4 to=0.42\n"
           ".endc\n.end\n")
    for opts in ("", ".options method=gear reltol=2e-3\n"):
        o, _ = ngspice(net.replace(".control", opts + ".control", 1), timeout=900)
        m1, m2, m3 = (re.search(r, o) for r in (r"THD: (\S+)", r"vr\s+=\s+(\S+)", r"bp\s+=\s+(\S+)"))
        if m1 and m2 and m3:
            vr = float(m2.group(1))
            return vr * vr / 4, float(m1.group(1)), float(m3.group(1))
    print(f"    ! stereo point {amp} Vpk did not converge - skipped")
    return None


def fig8():
    """Cold start: supply and decoupling nodes from switch-on (no .ic)."""
    # gear integration: the default trapezoidal method diverges at cold start
    d = ng_wrdata(stereo(0, ic=False) + ".options method=gear\n", "tran 100u 10 0 100u",
                  ["v(bp)", "v(xl.b2)", "v(xl.b3)", "v(xl.ka)"])
    t = d[:, 0]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 5.6), sharex=True,
                                 gridspec_kw=dict(height_ratios=[1.4, 1]))
    a1.plot(t, d[:, 1], color=C1, label="B+ (OPT centre tap)")
    a1.plot(t, d[:, 2], color=C2, label="B2 (LTP supply)")
    a1.plot(t, d[:, 3], color=C3, label="B3 (6N2 supply)")
    a1.set(title="Switch-on transient, stereo idle, nominal mains", ylabel="Voltage (V)", ylim=(0, 460))
    a1.legend(loc="lower right")
    a2.plot(t, d[:, 4] * 1e3, color=C1)
    a2.axhline(34.4, color=INK2, lw=1, ls=":")
    a2.text(9.9, 36, "steady 34 mA", color=INK2, fontsize=9, ha="right")
    a2.set(xlabel="Time (s)", ylabel="Output-tube Ik (mA)", xlim=(0, 10))
    fig.align_ylabels()
    save(fig, "fig8_psu_startup.png",
         "Tubes conduct from t = 0 (no heater warm-up modelled). B3 settles slowly: RD2 x CD2 = 47k x 47 uF = 2.2 s.")


def fig9():
    """Idle ripple: C1, B+, and hum at the speaker for a matched / mismatched pair."""
    win = "tran 10u 0.55 0.5 10u"
    d = ng_wrdata(stereo(0), win, ["v(raw)", "v(bp)", "v(outl)"])
    dm = ng_wrdata(stereo(0, KGB="1533"), win, ["v(outl)"])
    t = (d[:, 0] - d[0, 0]) * 1e3

    def ac(y):                       # remove mean and slow settling drift
        return y - np.polyval(np.polyfit(t, y, 1), t)

    def tone(y, f=120.0):            # rms of the 120 Hz component (window = 6 periods)
        tt = t / 1e3
        a = 2 * np.mean(y * np.cos(2 * np.pi * f * tt)); b = 2 * np.mean(y * np.sin(2 * np.pi * f * tt))
        return np.hypot(a, b) / np.sqrt(2)

    fig, axs = plt.subplots(3, 1, figsize=(7.2, 6.8), sharex=True)
    for ax, y, lab, col, sc, unit in [(axs[0], d[:, 1], "C1 reservoir", C1, 1, "V"),
                                      (axs[1], d[:, 2], "B+ after CRC", C2, 1e3, "mV")]:
        y = ac(y) * sc
        ax.plot(t, y, color=col, lw=1.6)
        ax.set_ylabel(f"{lab}\n({unit}, AC part)", fontsize=9.5)
        ax.text(0.995, 0.95, f"{y.max() - y.min():.3g} {unit} p-p", transform=ax.transAxes,
                ha="right", va="top", fontsize=9.5)
    hm, hx = ac(d[:, 3]), ac(np.interp(d[:, 0], dm[:, 0], dm[:, 1]))  # runs have different time points
    axs[2].plot(t, hm * 1e6, color=C1, lw=1.6, label=f"matched pair: {tone(hm)*1e6:.2f} uV rms at 120 Hz")
    axs[2].plot(t, hx * 1e6, color=C2, lw=1.6, label=f"V4 KG1 +5 % (less current): {tone(hx)*1e6:.1f} uV rms at 120 Hz")
    axs[2].set_ylabel("Speaker, no signal\n(uV, AC part)", fontsize=9.5)
    axs[2].legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=1)
    axs[0].set_title("Ripple and hum at idle, stereo, nominal mains")
    axs[2].set(xlabel="Time (ms)", xlim=(0, 50))
    fig.align_ylabels()
    snr = 20 * np.log10(np.sqrt(27.0 * 4) / tone(hx))
    save(fig, "fig9_psu_ripple.png",
         f"Supply-ripple hum only: {snr:.0f} dB below 27 W even with a 5 % mismatch. Heater / wiring hum is not modelled.")


def fig10():
    """THD and B+ sag vs output power, both channels driven, real supply."""
    amps = [0.05, 0.15, 0.25, 0.35, 0.42, 0.48, 0.53, 0.57, 0.6, 0.63]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        res = [r for r in ex.map(stereo_point, amps) if r]
        ideal = [r for r in ex.map(lambda a: tran_point(a), amps) if r]
    P, T, B = map(np.array, zip(*res))
    Pi, Ti = map(np.array, zip(*ideal))
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 6.4), sharex=True,
                                 gridspec_kw=dict(height_ratios=[1.5, 1]))
    a1.loglog(Pi, Ti, "o-", color=C1, ms=5, mec=SURF, mew=1, label="Ideal 400 V supply, one channel")
    a1.loglog(P, T, "o-", color=C2, ms=5, mec=SURF, mew=1, label="psu_v1, both channels driven")
    a1.axhline(1, color=INK2, lw=1, ls=":")
    a1.text(0.12, 1.12, "1 % THD", color=INK2, fontsize=9)
    a1.set(title="THD and B+ sag vs output power (1 kHz, 4 ohm)", ylabel="THD (%)")
    a1.legend(loc="upper left")
    a2.semilogx(P, B, "o-", color=C2, ms=5, mec=SURF, mew=1)
    a2.set(xlabel="Output power per channel (W)", ylabel="Mean B+ (V)", xlim=(0.1, 40))
    fig.align_ylabels()
    save(fig, "fig10_psu_thd_sag.png",
         "Bias held at -42 V (mains nominal). Sag lowers clipping power; below clipping the curves match.")

# ---------------------------------------------------------------- sensitivity (B+, OPT)
DATA = os.path.join(ROOT, "docs", "data")


def write_csv(name, header, rows):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(f"{v:.6g}" if isinstance(v, float) else str(v) for v in r) + "\n")
    print("  wrote docs/data/" + name)


def p_at_thd(limit=1.0, lo=0.2, hi=1.2, iters=7, **over):
    """Largest 1 kHz output (W) with THD <= limit %, by bisection on input level."""
    best = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        r = tran_point(mid, **over)
        if r and r[1] <= limit:
            lo, best = mid, r[0]
        else:
            hi = mid
    return best


def thd_at_power(p_target=10.0, **over):
    """THD % at a given output power, interpolated from two levels (P ~ amp^2)."""
    r1 = tran_point(0.3, **over)
    if not r1:
        return float("nan")
    amp = 0.3 * np.sqrt(p_target / r1[0])
    r2 = tran_point(amp, **over)
    return r2[1] if r2 else float("nan")


def read_csv(name):
    import csv
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


NO_COMP = dict(RZOB="1e9", RSTEP="1e9")     # removes the v1.3 HF compensation, for comparison


def ac_curve(extra="", **over):
    d = ng_wrdata(channel(**over) + extra + "VIN in 0 AC 1\n", "ac dec 100 0.5 5e6", ["vdb(out)"])
    f, g = d[:, 0], d[:, 1]
    return f, g - np.interp(3.0, np.log10(f), g)


def ac_metrics(extra="", **over):
    """Gain @1 kHz, -3 dB points, peaking (dB, re 1 kHz) and damping factor into 4 ohm."""
    d = ng_wrdata(channel(**over) + extra + "VIN in 0 AC 1\n", "ac dec 100 0.5 5e6", ["vm(out)"])
    f, g = d[:, 0], d[:, 1]
    g1k = np.interp(3.0, np.log10(f), g)
    db = 20 * np.log10(g / g1k)
    lo, hi = f < 1e3, f > 1e3
    flo = f[lo][db[lo] < -3].max() if np.any(db[lo] < -3) else float("nan")
    fhi = f[hi][db[hi] < -3].min() if np.any(db[hi] < -3) else float("nan")
    k = np.argmax(np.where(f > 5e3, db, -1e9))
    z = np.atleast_2d(ng_wrdata(channel(**over) + extra + "VIN in 0 0\nIZ 0 out AC 1\n",
                                "ac lin 1 1k 1k", ["vm(out)"]))[0, 1]
    zout = 1 / (1 / z - 1 / 4.0)
    return dict(gain=g1k, flo=flo, fhi=fhi, pk_lo=max(db[f < 200].max(), 0.0),
                pk_hi=db[k], f_pk=f[k], zout=zout, df=4.0 / zout)


def _bottom_legend(fig, handles, labels, ncol):
    fig.legend(handles, labels, loc="lower center", ncol=ncol, bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.1, 1, 1))


def fig11():
    """B+ sensitivity, single channel, ideal supply; fixed vs tracking bias."""
    bps = [360, 370, 380, 390, 400, 410, 420, 430, 440]
    modes = [("Bias fixed at -42 V", lambda b: -42.0),
             ("Bias scales with B+ (-42 V x B+/400)", lambda b: -42.0 * b / 400)]
    rows = []
    for lab, vbf in modes:
        def one(b):
            ov = dict(VBPLUS=b, VB=f"{vbf(b):.3f}")
            op = channel_op(**ov)
            return (lab, b, vbf(b), op["ka"] * 1e3, op["ka"] * op["pa"],
                    p_at_thd(**ov), thd_at_power(10.0, **ov))
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
            rows += list(ex.map(one, bps))
    write_csv("fig11_bplus_sweep.csv", ["bias_mode", "Bplus_V", "Vg_V", "Ik_mA", "Pa_W", "P_1pct_W", "THD_10W_pct"], rows)
    plot_fig11()


def plot_fig11():
    rows = read_csv("fig11_bplus_sweep.csv")
    fig, axs = plt.subplots(1, 3, figsize=(12.6, 4.4))
    hs = []
    for lab, col in [("Bias fixed at -42 V", C1), ("Bias scales with B+ (-42 V x B+/400)", C2)]:
        r = np.array([[float(x[k]) for k in ("Bplus_V", "Pa_W", "P_1pct_W", "THD_10W_pct")]
                      for x in rows if x["bias_mode"] == lab])
        for ax, k in zip(axs, (1, 2, 3)):
            h, = ax.plot(r[:, 0], r[:, k], "o-", color=col, ms=5, mec=SURF, mew=1)
        hs.append(h)
    axs[0].axhline(20.5, color=C4, lw=2, ls="--")
    axs[0].text(361, 21.2, "6P3S-E rating 20.5 W", color=INK2, fontsize=9)
    axs[0].set(title="Idle plate dissipation", xlabel="B+ (V)", ylabel="Pa per tube (W)", ylim=(0, 28))
    axs[1].set(title="Max power at 1 % THD", xlabel="B+ (V)", ylabel="Output power (W)", ylim=(0, 40))
    axs[2].set(title="THD at 10 W", xlabel="B+ (V)", ylabel="THD (%)", ylim=(0, 0.4))
    _bottom_legend(fig, hs, ["Bias fixed at -42 V", "Bias scales with B+ (-42 V x B+/400)"], 2)
    save(fig, "fig11_bplus_sensitivity.png",
         "Single channel, ideal B+ source, 6 k / 43 % UL OPT, 4 ohm. Data: docs/data/fig11_bplus_sweep.csv")


FIG12_TU = [0.2, 0.3, 0.43, 0.55]


def fig12():
    """OPT primary impedance x UL tap: power, THD and damping factor."""
    jobs = [(r, t) for t in FIG12_TU for r in [4000, 5000, 6000, 6600, 8000]]

    def one(j):
        r, t = j
        ov = dict(RAA=r, TU=t)
        m = ac_metrics(**ov)
        return r, t, p_at_thd(**ov), thd_at_power(10.0, **ov), m["df"], m["gain"], m["pk_hi"]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        rows = list(ex.map(one, jobs))
    write_csv("fig12_opt_raa_ul.csv", ["Raa_ohm", "UL_tap", "P_1pct_W", "THD_10W_pct", "damping_factor", "gain", "hf_peak_dB"], rows)
    plot_fig12()


def plot_fig12():
    res = np.array([[float(v) for v in x.values()] for x in read_csv("fig12_opt_raa_ul.csv")])
    fig, axs = plt.subplots(1, 3, figsize=(12.6, 4.4))
    hs, labs = [], []
    for t, col in zip(FIG12_TU, [C1, C2, C3, C4]):
        r = res[np.isclose(res[:, 1], t)]
        for ax, k in zip(axs, (2, 3, 4)):
            h, = ax.plot(r[:, 0] / 1e3, r[:, k], "o-", color=col, ms=5, mec=SURF, mew=1)
        hs.append(h); labs.append(f"UL tap {t*100:.0f} %" + ("  (v1)" if t == 0.43 else ""))
    for ax in axs:
        ax.axvspan(5, 6.6, color=GRID, alpha=0.5, lw=0)
    axs[0].text(5.8, 2, "likely MC34-B\nrange", ha="center", color=INK2, fontsize=8.5)
    axs[0].set(title="Max power at 1 % THD", xlabel="OPT primary (k ohm, p-p)", ylabel="Output power (W)", ylim=(0, None))
    axs[1].set(title="THD at 10 W", xlabel="OPT primary (k ohm, p-p)", ylabel="THD (%)", ylim=(0, None))
    axs[2].set(title="Damping factor at 1 kHz", xlabel="OPT primary (k ohm, p-p)", ylabel="4 ohm / Zout", ylim=(0, None))
    _bottom_legend(fig, hs, labs, 4)
    save(fig, "fig12_opt_raa_ul.png",
         "v1.3 circuit, B+ 400 V ideal, bias -42 V. Data: docs/data/fig12_opt_raa_ul.csv")


def fig13():
    """OPT primary inductance and coupling: closed-loop response, LF and HF."""
    fig, axs = plt.subplots(1, 3, figsize=(13.2, 4.4))
    rows = []
    lhs = [(2.5, C1), (5, C2), (10, C3), (20, C4)]
    for lh, col in lhs:
        f, db = ac_curve(LH=lh)
        lab = f"Lp = {4*lh:g} H" + ("  (v1)" if lh == 10 else "")
        axs[0].semilogx(f, db, color=col, label=lab)
        axs[1].semilogx(f, db, color=col, label=lab)
        m = ac_metrics(LH=lh)
        rows.append(("Lp_H", 4 * lh, "v1.3", m["flo"], m["fhi"], m["pk_hi"], m["f_pk"]))
    f, db = ac_curve(LH=5, **NO_COMP)
    axs[1].semilogx(f, db, color=C2, ls="--", lw=1.6, label="Lp = 20 H, v1.1 (no HF compensation)")
    m = ac_metrics(LH=5, **NO_COMP)
    rows.append(("Lp_H", 20, "v1.1_no_comp", m["flo"], m["fhi"], m["pk_hi"], m["f_pk"]))
    for kc, col in zip([0.998, 0.999, 0.9995, 0.9998], [C1, C2, C3, C4]):
        f, db = ac_curve(KC=kc)
        axs[2].semilogx(f, db, color=col, label=f"k = {kc}  (leakage ~{40*(1-kc**2)*1e3:.0f} mH)" + ("  (v1)" if kc == 0.9995 else ""))
        m = ac_metrics(KC=kc)
        rows.append(("k", kc, "v1.3", m["flo"], m["fhi"], m["pk_hi"], m["f_pk"]))
    axs[0].set(title="Primary inductance: low end", xlabel="Frequency (Hz)", ylabel="Gain re 1 kHz (dB)", xlim=(0.5, 2e3), ylim=(-15, 4))
    axs[1].set(title="Primary inductance: high end", xlabel="Frequency (Hz)", xlim=(1e3, 5e6), ylim=(-30, 15))
    axs[2].set(title="Coupling / leakage: high end", xlabel="Frequency (Hz)", xlim=(1e3, 5e6), ylim=(-30, 15))
    for ax in axs:
        ax.axhline(-3, color=INK2, lw=1, ls=":")
        ax.legend(loc="lower left", fontsize=8.5)
    axs[0].legend(loc="lower right", fontsize=8.5)
    fig.tight_layout()
    write_csv("fig13_opt_lp_kc.csv", ["param", "value", "fix", "f_minus3dB_low_Hz", "f_minus3dB_high_Hz", "hf_peak_dB", "hf_peak_Hz"], rows)
    save(fig, "fig13_opt_lp_kc.png",
         "v1.3 (step 3.3k+470p, Zobel 4.7R+100n); dashed = v1.1 without them. Winding capacitance not modelled. Data: docs/data/fig13_opt_lp_kc.csv")

ALL = dict(fig1=fig1, fig2=fig2, fig3=fig3, fig4=fig4, fig5=fig5, fig6=fig6, fig7=fig7,
           fig8=fig8, fig9=fig9, fig10=fig10, fig11=fig11, fig12=fig12, fig13=fig13, plot11=plot_fig11, plot12=plot_fig12, stereo=lambda: print("  wrote", os.path.relpath(STEREO, ROOT)) if build_stereo() else None)
if __name__ == "__main__":
    for k in (sys.argv[1:] or ALL):
        print(k)
        ALL[k]()
