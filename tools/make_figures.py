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

# Optional result cache: set MF_CACHE=<dir> to keep every ngspice result keyed by its netlist, so a long
# run can be split into several shorter runs (each one skips what is already done). Off by default.
CACHE = os.environ.get("MF_CACHE")


def _cache_path(text, ext):
    import hashlib
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, hashlib.sha1(text.encode()).hexdigest() + ext)


def ngspice(netlist, timeout=180):
    if CACHE:
        cp = _cache_path(netlist, ".out")
        if os.path.exists(cp):
            return open(cp, encoding="utf-8").read(), None
        out, d = _ngspice(netlist, timeout)
        if out:
            open(cp, "w", encoding="utf-8").write(out)
        return out, d
    return _ngspice(netlist, timeout)


def _ngspice(netlist, timeout=180):
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


def ng_wrdata(body, analysis, vectors, timeout=900, allow_fail=False):
    """Run analysis, return numpy array [x, v1, v2, ...] (None on failure if allow_fail)."""
    if CACHE:
        cp = _cache_path(body + analysis + " ".join(vectors), ".npy")
        if os.path.exists(cp):
            return np.load(cp)
        d = _ng_wrdata(body, analysis, vectors, timeout, allow_fail)
        if d is not None:
            np.save(cp, d)
        return d
    return _ng_wrdata(body, analysis, vectors, timeout, allow_fail)


def _ng_wrdata(body, analysis, vectors, timeout=900, allow_fail=False):
    with tempfile.TemporaryDirectory() as d:
        dat = os.path.join(d, "o.dat").replace("\\", "/")
        net = f"{body}\n.control\nset wr_singlescale\nset wr_vecnames\n{analysis}\n" \
              f"wrdata {dat} {' '.join(vectors)}\n.endc\n.end\n"
        f = os.path.join(d, "x.sp")
        open(f, "w").write(net)
        open(os.path.join(d, ".spiceinit"), "w").write("set ngbehavior=ltpsa\n")
        try:
            r = subprocess.run([NGSPICE, "-b", f], capture_output=True, text=True, cwd=d, timeout=timeout)
            log = r.stdout[-2000:] + r.stderr[-2000:]
        except subprocess.TimeoutExpired:
            log = f"timeout after {timeout} s"
        if not os.path.exists(dat):
            if allow_fail:
                return None
            sys.exit("ngspice failed:\n" + log)
        return np.loadtxt(dat, skiprows=1)


def model_path(p):
    """'../../models/foo.inc' (as written in the netlists) -> absolute path in this repo."""
    return os.path.join(ROOT, "models", os.path.basename(p)).replace("\\", "/")


def channel(**over):
    """Circuit section of amp_channel_v1.cir with .param overrides.
    OPT="sat" swaps in the saturable-core OPT (models/opt_sat.inc), see channel_sat()."""
    if over.pop("OPT", "lin") == "sat":
        return channel_sat(**over)
    txt = open(CIR, encoding="utf-8").read().replace("\r\n", "\n")
    txt = txt.split("* ---- stimulus")[0]
    txt = re.sub(r"(?im)^\.include\s+(\S+)", lambda mm: ".include " + model_path(mm.group(1)), txt)
    txt = re.sub(r";.*", "", txt)                      # strip LTspice comments
    txt = re.sub(r"(?im)^\.options.*$", "", txt)
    for k, v in over.items():
        txt, n = re.subn(rf"(?m)(\.param\b[^\n]*\b{k}=)\S+", rf"\g<1>{v}", txt)
        if n == 0:
            sys.exit(f"param {k} not found in netlist")
    return txt


SAT_KEYS = ("LSAT", "PSH", "LMUL", "IDCX")


def lsat_for(fsat, pref=25.0, raa=6000.0):
    """Half-primary flux linkage at which pref watts (4 ohm) at fsat Hz reaches LSAT."""
    return np.sqrt(2 * pref * raa) / 2 / (2 * np.pi * fsat)


def channel_sat(**over):
    """channel() with the linear coupled-inductor OPT replaced by models/opt_sat.inc.
    Extra overrides: LSAT (V*s), PSH, LMUL, IDCX (A); everything else as channel()."""
    sat = {k: over.pop(k) for k in SAT_KEYS if k in over}
    txt = channel(**over)               # linear netlist, then swap the OPT block
    lines = [l for l in txt.split("\n") if not re.match(r"(?i)^(L[1-5] |R[1-5]W |K[1-5][1-5] )", l)]
    pars = " ".join(f"{k}={{{k}}}" for k in ("LH", "TU", "KC", "RAA")) + " " + \
        " ".join(f"{k}={sat.get(k, d)}" for k, d in (("LSAT", "1e3"), ("PSH", "4"), ("LMUL", "1"), ("IDCX", "0")))
    i = next(n for n, l in enumerate(lines) if l.startswith("CPPW "))
    lines.insert(i, f"XOPT pa ula bp ulb pb out OPT_SAT PARAMS: {pars}")
    lines.insert(1, ".include " + model_path("opt_sat.inc"))
    out = "\n".join(lines)
    assert out.count("XOPT") == 1 and not re.search(r"(?m)^K12 ", out)
    return out


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
    ax.annotate("Idle: 397 V, 34.4 mA, Vg -40.9 V (13.7 W)", (B, 34.4), (405, 133),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=1), fontsize=9.5)
    ax.set_title("V3/V4  6P3S-E plate curves, Vg2 = 397 V", pad=18)
    ax.set( xlabel="Plate-cathode voltage (V)",
           ylabel="Plate current (mA)", xlim=(0, 640))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    save(fig, "fig3_6P3S-E_plate.png",
         "Koren 6L6GC form, KG1/KG2 fitted to the 6P3S datasheet point (250 V / 250 V / -14 V: 72 mA). Screen held at idle value here; in the UL circuit it swings with the plate.")


def fig4():
    sets = [("Open loop (v1.5 forward path)", dict(RFB="1e9"), C1, "-"),
            ("NFB 2.7k, no lead cap", dict(RFB="2.7k", CFB="1p", RZOB="1e9", RSTEP="1e9", RPZ="1e9"), C2, "-"),
            ("v1.1: NFB 2.7k || 1nF", dict(V11), C4, "--"),
            ("v1.4: step 3.3k/470p + Zobel 10R/470n", dict(V14), INK2, ":"),
            ("v1.5: + plate-plate 4.7k/2.2n, Zobel 10R/1u, CFB 100p", dict(), C3, "-")]
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
    modes = [("Fixed bias, Vg = -40.9 V", dict(), C1),
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


def build_stereo(real_bias=True, write=True):
    """Generate simulations/ltspice/amp_stereo_psu_v1.cir from the two sources:
    amp_channel_v1.cir (channel circuit, used twice as subckt AMPCH) and
    psu_v1.cir (transformer, bridge, CRC). Never edit the generated file."""
    ch = open(CIR, encoding="utf-8").read().replace("\r\n", "\n").split("* ---- stimulus")[0]
    head, body = ch.split("* ---- power supply", 1)
    body = "* ---- power supply" + body
    params = re.findall(r"(?m)^\.param .*$", head + body)
    includes = re.findall(r"(?im)^\.include .*$", head)
    lines = [l for l in body.split("\n")
             if l.strip() and not re.match(r"(?i)^(\.param|VBP\b|RBP\b|\* ---- power supply)", l)]
    params = [re.sub(r"^\.param VB=(\S+)", r".param VBN=\1", p) for p in params]
    params = [p for p in params if not p.startswith((".param AMP=", ".param VBPLUS="))]  # B+ comes from psu_v1
    # real bias: each output tube gets its own divider (RBTOP + pot RPOT + RBBOT) from the bias bus
    divider = ("* per-tube bias divider from the bias bus nbus: RBTOP - pot RPOT (wiper = grid bias) - RBBOT\n"
               "RBT{t} nbus t{t} {{RBTOP}}\nRPU{t} t{t} {n} {{max(RPOT*(1-{w}),1)}}\nRPL{t} {n} u{t} {{max(RPOT*{w},1)}}\n"
               "RBB{t} u{t} 0 {{RBBOT}}\nCW{t} {n} 0 {{CWIPER}}")
    if real_bias:
        lines = [divider.format(t="A", n="bias", w="WA") if l.startswith("VBIAS ") else
                 divider.format(t="B", n="biasb", w="WB") if l.startswith("VBIASB ") else l for l in lines]
    psu = open(PSU, encoding="utf-8").read().replace("\r\n", "\n")
    pparams = [p for p in re.findall(r"(?m)^\.param .*$", psu) if "ILOAD" not in p]
    pcirc = psu.split("* ---- transformer", 1)[1].split("* ---- load", 1)[0]
    out = f"""* =====================================================================
*  amp_stereo_psu_v1.cir  --  GENERATED by tools/make_figures.py, do not edit.
*  Sources: amp_channel_v1.cir (channel, used twice) + psu_v1.cir (B+ supply).
*  Both channels share one transformer / bridge / CRC (B+ node "bp");
*  each channel keeps its own RD1-CD1-RD2-CD2 decoupling (dual-mono style).
*  Fixed bias comes from the bias winding in psu_v1.cir (bus "nbus") through
*  one divider + pot per output tube (wiper settings WA / WB per tube).
*  .ic starts the supplies near steady state.
* =====================================================================
{chr(10).join(includes)}
.options plotwinsize=0 numdgt=7
* ---- channel parameters (from amp_channel_v1.cir) ----
{chr(10).join(params)}
* ---- per-tube bias dividers (range about -34 ... -49 V on a -58.5 V bus) ----
.param RBTOP=15k RPOT=25k RBBOT=56k CWIPER=10u
.param WA=0.462 WB=0.462   ; pot wiper position 0..1 (1 = most negative); 0.462 = 34.4 mA per tube (nominal tubes)
.param VB={{VBN*MAINS}}   ; used only by the ideal-bias variant (build_stereo(real_bias=False))
* ---- supply parameters (from psu_v1.cir) ----
{chr(10).join(pparams)}
* ---- shared B+ supply ----
* ---- transformer{pcirc.rstrip()}
* ---- one channel ----
.subckt AMPCH in out bp nbus
{chr(10).join(lines)}
.ends AMPCH
XL inL outL bp nbus AMPCH
XR inR outR bp nbus AMPCH
* ---- start near steady state (released after the operating point) ----
.ic V(raw)=407 V(bp)=400 V(xl:b2)=389 V(xl:b3)=358 V(xr:b2)=389 V(xr:b3)=358 V(nb1)=-61 V(nbus)=-58.3 V(xl:bias)=-41 V(xl:biasb)=-41 V(xr:bias)=-41 V(xr:biasb)=-41
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
    if write:
        with open(STEREO, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
    return out


def stereo(amp=0.0, mains=1.0, tstop=0.42, tstart=0.4, ic=True, real_bias=True, **over):
    """ngspice text of the stereo+PSU netlist, analysis lines removed."""
    txt = build_stereo(real_bias, write=real_bias).split("* ---- stimulus")[0]
    txt = re.sub(r"(?im)^\.include\s+(\S+)", lambda mm: ".include " + model_path(mm.group(1)), txt)
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
    dm = ng_wrdata(stereo(0, KGB="1722"), win, ["v(outl)"])
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
    snr = 20 * np.log10(np.sqrt(25.0 * 4) / tone(hx))
    save(fig, "fig9_psu_ripple.png",
         f"Supply-ripple hum only: {snr:.0f} dB below 25 W even with a 5 % mismatch. Heater / wiring hum is not modelled.")


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
         "Bias from the bias-supply model (pots WA = WB = 0.462). Sag lowers clipping power; below clipping the curves match.")

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


NO_COMP = dict(RZOB="1e9", RSTEP="1e9", CFB="1n", RPZ="1e9")   # = v1.1 (no HF compensation), for comparison


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
    modes = [("Bias fixed at -40.9 V", lambda b: -40.9),
             ("Bias scales with B+ (-40.9 V x B+/400)", lambda b: -40.9 * b / 400)]
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
    for lab, col in [("Bias fixed at -40.9 V", C1), ("Bias scales with B+ (-40.9 V x B+/400)", C2)]:
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
    _bottom_legend(fig, hs, ["Bias fixed at -40.9 V", "Bias scales with B+ (-40.9 V x B+/400)"], 2)
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
         "v1.5 circuit, B+ 400 V ideal, bias -40.9 V. Data: docs/data/fig12_opt_raa_ul.csv")


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
        rows.append(("Lp_H", 4 * lh, "v1.5", m["flo"], m["fhi"], m["pk_hi"], m["f_pk"]))
    f, db = ac_curve(LH=5, **NO_COMP)
    axs[1].semilogx(f, db, color=C2, ls="--", lw=1.6, label="Lp = 20 H, v1.1 (no HF compensation)")
    m = ac_metrics(LH=5, **NO_COMP)
    rows.append(("Lp_H", 20, "v1.1_no_comp", m["flo"], m["fhi"], m["pk_hi"], m["f_pk"]))
    for kc, col in zip([0.998, 0.999, 0.9995, 0.9998], [C1, C2, C3, C4]):
        f, db = ac_curve(KC=kc)
        axs[2].semilogx(f, db, color=col, label=f"k = {kc}  (leakage ~{40*(1-kc**2)*1e3:.0f} mH)" + ("  (v1)" if kc == 0.9995 else ""))
        m = ac_metrics(KC=kc)
        rows.append(("k", kc, "v1.5", m["flo"], m["fhi"], m["pk_hi"], m["f_pk"]))
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
         "v1.5 (step 3.3k+470p, Zobel 10R+1u, CFB 100p, plate-plate 4.7k+2.2n); dashed = v1.1. Winding capacitance off (see fig 20). Data: docs/data/fig13_opt_lp_kc.csv")
# ---------------------------------------------------------------- square wave & loop gain
V11 = dict(RZOB="1e9", RSTEP="1e9", CFB="1n", RPZ="1e9")   # v1.1: RFB 2.7k || 1n, no step network, no Zobel
V13 = dict(RZOB="4.7", CZOB="100n", CFB="1n", RPZ="1e9")    # v1.3: step network + Zobel 4.7R/100n + 1n lead cap
V14 = dict(CZOB="470n", CFB="1p", RPZ="1e9")                # v1.4: Zobel 10R/470n, no lead cap, no plate-plate RC
V15C = dict(CSTEP="1n", CFB="220p")                         # v1.5-C: v1.5 tuned for pure capacitive loads


def square(freq, amp=0.16, extra="", cycles=None, **over):
    """Output for a +/-amp square wave (20 ns edges) -> (t_s, v_out) of the last 2 periods."""
    T = 1.0 / freq
    n = cycles or max(4, int(np.ceil(0.25 / T)) if freq < 200 else 12)
    tstop = n * T
    step = min(T / 4000, 50e-9) if freq >= 1e3 else T / 2000   # T/4000 fails in ngspice at 40 Hz
    # two unipolar pulses in series: starts at 0 V, so the DC operating point is the idle one
    tr = 20e-9 if freq >= 1e3 else 1e-6        # 1 us edges below 1 kHz (20 ns stalls ngspice at 40 Hz)
    w = T / 2 - tr
    src = (f"VIN in in2 PULSE(0 {amp} 0 {tr:.3g} {tr:.3g} {w:.6g} {T:.6g})\n"
           f"VIN2 in2 0 PULSE(0 {-amp} {T/2:.6g} {tr:.3g} {tr:.3g} {w:.6g} {T:.6g})\n")
    for opts in (".options method=gear\n", "", ".options method=gear reltol=5e-3 itl4=200\n"):
        d = ng_wrdata(channel(**over) + extra + src + opts,
                      f"tran {step:.3g} {tstop:.6g} {tstop-2*T:.6g} {step:.3g}", ["v(out)"],
                      timeout=180, allow_fail=True)
        if d is not None and len(d) > 10:
            return d[:, 0] - d[0, 0], d[:, 1]
    print(f"    ! square {freq:g} Hz {over} {extra.strip()} did not finish (likely oscillating)")
    return None


def square_metrics(t, v, freq):
    """Overshoot %, 10-90 % rise time (us), tilt % (from 1/4 to 1/2 of the half-period)."""
    T = 1.0 / freq
    half = (t % T) < T / 2                     # first half of each period = high level
    hi_plateau = v[half & ((t % T) > 0.35 * T)].mean()
    lo_plateau = v[~half & ((t % T) > 0.85 * T)].mean()
    span = hi_plateau - lo_plateau
    over = (v[half].max() - hi_plateau) / span * 100
    seg = (t >= 0) & (t < T / 2)
    tt, vv = t[seg], v[seg]
    lv, hv = lo_plateau + 0.1 * span, lo_plateau + 0.9 * span
    try:
        rise = (tt[np.nonzero(vv >= hv)[0][0]] - tt[np.nonzero(vv >= lv)[0][0]]) * 1e6
    except IndexError:
        rise = float("nan")
    early = v[half & ((t % T) > 0.25 * T) & ((t % T) < 0.3 * T)].mean()   # tilt: meaningful for f <= 1 kHz
    late = v[half & ((t % T) > 0.45 * T) & ((t % T) < 0.5 * T)].mean()
    tilt = (early - late) / span * 100
    return over, rise, tilt


def loop_gain(**over):
    """Middlebrook voltage injection between the speaker node and RFB/CFB:
    T(f) = -V(out)/V(fbi). Returns f, |T| dB, phase deg."""
    txt = channel(**over)
    for a, b in (("RFB out v1k", "RFB fbi v1k"), ("CFB out v1k", "CFB fbi v1k")):
        assert a in txt
        txt = txt.replace(a, b)
    txt += "VINJ fbi out AC 1\nVIN in 0 0\n"
    d = ng_wrdata(txt, "ac dec 100 1 1e7", ["vr(out)", "vi(out)", "vr(fbi)", "vi(fbi)"])
    f = d[:, 0]
    T = -(d[:, 1] + 1j * d[:, 2]) / (d[:, 3] + 1j * d[:, 4])
    return f, 20 * np.log10(np.abs(T)), np.degrees(np.angle(T))


def margins(f, mag, ph):
    """Unity-gain crossover (highest), phase margin, gain margin."""
    hf = f > 1e3
    idx = np.nonzero(hf[:-1] & (mag[:-1] > 0) & (mag[1:] <= 0))[0]
    if len(idx) == 0:
        return float("nan"), float("nan"), float("nan")
    i = idx[-1]
    fc = f[i]
    pm = 180 - abs(ph[i])
    # gain margin: |T| where phase crosses +/-180 above fc
    unwrapped = np.degrees(np.unwrap(np.radians(ph)))
    crosses = np.nonzero(hf[:-1] & (np.abs(unwrapped[:-1]) < 180) & (np.abs(unwrapped[1:]) >= 180))[0]
    gm = -mag[crosses[0]] if len(crosses) else float("nan")
    return fc, pm, gm


LOADS = [("4 ohm", "", {}), ("8 ohm", "", {"RL": "8"}),
         ("4 ohm || 0.47 uF", "CLD out 0 0.47u\n", {}), ("4 ohm || 2 uF", "CLD out 0 2u\n", {}),
         ("0.47 uF only", "CLD out 0 0.47u\n", {"RL": "1e6"}), ("2 uF only", "CLD out 0 2u\n", {"RL": "1e6"}),
         ("no load", "", {"RL": "1e6"})]


def loop_margins(extra="", **over):
    txt = channel(**over)
    for a, b in (("RFB out v1k", "RFB fbi v1k"), ("CFB out v1k", "CFB fbi v1k")):
        txt = txt.replace(a, b)
    d = ng_wrdata(txt + extra + "VINJ fbi out AC 1\nVIN in 0 0\n", "ac dec 100 1 1e7",
                  ["vr(out)", "vi(out)", "vr(fbi)", "vi(fbi)"])
    T = -(d[:, 1] + 1j * d[:, 2]) / (d[:, 3] + 1j * d[:, 4])
    return margins(d[:, 0], 20 * np.log10(np.abs(T)), np.degrees(np.angle(T)))


def fig14():
    """Square-wave response: load / stability table, v1.1 / v1.3 / v1.4 / v1.5, plus 1 kHz and 40 Hz."""
    rows = []
    for ver, vov in [("v1.1", V11), ("v1.3", V13), ("v1.4", V14), ("v1.5", {})]:
        for name, ex, ov in LOADS:
            fc, pm, gm = loop_margins(ex, **ov, **vov)
            sq = square(1e4, extra=ex, **ov, **vov)
            o, r, _ = square_metrics(*sq, 1e4) if sq else (float("nan"), float("nan"), 0)
            rows.append((ver, name, fc, pm, gm, o, r))
    write_csv("fig14_square_loads.csv", ["version", "load", "crossover_Hz", "phase_margin_deg", "gain_margin_dB",
                                         "overshoot_10kHz_pct", "rise_10_90_us"], rows)
    fig, axs = plt.subplots(2, 2, figsize=(12.0, 8.6))
    a = axs[0, 0]
    for lab, ov, col, lw in [("v1.1, no load (oscillates)", dict(RL="1e6", **V11), C2, 1.0),
                             ("v1.5, no load", dict(RL="1e6"), C3, 1.8), ("v1.5, 4 ohm", {}, C1, 1.8)]:
        sq = square(1e4, **ov)
        if sq:
            a.plot(sq[0] * 1e6, sq[1], color=col, lw=lw, label=lab)
    a.set(title="10 kHz square: v1.1 vs v1.5", xlabel="Time (us)", ylabel="Speaker (V)", xlim=(0, 200), ylim=(-12, 12))
    a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=8.5)
    a = axs[0, 1]
    for (name, ex, ov), col in zip([LOADS[0], LOADS[2], LOADS[3], LOADS[5]], [C1, C2, C3, C4]):
        t, v = square(1e4, extra=ex, **ov)
        o = [r[5] for r in rows if r[0] == "v1.5" and r[1] == name][0]
        a.plot(t * 1e6, v, color=col, lw=1.6, label=f"{name}: overshoot {o:.0f} %")
    a.set(title="10 kHz square, v1.5, reactive loads", xlabel="Time (us)", ylabel="Speaker (V)", xlim=(0, 200))
    a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=8.5)
    for a, fq in [(axs[1, 0], 1e3), (axs[1, 1], 40.0)]:
        sq = square(fq)
        if not sq:
            a.set(title=f"{fq:g} Hz square: simulation did not finish")
            continue
        t, v = sq
        _, r, ti = square_metrics(t, v, fq)
        lab = f"rise {r:.1f} us" if fq >= 1e3 else f"tilt {ti:.0f} % over 1/8 period"
        a.plot(t * 1e3, v, color=C1, lw=1.6)
        a.set(title=f"{fq/1e3:g} kHz square, v1.5, 4 ohm ({lab})" if fq >= 1e3 else f"{fq:g} Hz square, v1.5, 4 ohm ({lab})", xlabel="Time (ms)", ylabel="Speaker (V)", xlim=(0, 2e3 / fq))
        rows2 = (f"{fq:g}Hz", r, ti)
        print(f"    {fq:g} Hz: rise {r:.1f} us, tilt {ti:.1f} %")
    fig.tight_layout()
    save(fig, "fig14_square_wave.png",
         "Input +/-0.16 V square (about 4 V peak into 4 ohm). OPT 40 H / k 0.9995 / 43 % UL / 6 k. Data: docs/data/fig14_square_loads.csv")


def fig15():
    """Loop gain and phase margin: v1.1 / v1.3 / v1.4 / v1.5, nominal OPT and worst grid cases."""
    rows = []
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.6, 6.6), sharex=True, gridspec_kw=dict(height_ratios=[1.2, 1]))
    for lab, ov, col in [("v1.1", V11, C2), ("v1.3", V13, C4), ("v1.4", V14, C3), ("v1.5", {}, C1)]:
        f, mag, ph = loop_gain(**ov)
        fc, pm, gm = margins(f, mag, ph)
        rows.append(("nominal", lab, fc, pm, gm))
        a1.semilogx(f, mag, color=col, label=f"{lab}: crossover {fc/1e3:.0f} kHz, PM {pm:.0f} deg, GM {gm:.1f} dB")
        a2.semilogx(f, ph, color=col)
    a1.axhline(0, color=INK2, lw=1, ls=":")
    for y in (-180, 180):
        a2.axhline(y, color=INK2, lw=1, ls=":")
    a1.set(title="Loop gain T(f) = -V(out)/V(inj), nominal OPT", ylabel="|T| (dB)", ylim=(-40, 30))
    a1.legend(loc="lower left", fontsize=9)
    a2.set(xlabel="Frequency (Hz)", ylabel="Phase of T (deg)", xlim=(1, 1e7), ylim=(-200, 200))
    import itertools
    grid = list(itertools.product([4000, 5000, 6000, 6600, 8000], [0.2, 0.3, 0.43, 0.55], [5, 10], [0.999, 0.9995, 0.9998]))
    for lab, ov in [("v1.1", V11), ("v1.3", V13), ("v1.4", V14), ("v1.5", {})]:
        def one(g):
            raa, tu, lh, kc = g
            return margins(*loop_gain(RAA=raa, TU=tu, LH=lh, KC=kc, **ov)) + (g,)
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
            res = list(ex.map(one, grid))
        pms = np.array([r[1] for r in res]); gms = np.array([r[2] for r in res])
        i, j = int(np.nanargmin(pms)), int(np.nanargmin(gms))
        rows.append(("grid_worst_PM", lab, res[i][0], res[i][1], res[i][2]))
        rows.append(("grid_worst_GM", lab, res[j][0], res[j][1], res[j][2]))
        print(f"    {lab}: worst PM {res[i][1]:.0f} deg at {res[i][3]}, worst GM {res[j][2]:.1f} dB at {res[j][3]}")
    fig.align_ylabels()
    write_csv("fig15_loop_gain.csv", ["case", "version", "crossover_Hz", "phase_margin_deg", "gain_margin_dB"], rows)
    save(fig, "fig15_loop_gain.png",
         "Middlebrook voltage injection at the feedback take-off (source Z ~0.3 ohm << RFB). Grid results: docs/data/fig15_loop_gain.csv")

# ---------------------------------------------------------------- ELT 10 load (estimated model)
SPKR = dict(SPK=1, RL="1e6")                 # estimated ELT 10 instead of the 4 ohm resistor


def speaker_impedance():
    d = ng_wrdata(f".include {model_path('elt10_est.inc')}\nX1 a 0 ELT10_EST\nIS 0 a AC 1\n",
                  "ac dec 100 10 40k", ["vm(a)", "vp(a)"])
    return d[:, 0], d[:, 1], np.degrees(d[:, 2])


def tone_point(freq, amp, **over):
    """One tone at any frequency: (P W into the 4 ohm nominal, THD %)."""
    T = 1.0 / freq
    settle = max(0.15, 12 * T)
    win = max(2, int(np.ceil(0.02 / T))) * T
    step = min(10e-6, T / 400)
    net = (channel(**over) + f"VIN in 0 SIN(0 {amp} {freq:g})\n.control\n"
           f"tran {step:.3g} {settle+win:.6g} {settle:.6g} {step:.3g}\nfourier {freq:g} v(out)\n"
           f"meas tran vr rms v(out) from={settle:.6g} to={settle+win:.6g}\n.endc\n.end\n")
    for opts in ("", ".options method=gear reltol=2e-3\n"):
        o, _ = ngspice(net.replace(".control", opts + ".control", 1), timeout=120)
        m1, m2 = re.search(r"THD: (\S+)", o), re.search(r"vr\s+=\s+(\S+)", o)
        if m1 and m2:
            return float(m2.group(1)) ** 2 / 4.0, float(m1.group(1))
    return None


def p_at_thd_f(freq, limit=1.0, lo=0.2, hi=1.4, iters=7, **over):
    best = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        r = tone_point(freq, mid, **over)
        if r and r[1] <= limit:
            lo, best = mid, r[0]
        else:
            hi = mid
    return best


def fig16():
    """Estimated ELT 10 impedance."""
    f, z, ph = speaker_impedance()
    write_csv("fig16_elt10_impedance.csv", ["freq_Hz", "Z_ohm", "phase_deg"], list(zip(f, z, ph)))
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.6, 6.0), sharex=True, gridspec_kw=dict(height_ratios=[1.4, 1]))
    a1.semilogx(f, z, color=C1)
    a1.axhline(4, color=INK2, lw=1, ls=":")
    a1.text(11, 4.3, "4 ohm nominal", color=INK2, fontsize=9)
    i = np.argmin(np.where(f > 100, z, 1e9))
    a1.annotate(f"min {z[i]:.2f} ohm @ {f[i]:.0f} Hz", (f[i], z[i]), (f[i] * 1.6, 1.2),
                arrowprops=dict(arrowstyle="-", color=INK2, lw=1), fontsize=9)
    for fr, lab in [(25, "box/driver"), (70, "peaks"), (40, "fb")]:
        pass
    a1.set(title="ELAC ELT 10: ESTIMATED impedance model", ylabel="|Z| (ohm)", ylim=(0, 16))
    a2.semilogx(f, ph, color=C2)
    a2.axhline(0, color=INK2, lw=1, ls=":")
    a2.set(xlabel="Frequency (Hz)", ylabel="Phase (deg)", xlim=(10, 40e3), ylim=(-60, 60))
    fig.align_ylabels()
    save(fig, "fig16_elt10_impedance.png",
         "Not measured: built from published specs + typical driver values (models/elt10_est.inc). Data: docs/data/fig16_elt10_impedance.csv")


def fig17():
    """v1.5 driving the estimated ELT 10 vs a 4 ohm resistor."""
    fig, axs = plt.subplots(1, 3, figsize=(13.6, 4.4))
    # (a) frequency response re 1 kHz into 4 ohm
    rows = []
    ref = None
    for lab, ov, col in [("4 ohm resistor", {}, C1), ("ELT 10 model", SPKR, C2)]:
        d = ng_wrdata(channel(**ov) + "VIN in 0 AC 1\n", "ac dec 100 10 40k", ["vdb(out)"])
        if ref is None:
            ref = np.interp(3.0, np.log10(d[:, 0]), d[:, 1])
        axs[0].semilogx(d[:, 0], d[:, 1] - ref, color=col, label=lab)
        if ov:
            dev = d[:, 1] - ref
            band = (d[:, 0] >= 20) & (d[:, 0] <= 20e3)
            rows.append(("response_dev_20Hz_20kHz_dB", dev[band].min(), dev[band].max()))
    axs[0].set(title="Frequency response (re 1 kHz, 4 ohm)", xlabel="Frequency (Hz)", ylabel="dB", xlim=(10, 40e3), ylim=(-4, 3))
    axs[0].legend(loc="lower center", fontsize=9)
    # (b) 10 kHz square into the ELT 10, v1.1 / v1.3 / v1.4 / v1.5
    for lab, ov, col in [("v1.1", dict(**SPKR, **V11), C2), ("v1.3", dict(**SPKR, **V13), C4), ("v1.4", dict(**SPKR, **V14), C3), ("v1.5", SPKR, C1)]:
        sq = square(1e4, **ov)
        o, r, _ = square_metrics(*sq, 1e4) if sq else (float("nan"), 0, 0)
        fc, pm, gm = loop_margins(**ov)
        if not sq:
            rows.append((f"{lab}_ELT10_square_PM_GM", o, pm, gm))
            continue
        t, v = sq
        rows.append((f"{lab}_ELT10_square_PM_GM", o, pm, gm))
        axs[1].plot(t * 1e6, v, color=col, lw=1.6 if lab == "v1.5" else 1.0,
                    label=f"{lab}: overshoot {o:.0f} %" + (f", PM {pm:.0f} deg, GM {gm:.1f} dB" if np.isfinite(pm) else " (oscillates)"))
    axs[1].set(title="10 kHz square into ELT 10 model", xlabel="Time (us)", ylabel="Speaker (V)", xlim=(0, 200), ylim=(-12, 12))
    axs[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), fontsize=8.5)
    # (c) max power vs frequency
    freqs = [30, 40, 60, 100, 300, 1000, 3000, 10000]
    jobs = [(f, ov) for ov in ({}, SPKR) for f in freqs]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        ps = list(ex.map(lambda j: p_at_thd_f(j[0], **j[1]), jobs))
    p4, pe = ps[:len(freqs)], ps[len(freqs):]
    v4, ve = np.sqrt(np.array(p4) * 4), np.sqrt(np.array(pe) * 4)
    axs[2].semilogx(freqs, v4, "o-", color=C1, ms=5, mec=SURF, mew=1, label="4 ohm resistor")
    axs[2].semilogx(freqs, ve, "o-", color=C2, ms=5, mec=SURF, mew=1, label="ELT 10 model")
    axs[2].set(title="Max output voltage at 1 % THD", xlabel="Frequency (Hz)", ylabel="Speaker voltage (V rms)", ylim=(0, None))
    axs[2].legend(loc="lower center", fontsize=9)
    fig.tight_layout()
    write_csv("fig17_elt10_power.csv", ["freq_Hz", "Vrms_1pct_4ohm", "Vrms_1pct_ELT10", "P_4ohm_W"],
              list(zip(freqs, v4, ve, p4)))
    # worst-case margins over the OPT grid with the speaker load
    import itertools
    grid = list(itertools.product([4000, 5000, 6000, 6600, 8000], [0.2, 0.3, 0.43, 0.55], [5, 10], [0.999, 0.9995, 0.9998]))
    for lab, ov in [("v1.1", dict(**SPKR, **V11)), ("v1.3", dict(**SPKR, **V13)), ("v1.4", dict(**SPKR, **V14)), ("v1.5", SPKR)]:
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
            res = list(ex.map(lambda g: loop_margins(RAA=g[0], TU=g[1], LH=g[2], KC=g[3], **ov), grid))
        rows.append((f"{lab}_ELT10_grid_worst_PM_GM", float(np.nanmin([r[1] for r in res])), float(np.nanmin([r[2] for r in res]))))
    write_csv("fig17_elt10_summary.csv", ["item", "a", "b", "c"], [r + ("",) * (4 - len(r)) for r in rows])
    for r in rows:
        print("   ", r)
    save(fig, "fig17_elt10_load.png",
         "v1.5 unless noted. Output voltage at 1 % THD. OPT core saturation at low frequency is not modelled.")

# ---------------------------------------------------------------- tube-to-tube spread
NOM = {"X1": dict(KG1=1414, MU=97.5),      # 6N2  (V1)
       "X3": dict(KG1=1202, MU=35),        # 6N1  (LTP, driven half)
       "X4": dict(KG1=1202, MU=35),        # 6N1  (LTP, grounded-grid half)
       "X5": dict(KG1=1640, MU=8.7),       # 6P3S-E (V3)
       "X6": dict(KG1=1640, MU=8.7)}       # 6P3S-E (V4)
IK_TARGET = 34.4e-3                         # per-tube idle current the bias is trimmed to


def chan_t(tubes=None, extra="", **over):
    """channel() text with per-instance tube parameters, e.g. {"X5": {"KG1": 1600}}."""
    txt = channel(**over)
    for name, pars in (tubes or {}).items():
        def add(mm):
            line = mm.group(0)
            for k, v in pars.items():
                line = re.sub(rf"\s{k}=\S+", "", line) + f" {k}={v:.6g}"
            return line
        txt, n = re.subn(rf"(?m)^{name} .*$", add, txt)
        assert n == 1, name
    return txt + extra


def op_t(txt):
    nodes = ["ka", "kb", "pa", "pb", "v1a", "v1k", "lk", "la", "lb", "b2"]
    o, _ = ngspice(txt + "VIN in 0 0\n.control\nop\n" + "".join(f"print v({n})\n" for n in nodes) + ".endc\n.end\n")
    return {n: float(re.search(rf"v\({n}\) = (\S+)", o).group(1)) for n in nodes}


def trim_bias(tubes, **over):
    """Per-tube bias trim: VB sets V3 to IK_TARGET, then DVB sets V4. Returns (VB, DVB)."""
    def solve(key, var, fixed, x0, x1, lo, hi):
        f = lambda x: op_t(chan_t(tubes, **{**over, **fixed, var: f"{x:.5f}"}))[key] - IK_TARGET
        f0, f1 = f(x0), f(x1)
        for _ in range(8):
            if abs(f1) < 2e-5 or f1 == f0:
                break
            step = -f1 * (x1 - x0) / (f1 - f0)
            step = max(-3.0, min(3.0, step))              # current rises as bias goes less negative
            x0, f0 = x1, f1
            x1 = max(lo, min(hi, x1 + step))
            f1 = f(x1)
        return x1
    vb = solve("ka", "VB", {"DVB": "0"}, -42.0, -41.0, -70.0, -20.0)
    dvb = solve("kb", "DVB", {"VB": f"{vb:.5f}"}, 0.0, 0.5, -20.0, 20.0)
    return vb, dvb


def tone_t(txt, amp, freq=1e3):
    """(P W into 4 ohm, THD %, H2 % of fundamental) for one 1 kHz tone."""
    net = (txt + f"VIN in 0 SIN(0 {amp} {freq:g})\n.control\ntran 10u 0.14 0.12 10u\nfourier {freq:g} v(out)\n"
           "meas tran vr rms v(out) from=0.12 to=0.14\n.endc\n.end\n")
    for opts in ("", ".options method=gear reltol=2e-3\n"):
        o, _ = ngspice(net.replace(".control", opts + ".control", 1), timeout=60)
        m1, m2 = re.search(r"THD: (\S+)", o), re.search(r"vr\s+=\s+(\S+)", o)
        h2 = re.search(r"(?m)^\s*2\s+\S+\s+(\S+)\s+\S+\s+(\S+)", o)
        if m1 and m2:
            return float(m2.group(1)) ** 2 / 4, float(m1.group(1)), (float(h2.group(2)) * 100 if h2 else float("nan"))
    return float("nan"), float("nan"), float("nan")


def thd10_t(txt):
    """THD % and H2 % at 10 W (two-step level search)."""
    p, _, _ = tone_t(txt, 0.3)
    if not np.isfinite(p) or p <= 0:
        return float("nan"), float("nan")
    _, thd, h2 = tone_t(txt, 0.3 * np.sqrt(10.0 / p))
    return thd, h2


def pmax_t(txt, limit=1.0, lo=0.2, hi=1.2, iters=7):
    best = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        p, thd, _ = tone_t(txt, mid)
        if np.isfinite(thd) and thd <= limit:
            lo, best = mid, p
        else:
            hi = mid
    return best


def gain_t(txt):
    d = np.atleast_2d(ng_wrdata(txt + "VIN in 0 AC 1\n", "ac lin 1 1k 1k", ["vm(out)", "vm(ga)", "vm(gb)"]))
    return d[0, 1], d[0, 2] / d[0, 3]


def spread_case(tubes, trim):
    """All metrics for one set of tube parameters, with or without per-tube bias trim."""
    over = {}
    if trim:
        vb, dvb = trim_bias(tubes)
        over = dict(VB=f"{vb:.5f}", DVB=f"{dvb:.5f}")
    txt = chan_t(tubes, **over)
    op = op_t(txt)
    thd, h2 = thd10_t(txt)
    g, bal = gain_t(txt)
    return dict(ia=op["ka"] * 1e3, ib=op["kb"] * 1e3, pa=op["ka"] * op["pa"], pb=op["kb"] * op["pb"],
                dI=(op["ka"] - op["kb"]) * 1e3, thd=thd, h2=h2, gain=g, bal=bal,
                v1gk=-op["v1k"], ltp_vak=op["la"] - op["lk"], ltp_ia=(op["b2"] - op["la"]) / param("RLA") * 1e3,
                vb=float(over.get("VB", -40.9)), dvb=float(over.get("DVB", 0)))


def fig18():
    """Tube-to-tube spread: output pair mismatch, common shift, driver tubes, Monte Carlo."""
    pool = ThreadPoolExecutor(max_workers=os.cpu_count() or 2)
    rows = []
    # (a,b) output pair mismatch: V4 KG1 scaled, V3 nominal
    mis = [0.8, 0.87, 0.93, 1.0, 1.07, 1.15, 1.25]
    def mis_case(k_tr):
        k, tr = k_tr
        return k, tr, spread_case({"X6": dict(KG1=1640 * k)}, tr)
    res_mis = list(pool.map(mis_case, [(k, tr) for tr in (False, True) for k in mis]))
    for k, tr, r in res_mis:
        rows.append(("pair_mismatch", f"V4 KG1 x{k}", "trimmed" if tr else "fixed -40.9 V", r))
    # (c,d) both output tubes shifted together
    sh = [0.8, 0.9, 1.0, 1.1, 1.25]
    def sh_case(k_tr):
        k, tr = k_tr
        tubes = {"X5": dict(KG1=1640 * k), "X6": dict(KG1=1640 * k)}
        r = spread_case(tubes, tr)
        over = dict(VB=f"{r['vb']:.5f}", DVB=f"{r['dvb']:.5f}") if tr else {}
        r["pmax"] = pmax_t(chan_t(tubes, **over))
        return k, tr, r
    res_sh = list(pool.map(sh_case, [(k, tr) for tr in (False, True) for k in sh]))
    for k, tr, r in res_sh:
        rows.append(("common_shift", f"V3+V4 KG1 x{k}", "trimmed" if tr else "fixed -40.9 V", r))
    # (e) driver tubes (output bias trimmed, as on a finished amp)
    drv = [0.75, 0.87, 1.0, 1.15, 1.33]
    drv_sets = [("6N2 (V1) KG1", lambda k: {"X1": dict(KG1=1414 * k)}),
                ("6N1 both halves KG1", lambda k: {"X3": dict(KG1=1202 * k), "X4": dict(KG1=1202 * k)}),
                ("6N1 halves mismatched", lambda k: {"X4": dict(KG1=1202 * k)})]
    def drv_case(job):
        name, fn, k = job
        return name, k, spread_case(fn(k), True)
    res_drv = list(pool.map(drv_case, [(n, fn, k) for n, fn in drv_sets for k in drv]))
    for name, k, r in res_drv:
        rows.append(("driver", f"{name} x{k}", "trimmed", r))
    # (f) Monte Carlo: every tube independent, KG1 lognormal sigma 10 %, MU normal sigma 3 %
    rng = np.random.default_rng(20261103)
    samples = []
    for i in range(200):
        tubes = {n: dict(KG1=v["KG1"] * float(np.exp(rng.normal(0, 0.10))), MU=v["MU"] * float(1 + rng.normal(0, 0.03)))
                 for n, v in NOM.items()}
        samples.append(tubes)
    def mc_case(job):
        i, tubes = job
        return i, spread_case(tubes, False), spread_case(tubes, True)
    res_mc = list(pool.map(mc_case, list(enumerate(samples))))
    for i, ru, rt in res_mc:
        rows.append(("monte_carlo", f"sample {i}", "fixed -40.9 V", ru))
        rows.append(("monte_carlo", f"sample {i}", "trimmed", rt))
    pool.shutdown()
    keys = ["ia", "ib", "pa", "pb", "dI", "thd", "h2", "gain", "bal", "v1gk", "ltp_vak", "ltp_ia", "vb", "dvb"]
    write_csv("fig18_tube_spread.csv", ["study", "case", "bias"] + keys,
              [(a, b, c) + tuple(float(r[k]) for k in keys) for a, b, c, r in rows])
    plot_fig18()


def plot_fig18():
    import csv
    with open(os.path.join(DATA, "fig18_tube_spread.csv"), encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    f = lambda r, k: float(r[k])
    fig, axs = plt.subplots(2, 3, figsize=(14.4, 8.4))
    # (a) DC imbalance vs current ratio
    for bias, col, lab in [("fixed -40.9 V", C2, "bias fixed at -40.9 V"), ("trimmed", C1, "each tube trimmed to 34.4 mA")]:
        r = [x for x in rows if x["study"] == "pair_mismatch" and x["bias"] == bias]
        k = [float(x["case"].split("x")[-1]) for x in r]
        axs[0, 0].plot(k, [abs(f(x, "dI")) for x in r], "o-", color=col, ms=5, mec=SURF, mew=1, label=lab)
        axs[0, 1].plot(k, [f(x, "thd") for x in r], "o-", color=col, ms=5, mec=SURF, mew=1, label=lab)
    axs[0, 0].set(title="(a) Pair mismatch: OPT DC imbalance", xlabel="V4 KG1 / nominal  (>1 = less current)",
                  ylabel="|Ik(V3) - Ik(V4)| (mA)")
    axs[0, 0].legend(loc="upper center", fontsize=8.5)
    axs[0, 1].set(title="(b) Pair mismatch: THD at 10 W", xlabel="V4 KG1 / nominal", ylabel="THD (%)", ylim=(0, None))
    # (c,d) common shift
    for bias, col, lab in [("fixed -40.9 V", C2, "bias fixed at -40.9 V"), ("trimmed", C1, "trimmed to 34.4 mA")]:
        r = [x for x in rows if x["study"] == "common_shift" and x["bias"] == bias]
        k = [float(x["case"].split("x")[-1]) for x in r]
        axs[0, 2].plot(k, [max(f(x, "pa"), f(x, "pb")) for x in r], "o-", color=col, ms=5, mec=SURF, mew=1, label=lab)
    axs[0, 2].axhline(20.5, color=C4, lw=2, ls="--")
    axs[0, 2].text(0.81, 21.0, "rating 20.5 W", color=INK2, fontsize=9)
    axs[0, 2].set(title="(c) Both output tubes shifted: idle Pa", xlabel="V3 and V4 KG1 / nominal",
                  ylabel="Pa per tube (W)", ylim=(0, 32))
    axs[0, 2].legend(loc="upper right", fontsize=8.5)
    # (d) driver tubes
    for name, col in [("6N2 (V1) KG1", C1), ("6N1 both halves KG1", C2), ("6N1 halves mismatched", C3)]:
        r = [x for x in rows if x["study"] == "driver" and x["case"].startswith(name)]
        k = [float(x["case"].split("x")[-1]) for x in r]
        axs[1, 0].plot(k, [f(x, "thd") for x in r], "o-", color=col, ms=5, mec=SURF, mew=1, label=name)
    axs[1, 0].set(title="(d) Driver tubes: THD at 10 W (output trimmed)", xlabel="KG1 / nominal",
                  ylabel="THD (%)", ylim=(0, None))
    axs[1, 0].legend(loc="lower right", fontsize=8.5)
    # (e,f) Monte Carlo
    mu = [x for x in rows if x["study"] == "monte_carlo" and x["bias"] == "fixed -40.9 V"]
    mt = [x for x in rows if x["study"] == "monte_carlo" and x["bias"] == "trimmed"]
    pa_u = np.array([max(f(x, "pa"), f(x, "pb")) for x in mu])
    bins = np.arange(4, 30, 1.0)
    axs[1, 1].hist(pa_u, bins=bins, color=C2, alpha=0.85, rwidth=0.9)
    axs[1, 1].axvline(20.5, color=C4, lw=2, ls="--")
    axs[1, 1].axvline(13.7, color=C1, lw=2)
    axs[1, 1].text(13.9, axs[1, 1].get_ylim()[1] * 0.92, "trimmed: 13.7 W", color=INK2, fontsize=9)
    n_over = int((pa_u > 20.5).sum())
    axs[1, 1].text(20.8, axs[1, 1].get_ylim()[1] * 0.8, f"{n_over} of {len(pa_u)}\nover 20.5 W", color=INK2, fontsize=9)
    axs[1, 1].set(title="(e) Monte Carlo (200): hotter tube idle Pa",
                  xlabel="Pa of the hotter output tube, bias fixed at -40.9 V (W)", ylabel="Count")
    t_u = np.array([f(x, "thd") for x in mu]); t_t = np.array([f(x, "thd") for x in mt])
    tb = np.linspace(0, max(np.nanpercentile(t_u, 99), np.nanpercentile(t_t, 99)) * 1.05, 26)
    axs[1, 2].hist(t_u, bins=tb, color=C2, alpha=0.6, label=f"fixed -40.9 V: median {np.nanmedian(t_u):.2f} %")
    axs[1, 2].hist(t_t, bins=tb, color=C1, alpha=0.6, label=f"trimmed: median {np.nanmedian(t_t):.2f} %")
    axs[1, 2].set(title="(f) Monte Carlo (200): THD at 10 W", xlabel="THD (%)", ylabel="Count")
    axs[1, 2].legend(loc="upper right", fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig18_tube_spread.png",
         "v1.5, 4 ohm, ideal 400 V. KG1 sets tube current (Ia ~ 1/KG1). Monte Carlo: KG1 lognormal sigma 10 %, mu sigma 3 %, all 5 tubes independent. "
         "Data: docs/data/fig18_tube_spread.csv")


# ---------------------------------------------------------------- bias supply (fig19)
def stereo_meas(meas, tstop=0.5, t0=0.45, timeout=900, **kw):
    net = stereo(**kw) + ".control\n" + f"tran 10u {tstop} 0 10u\n" + \
        "".join(f"meas tran {n} avg {e} from={t0} to={tstop}\n" for n, e in meas.items()) + ".endc\n.end\n"
    o, _ = ngspice(net, timeout=timeout)
    return {n: float(re.search(rf"(?m)^{n}\s+=\s+(\S+)", o).group(1)) for n in meas}


def _tone120(t, y, f=120.0):
    y = y - np.polyval(np.polyfit(t, y, 1), t)
    a = 2 * np.mean(y * np.cos(2 * np.pi * f * t)); b = 2 * np.mean(y * np.sin(2 * np.pi * f * t))
    return np.hypot(a, b) / np.sqrt(2)


def fig19():
    """Bias supply model: start-up, mains tracking, pot range, hum."""
    rows = []
    fig, axs = plt.subplots(2, 2, figsize=(12.0, 8.2))
    # (a)(b) cold start, bias supply model vs ideal bias source
    for lab, rb, col in [("bias supply model", True, C1), ("ideal bias source", False, C2)]:
        d = ng_wrdata(stereo(0, ic=False, real_bias=rb) + ".options method=gear\n", "tran 100u 3 0 100u",
                      ["v(bp)", "v(xl.bias)", "v(xl.ka)"], timeout=1800)
        axs[0, 0].plot(d[:, 0], d[:, 3] * 1e3, color=col, label=lab)
        if rb:
            axs[0, 1].plot(d[:, 0], d[:, 1], color=C1, label="B+")
            axs[0, 1].plot(d[:, 0], -d[:, 2] * 5, color=C3, label="grid bias x (-5)")
        k = int(np.argmax(d[:, 3]))
        rows.append(("startup_peak_Ik", lab, float(d[k, 3] * 1e3), float(d[k, 0])))
    axs[0, 0].axhline(34.4, color=INK2, lw=1, ls=":")
    axs[0, 0].set(title="(a) Switch-on: output tube current", xlabel="Time (s)", ylabel="Ik V3 (mA)", xlim=(0, 3))
    axs[0, 0].legend(loc="upper right", fontsize=8.5)
    axs[0, 1].set(title="(b) Switch-on: B+ and grid bias (bias supply model)", xlabel="Time (s)",
                  ylabel="Volts (bias shown x -5)", xlim=(0, 1))
    axs[0, 1].legend(loc="lower right", fontsize=8.5)
    # (c) mains tracking
    mains = [0.9, 0.95, 1.0, 1.05, 1.1]
    meas = {"ik": "v(xl.ka)", "pa": "v(xl.pa)", "bp": "v(bp)", "g": "v(xl.bias)", "nb": "v(nbus)"}

    def mjob(j):
        mm, rb = j
        over = {} if rb else {"VBN": f"{-41.02/mm:.4f}"}     # ideal source held at -41.02 V for all mains
        return mm, rb, stereo_meas(meas, tstop=1.0, t0=0.95, mains=mm, real_bias=rb, **over)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        res = list(ex.map(mjob, [(mm, rb) for rb in (True, False) for mm in mains]))
    for rb, col, lab in [(True, C1, "bias supply model (tracks mains)"), (False, C2, "bias held at -41.0 V")]:
        r = [x for x in res if x[1] == rb]
        axs[1, 0].plot([110 * x[0] for x in r], [x[2]["ik"] * x[2]["pa"] for x in r], "o-", color=col, ms=5,
                       mec=SURF, mew=1, label=lab)
        for mm, _, x in r:
            rows.append(("mains", lab, mm, x["bp"], x["g"], x["nb"], x["ik"] * 1e3, x["ik"] * x["pa"]))
    axs[1, 0].axhline(20.5, color=C4, lw=2, ls="--")
    axs[1, 0].text(99.5, 21.0, "rating 20.5 W", color=INK2, fontsize=9)
    axs[1, 0].set(title="(c) Mains variation: idle Pa per tube", xlabel="Mains (V rms)", ylabel="Pa (W)", ylim=(0, 26))
    axs[1, 0].legend(loc="upper left", fontsize=8.5)
    # (d) pot range at three mains levels vs the Monte Carlo requirement
    rbot = 56e3
    rt = 15e3 + 25e3 + rbot
    w = np.linspace(0, 1, 51)
    for mm, col in [(0.9, C2), (1.0, C1), (1.1, C3)]:
        nb = [x[2]["nb"] for x in res if x[1] and abs(x[0] - mm) < 1e-6][0]
        axs[1, 1].plot(w, nb * (rbot + w * 25e3) / rt, color=col, label=f"mains {110*mm:.0f} V (bus {nb:.1f} V)")
        rows.append(("pot_range", f"mains {mm}", nb, nb * rbot / rt, nb * (rbot + 25e3) / rt))
    import csv
    with open(os.path.join(DATA, "fig18_tube_spread.csv"), encoding="utf-8") as fh:
        mc = [r for r in csv.DictReader(fh) if r["study"] == "monte_carlo" and r["bias"] == "trimmed"]
    need = [float(r["vb"]) for r in mc] + [float(r["vb"]) + float(r["dvb"]) for r in mc]
    nlo, nhi = min(need), max(need)
    rows.append(("mc_bias_needed", "fig18 trimmed", nlo, nhi))
    axs[1, 1].axhspan(nlo, nhi, color=GRID, alpha=0.6, lw=0)
    axs[1, 1].text(0.02, nlo + 0.3, f"needed by the 200 Monte Carlo amps (fig 18): {nhi:.1f} ... {nlo:.1f} V",
                   color=INK2, fontsize=8.5, va="bottom")
    axs[1, 1].set(title="(d) Bias pot range (15k - 25k pot - 56k)", xlabel="Pot position (0 = least negative)",
                  ylabel="Grid bias (V)", xlim=(0, 1))
    axs[1, 1].legend(loc="upper right", fontsize=8.5)
    fig.tight_layout()
    # hum at 120 Hz: bias supply vs ideal bias, matched and 5 % mismatched pair
    for rb in (True, False):
        for kgb in ("1640", "1722"):
            d = ng_wrdata(stereo(0, real_bias=rb, KGB=kgb), "tran 10u 0.55 0.5 10u", ["v(outl)", "v(xl.bias)", "v(nbus)"])
            t = d[:, 0] - d[0, 0]
            rows.append(("hum_120Hz_rms_V", "bias supply" if rb else "ideal bias", "matched" if kgb == "1640" else "V4 5 % low",
                         _tone120(t, d[:, 1]), _tone120(t, d[:, 2]), _tone120(t, d[:, 3])))
    write_csv("fig19_bias_supply.csv", ["item", "case", "a", "b", "c", "d", "e", "f"],
              [tuple(r) + ("",) * (8 - len(r)) for r in rows])
    for r in rows:
        print("   ", r)
    save(fig, "fig19_bias_supply.png",
         "Bias winding 45 Vrms (assumed), half-wave, 47u - 1k - 100u, then one 15k / 25k pot / 56k divider + 10 uF per tube. "
         "Data: docs/data/fig19_bias_supply.csv")


# ---------------------------------------------------------------- OPT winding capacitance (fig20)
CAP_CPP = ["1p", "100p", "300p", "1n"]
CAP_CPS = ["1p", "300p", "1n", "3n"]
CAP_LOADS = [("4 ohm", "", {}), ("ELT 10", "", None), ("no load", "", {"RL": "1e6"}),
             ("0.47 uF only", "CLD out 0 0.47u\n", {"RL": "1e6"}), ("2 uF only", "CLD out 0 2u\n", {"RL": "1e6"})]
CAP_VERS = [("v1.4", V14), ("v1.5", {}), ("v1.5-C", V15C)]
OPT_GRID = list(__import__("itertools").product([4000, 5000, 6000, 6600, 8000], [0.2, 0.3, 0.43, 0.55], [5, 10],
                                                [0.999, 0.9995, 0.9998]))


def _load_over(lov):
    return dict(SPKR) if lov is None else dict(lov)


def fig20():
    """OPT winding capacitance: v1.4 vs v1.5 vs v1.5-C, nominal OPT and worst case over the OPT grid."""
    rows = []
    # nominal OPT, full capacitance matrix, v1.4 and v1.5, resistive / speaker / open loads
    jobs = [(vn, vo, cpp, cps, ln, ex, lov) for vn, vo in CAP_VERS[:2] for cpp in CAP_CPP for cps in CAP_CPS
            for ln, ex, lov in CAP_LOADS[:3]]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex_:
        res = list(ex_.map(lambda j: loop_margins(j[5], CPP=j[2], CPS=j[3], **_load_over(j[6]), **j[1]), jobs))
    for j, (fc, pm, gm) in zip(jobs, res):
        rows.append(("nominal_OPT", j[0], j[2], j[3], j[4], fc, pm, gm, ""))
    # grid worst: typical and high winding capacitance, every load
    worst = {}
    for vn, vo in CAP_VERS:
        for cpp, cps in [("300p", "1n"), ("1n", "3n")]:
            for ln, ex, lov in CAP_LOADS:
                with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex_:
                    r = list(ex_.map(lambda g: loop_margins(ex, RAA=g[0], TU=g[1], LH=g[2], KC=g[3], CPP=cpp, CPS=cps,
                                                            **_load_over(lov), **vo), OPT_GRID))
                pm = np.array([np.nan_to_num(x[1], nan=-90) for x in r]); gm = np.array([np.nan_to_num(x[2], nan=-30) for x in r])
                worst[(vn, cpp, cps, ln)] = (pm.min(), gm.min(), int(((pm < 20) | (gm < 3)).sum()))
                rows.append(("grid_worst", vn, cpp, cps, ln, "", pm.min(), gm.min(), worst[(vn, cpp, cps, ln)][2]))
    # in-band response of each version
    for vn, vo in CAP_VERS:
        mt = ac_metrics(**vo)
        f, db = ac_curve(**vo)
        rows.append(("response", vn, "", "", "4 ohm", mt["fhi"], float(np.interp(np.log10(2e4), np.log10(f), db)), mt["df"], ""))
    write_csv("fig20_opt_capacitance.csv", ["study", "version", "CPP", "CPS", "load", "crossover_Hz_or_f3dB",
                                            "PM_deg_or_dB20k", "GM_dB_or_DF", "n_bad_of_120"], rows)
    # ---- figure
    fig, axs = plt.subplots(2, 2, figsize=(12.6, 9.0))
    a = axs[0, 0]
    for (vn, vo), (cpp, cps), col, ls in [(CAP_VERS[0], ("300p", "1n"), C2, "--"), (CAP_VERS[1], ("1p", "1p"), C4, ":"),
                                          (CAP_VERS[1], ("300p", "1n"), C1, "-"), (CAP_VERS[1], ("1n", "3n"), C3, "-"),
                                          (CAP_VERS[2], ("300p", "1n"), INK2, "-.")]:
        f, db = ac_curve(CPP=cpp, CPS=cps, **vo)
        lab = f"{vn}, " + ("no winding C" if cpp == "1p" else f"CPP {cpp} / CPS {cps}")
        a.semilogx(f, db, color=col, ls=ls, label=lab)
    a.axhline(-3, color=INK2, lw=1, ls=":")
    a.set(title="(a) Closed-loop response, 4 ohm, nominal OPT", xlabel="Frequency (Hz)", ylabel="Gain re 1 kHz (dB)",
          xlim=(1e3, 5e6), ylim=(-30, 15))
    a.legend(loc="lower left", fontsize=8.5)
    for a, vn in [(axs[0, 1], "v1.4"), (axs[1, 0], "v1.5")]:
        m = np.array([[[r[7] for r in rows if r[0] == "nominal_OPT" and r[1] == vn and r[2] == cpp and r[3] == cps
                        and r[4] == "4 ohm"][0] for cps in CAP_CPS] for cpp in CAP_CPP], dtype=float)
        a.imshow(np.clip(m, -10, 40), cmap="Blues", vmin=-10, vmax=40, origin="lower", aspect="auto")
        for i in range(len(CAP_CPP)):
            for j in range(len(CAP_CPS)):
                v = m[i, j]
                a.text(j, i, "osc." if not np.isfinite(v) or v < 0 else f"{v:.1f}", ha="center", va="center", fontsize=9.5,
                       color=SURF if (np.isfinite(v) and v > 22) else INK)
        a.set_xticks(range(len(CAP_CPS)), ["0" if c == "1p" else c for c in CAP_CPS])
        a.set_yticks(range(len(CAP_CPP)), ["0" if c == "1p" else c for c in CAP_CPP])
        a.set(title=f"({'b' if vn == 'v1.4' else 'c'}) Gain margin (dB), {vn}, 4 ohm, nominal OPT",
              xlabel="Primary-secondary C (CPS)", ylabel="Plate-plate C (CPP)")
        a.grid(False)
    a = axs[1, 1]
    lnames = [l[0] for l in CAP_LOADS]
    x = np.arange(len(lnames)); w = 0.26
    for k, ((vn, _), col) in enumerate(zip(CAP_VERS, [C2, C1, INK2])):
        g = [worst[(vn, "300p", "1n", ln)][1] for ln in lnames]
        a.bar(x + (k - 1) * w, np.clip(g, -12, None), w, color=col, label=vn)
    a.axhline(0, color=INK, lw=1)
    a.axhline(3, color=INK2, lw=1, ls=":")
    a.set_xticks(x, lnames)
    a.set(title="(d) Worst gain margin over 120 OPT cases, CPP 300p / CPS 1n", ylabel="GM (dB), < 0 = oscillates")
    a.legend(loc="upper right", fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig20_opt_capacitance.png",
         "Lumped OPT winding capacitance (CPP plate-plate, CPS primary-secondary, values assumed). v1.5-C = v1.5 with "
         "step 3.3k+1n and CFB 220p. Data: docs/data/fig20_opt_capacitance.csv")
    for k, v in worst.items():
        print("   worst", k, f"PM {v[0]:.0f} GM {v[1]:.1f} bad {v[2]}")
    return rows, worst


# ---------------------------------------------------------------- OPT core saturation (fig21)
SATF = [12, 20, 30, 40]                 # Hz at which 25 W drives the core flux to LSAT (assumed range)
SAT_REF = 20                            # reference case
LF_FREQS = [20, 25, 30, 40, 60, 100, 200]
SAT_CIR = os.path.join(ROOT, "simulations", "ltspice", "amp_channel_v1_sat.cir")


def build_sat_cir():
    """Write simulations/ltspice/amp_channel_v1_sat.cir: amp_channel_v1.cir with the saturable OPT."""
    src = open(CIR, encoding="utf-8").read().replace("\r\n", "\n")
    out = []
    for l in src.split("\n"):
        if re.match(r"(?i)^(L[1-5] |R[1-5]W |K[1-5][1-5] )", l):
            continue
        if l.startswith("CPPW "):
            out.append("* saturable-core OPT (models/opt_sat.inc) replaces the linear L1-L5 / K block")
            out.append("XOPT pa ula bp ulb pb out OPT_SAT PARAMS: LH={LH} TU={TU} KC={KC} RAA={RAA} "
                       "LSAT={LSAT} PSH={PSH} LMUL={LMUL} IDCX={IDCX}")
        out.append(l)
        if l.startswith(".include ../../models/tubes_amp.inc"):
            out.append(".include ../../models/opt_sat.inc")
        if l.startswith(".param CPP="):
            out.append(f".param LSAT={lsat_for(SAT_REF):.4f} PSH=4 LMUL=1 IDCX=0   ; core: flux limit (V*s, = 25 W at "
                       f"{SAT_REF} Hz), knee sharpness, inductance multiplier, extra DC imbalance (A)")
    txt = "\n".join(out)
    head = ("* =====================================================================\n"
            "*  amp_channel_v1_sat.cir  --  GENERATED by tools/make_figures.py (sat), do not edit.\n"
            "*  amp_channel_v1.cir with the saturable-core OPT of models/opt_sat.inc (README 4.10).\n"
            "*  LSAT large (e.g. 1e3) = linear core, identical to amp_channel_v1.cir.\n")
    assert txt.count("XOPT ") == 1 and "K12 " not in txt
    with open(SAT_CIR, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head + txt)
    return SAT_CIR


def tone_sat(freq, amp, **over):
    """(P W into 4 ohm, THD %, H2 %, H3 %) for one tone, any OPT model."""
    T = 1.0 / freq
    settle = max(0.15, 12 * T)
    win = max(2, int(np.ceil(0.02 / T))) * T
    step = min(10e-6, T / 400)
    net = (channel(**over) + f"VIN in 0 SIN(0 {amp} {freq:g})\n.control\n"
           f"tran {step:.3g} {settle+win:.6g} {settle:.6g} {step:.3g}\nfourier {freq:g} v(out)\n"
           f"meas tran vr rms v(out) from={settle:.6g} to={settle+win:.6g}\n.endc\n.end\n")
    for opts in ("", ".options method=gear reltol=2e-3\n"):
        o, _ = ngspice(net.replace(".control", opts + ".control", 1), timeout=240)
        m1, m2 = re.search(r"THD: (\S+)", o), re.search(r"vr\s+=\s+(\S+)", o)
        if m1 and m2:
            h = {int(a): float(b) * 100 for a, b in re.findall(r"(?m)^\s*([23])\s+\S+\s+\S+\s+\S+\s+(\S+)", o)}
            return float(m2.group(1)) ** 2 / 4.0, float(m1.group(1)), h.get(2, np.nan), h.get(3, np.nan)
    return np.nan, np.nan, np.nan, np.nan


def p_at_thd_sat(freq, limit=1.0, lo=0.2, hi=1.4, iters=7, **over):
    """Power at the THD limit (bisection on input amplitude) using tone_sat()."""
    best = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        p, thd = tone_sat(freq, f"{mid:.5f}", **over)[:2]
        if np.isfinite(thd) and thd <= limit:
            lo, best = mid, p
        else:
            hi = mid
    return best


def fig21():
    """Saturable OPT core: LF power limit, LF THD, DC-imbalance sensitivity, magnetizing current."""
    rows = []
    sat = lambda fs, **k: dict(OPT="sat", LSAT=f"{lsat_for(fs):.4f}", **k)
    # (0) check: saturable model with a huge LSAT equals the linear netlist
    lin_t, sat_t = tone_sat(1e3, 0.3), tone_sat(1e3, 0.3, OPT="sat")
    lin_m, sat_m = ac_metrics(), ac_metrics(OPT="sat")
    lin_l, sat_l = loop_margins(), loop_margins(OPT="sat")
    rows.append(("check_1kHz_THD_pct", "linear / sat(LSAT=1e3)", lin_t[1], sat_t[1]))
    rows.append(("check_gain_f3hi_Hz", "linear / sat(LSAT=1e3)", lin_m["gain"], sat_m["gain"], lin_m["fhi"], sat_m["fhi"]))
    rows.append(("check_PM_GM", "linear / sat(LSAT=1e3)", lin_l[1], sat_l[1], lin_l[2], sat_l[2]))
    # (a) max power at 1 % THD vs frequency
    cases = [("linear core", {})] + [(f"saturates at {fs} Hz", sat(fs)) for fs in SATF]
    jobs = [(lab, ov, f) for lab, ov in cases for f in LF_FREQS]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        pw = list(ex.map(lambda j: p_at_thd_sat(j[2], **j[1]), jobs))
    for (lab, _, f), p in zip(jobs, pw):
        rows.append(("P_1pct_W", lab, f, p))
    # (b) THD vs power at 20 / 30 / 50 Hz, reference core vs linear
    amps = [0.05, 0.1, 0.2, 0.3, 0.38, 0.45, 0.5, 0.55]
    jobs = [(f, lab, ov, a) for f in (20, 30, 50) for lab, ov in (("linear core", {}), (f"saturates at {SAT_REF} Hz", sat(SAT_REF)))
            for a in amps]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        tb = list(ex.map(lambda j: tone_sat(j[0], j[3], **j[2]), jobs))
    for (f, lab, _, a), r in zip(jobs, tb):
        rows.append(("THD_vs_P", lab, f, a) + tuple(r))
    # (c) DC imbalance at 30 Hz, 10 W
    a10 = np.sqrt(10 * 4) * np.sqrt(2) / lin_m["gain"]
    dis = [0, 0.002, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03]
    jobs = [(lm, di) for lm in (1, 3, 10) for di in dis]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        tc = list(ex.map(lambda j: tone_sat(30, a10, **sat(SAT_REF, LMUL=j[0], IDCX=j[1])), jobs))
    for (lm, di), r in zip(jobs, tc):
        rows.append(("dc_imbalance_30Hz_10W", f"LMUL {lm}", di * 1e3) + tuple(r))
    lin30 = tone_sat(30, a10)
    rows.append(("dc_imbalance_30Hz_10W", "linear core", 0.0) + tuple(lin30))
    # (d) magnetizing MMF waveform at 20 Hz, about 10 W
    waves = []
    a15 = np.sqrt(15 * 4) * np.sqrt(2) / lin_m["gain"]
    for lab, di, col in [("balanced", 0.0, C1), ("20 mA imbalance", 0.02, C2)]:
        T = 1 / 20.0
        d = ng_wrdata(channel(**sat(SAT_REF, LMUL=3, IDCX=di)) + f"VIN in 0 SIN(0 {a15:.4f} 20)\n",
                      f"tran 50u {16*T:g} {14*T:g} 50u", ["v(xopt.f)", "v(xopt.phi)", "v(out)"], timeout=600)
        waves.append((lab, col, d))
    for lab, _, d in waves:
        rows.append(("mmf_20Hz_15W_LMUL3", lab, float(d[:, 1].min() * 1e3), float(d[:, 1].max() * 1e3),
                     float(d[:, 2].min()), float(d[:, 2].max())))
    write_csv("fig21_opt_saturation.csv", ["study", "case", "a", "b", "c", "d", "e", "f"],
              [tuple(r) + ("",) * (8 - len(r)) for r in rows])
    # ---- figure
    fig, axs = plt.subplots(2, 2, figsize=(12.6, 9.0))
    a = axs[0, 0]
    for (lab, _), col, ls in zip(cases, [INK2, C2, C1, C3, C4], ["--", "-", "-", "-", "-"]):
        p = [r[3] for r in rows if r[0] == "P_1pct_W" and r[1] == lab]
        a.semilogx(LF_FREQS, p, "o" + ls, color=col, ms=4.5, mec=SURF, mew=1, label=lab)
    a.set(title="(a) Max power at 1 % THD, 4 ohm", xlabel="Frequency (Hz)", ylabel="Power (W)", ylim=(0, None))
    a.set_xticks(LF_FREQS, [str(f) for f in LF_FREQS])
    a.legend(loc="lower right", fontsize=8.5)
    a = axs[0, 1]
    for f, col in zip((20, 30, 50), (C2, C1, C3)):
        for lab, ls in (("linear core", ":"), (f"saturates at {SAT_REF} Hz", "-")):
            r = [x for x in rows if x[0] == "THD_vs_P" and x[1] == lab and x[2] == f]
            a.loglog([x[4] for x in r], [x[5] for x in r], ls, color=col, marker="o", ms=3.5,
                     label=f"{f} Hz" + (", linear core" if ls == ":" else ""))
    a.axhline(1, color=INK2, lw=1, ls=":")
    a.set(title=f"(b) THD vs power, core saturating at {SAT_REF} Hz (dotted: linear)", xlabel="Power (W)", ylabel="THD (%)")
    a.legend(loc="upper left", fontsize=8, ncol=2)
    a = axs[1, 0]
    for lm, col in zip((1, 3, 10), (C1, C3, C2)):
        r = [x for x in rows if x[0] == "dc_imbalance_30Hz_10W" and x[1] == f"LMUL {lm}"]
        a.plot([x[2] for x in r], [x[4] for x in r], "o-", color=col, ms=5, mec=SURF, mew=1,
               label=f"core inductance x{lm} ({40*lm} H)")
        a.plot([x[2] for x in r], [x[5] for x in r], "o--", color=col, ms=3.5, lw=1)
    a.axhline(lin30[1], color=INK2, lw=1, ls=":")
    a.text(0.5, lin30[1] * 1.04, "linear core", color=INK2, fontsize=8.5, va="bottom")
    a.set(title=f"(c) 30 Hz, 10 W: THD (solid) and H2 (dashed) vs DC imbalance", xlabel="Output-tube DC imbalance (mA)",
          ylabel="%", yscale="log")
    a.legend(loc="upper left", fontsize=8.5)
    a = axs[1, 1]
    for lab, col, d in waves:
        t = (d[:, 0] - d[0, 0]) * 1e3
        a.plot(t, d[:, 1] * 1e3, color=col, label=lab)
    a.set(title="(d) Core MMF at 20 Hz, 15 W, core x3 (= magnetizing current)", xlabel="Time (ms)",
          ylabel="MMF (mA, half-primary turns)")
    a.legend(loc="upper right", fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig21_opt_saturation.png",
         f"Saturable OPT core (models/opt_sat.inc), no hysteresis. 'Saturates at f Hz' = 25 W at f reaches the flux limit "
         f"(assumed). (b)-(d) use {SAT_REF} Hz. Data: docs/data/fig21_opt_saturation.csv")
    build_sat_cir()
    for r in rows:
        if r[0] != "THD_vs_P":
            print("   ", r)
    return rows


ALL = dict(fig1=fig1, fig2=fig2, fig3=fig3, fig4=fig4, fig5=fig5, fig6=fig6, fig7=fig7,
           fig8=fig8, fig9=fig9, fig10=fig10, fig11=fig11, fig12=fig12, fig13=fig13, fig14=fig14, fig15=fig15, fig16=fig16, fig17=fig17, fig18=fig18, plot18=plot_fig18, fig19=fig19, fig20=fig20, fig21=fig21, sat=lambda: print("  wrote", os.path.relpath(build_sat_cir(), ROOT)), plot11=plot_fig11, plot12=plot_fig12, stereo=lambda: print("  wrote", os.path.relpath(STEREO, ROOT)) if build_stereo() else None)
if __name__ == "__main__":
    for k in (sys.argv[1:] or ALL):
        print(k)
        ALL[k]()
