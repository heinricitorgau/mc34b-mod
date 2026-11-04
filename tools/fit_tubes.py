#!/usr/bin/env python3
"""
fit_tubes.py -- fit the output-tube models (6P3S-E, 6P3P) to digitized datasheet curves.

    python tools/fit_tubes.py          # fit, print parameters, write fig22 + docs/data/tube_fit.csv

Data: docs/data/tube_curves/*.csv (columns source, Ug2_V, Ug1_V, Ua_V, Ia_mA), digitized from
  6P3S  : kutilovo.cz datasheet sheet 104316 (plate curves at Ug1 = 0, and at Ug2 = 250 V)
  6P3P  : r-type.org/pdfs/6p3p.pdf (Chinese tube handbook, pages 100-101)
plus each sheet's typical point 250 V / 250 V / -14 V (source "table", weighted x4).

Model: the same equations as the 6P3S-E / 6P3P subcircuits in models/tubes_amp.inc
  E1 = Vg2/KP * softplus(KP * (1/MU + Vg1/Vg2))
  Ia = 2 * E1^EX / KG1 * atan(Va/KVB) * (1 + LAM*Va)
  Ig2 = max(Vg2/MU + Vg1, 0)^EX / KG2           (KG2 set from the sheet's screen current)
Fitted: MU, EX, KG1, KP, KVB, LAM by least squares on log(Ia). LAM (plate-voltage slope above the knee)
is an addition to Koren's form; LAM = 0 gives the original equation. Requires numpy, scipy, matplotlib.
The Python model is checked against the SPICE subcircuit in ngspice at a few points.
"""
import csv
import os
import re
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(__file__))
import make_figures as mf  # noqa: E402  (plot style, ngspice runner)

ROOT = mf.ROOT
CURVES = os.path.join(ROOT, "docs", "data", "tube_curves")
TUBES = {   # name: (data file, screen current at 250/250/-14 (A), where that value comes from)
    "6P3S-E": ("6P3S_kutilovo.csv", 5.0e-3, "6P3S-E sheet: max 6 mA; 5 mA assumed typical"),
    "6P3P": ("6P3P_r-type.csv", None, "dashed Ig2 curve on the 6P3P sheet: about 10 mA at Ug1 = 0, Ua >= 200 V"),
}
V3 = dict(MU=8.7, EX=1.35, KG1=1640, KP=48, KVB=12, LAM=0)    # previous single-point fit (README 4.9)
PK = ("MU", "EX", "KG1", "KP", "KVB", "LAM")


def softp(x):
    return np.maximum(x, 0) + np.log1p(np.exp(-np.abs(x)))


def ia_model(p, ug1, ug2, ua):
    mu, ex, kg1, kp, kvb, lam = p
    e1 = ug2 / kp * softp(kp * (1 / mu + ug1 / ug2))
    return 2 * e1 ** ex / kg1 * np.arctan(ua / kvb) * (1 + lam * ua)


def load(fn):
    rows = list(csv.DictReader(open(os.path.join(CURVES, fn), encoding="utf-8")))
    a = {k: np.array([float(r[k]) for r in rows]) for k in ("Ug2_V", "Ug1_V", "Ua_V", "Ia_mA")}
    a["src"] = np.array([r["source"] for r in rows])
    return a


def fit(d):
    w = np.where(d["src"] == "table", 4.0, 1.0) * np.where(d["Ia_mA"] < 10, 0.5, 1.0)
    ia = d["Ia_mA"] * 1e-3

    def res(p):
        return w * (np.log(ia_model(p, d["Ug1_V"], d["Ug2_V"], d["Ua_V"])) - np.log(ia))
    best = None
    for kvb0 in (5, 12, 30):          # several starts: the knee parameter has local minima
        f = least_squares(res, [9, 1.35, 1500, 40, kvb0, 1e-4],
                          bounds=([3, 1.0, 100, 1, 1, 0], [30, 2.5, 20000, 2000, 200, 0.01]))
        if best is None or f.cost < best.cost:
            best = f
    return best.x


def err(p, d):
    r = ia_model(p, d["Ug1_V"], d["Ug2_V"], d["Ua_V"]) / (d["Ia_mA"] * 1e-3) - 1
    return 100 * np.sqrt(np.mean(r ** 2)), 100 * np.max(np.abs(r))


def point(p, ug1, ug2, ua):
    f = lambda a, b, c: ia_model(p, np.array([a]), np.array([b]), np.array([c]))[0]
    gm = (f(ug1 + 0.1, ug2, ua) - f(ug1 - 0.1, ug2, ua)) / 0.2
    ri = 10 / (f(ug1, ug2, ua + 5) - f(ug1, ug2, ua - 5))
    return f(ug1, ug2, ua), gm, ri


def spice_check(name, pars):
    """Ia from the SPICE subcircuit (with the fitted parameters) at a few points."""
    pts = [(250, -14, 250), (250, 0, 150), (250, -25, 300), (150, 0, 200)]
    net = f".include {mf.model_path('tubes_amp.inc')}\n"
    for i, (g2, g1, a) in enumerate(pts):
        net += (f"VA{i} a{i} 0 {a}\nVS{i} s{i} 0 {g2}\nVG{i} g{i} 0 {g1}\n"
                f"X{i} a{i} s{i} g{i} 0 {name} " + " ".join(f"{k}={v:.6g}" for k, v in pars.items()) + "\n")
    net += ".control\nop\n" + "".join(f"print -i(VA{i})\n" for i in range(len(pts))) + ".endc\n.end\n"
    o, _ = mf.ngspice(net)
    got = [float(x) for x in re.findall(r"(?i)-i\(va\d+\)\s*=\s*(\S+)", o)]
    want = [ia_model([pars[k] for k in PK], np.array([g1]), np.array([g2]), np.array([a]))[0]
            for g2, g1, a in pts]
    return list(zip(pts, want, got))


def main():
    rows, fits = [], {}
    for name, (fn, ig2, ig2_note) in TUBES.items():
        d = load(fn)
        p = fit(d)
        mu, ex, kg1, kp, kvb, lam = p
        if ig2 is None:      # 6P3P: screen current from the dashed curve, Ug1 = 0, Ug2 = 250 V, about 10 mA
            kg2 = (250 / mu) ** ex / 10e-3
        else:
            kg2 = (250 / mu - 14) ** ex / ig2
        pars = dict(MU=mu, EX=ex, KG1=kg1, KG2=kg2, KP=kp, KVB=kvb, LAM=lam)
        fits[name] = (p, d, pars)
        e_old, e_new = err([V3[k] for k in PK], d), err(p, d)
        ia, gm, ri = point(p, -14, 250, 250)
        ig2_14 = max(250 / mu - 14, 0) ** ex / kg2
        print(f"{name}: " + " ".join(f"{k}={v:.4g}" for k, v in pars.items()))
        print(f"   rms / max error: v3 {e_old[0]:.1f} / {e_old[1]:.0f} %  ->  fit {e_new[0]:.1f} / {e_new[1]:.0f} %  ({len(d['Ia_mA'])} points)")
        print(f"   250/250/-14 V: Ia {ia*1e3:.1f} mA, Ig2 {ig2_14*1e3:.1f} mA, gm {gm*1e3:.2f} mA/V, ri {ri/1e3:.0f} k")
        for pt, want, got in spice_check(name, pars):
            print(f"   SPICE check {pt}: python {want*1e3:.3f} mA, ngspice {got*1e3:.3f} mA")
        rows.append((name, *[pars[k] for k in ("MU", "EX", "KG1", "KG2", "KP", "KVB", "LAM")], e_old[0], e_new[0], e_new[1],
                     ia * 1e3, ig2_14 * 1e3, gm * 1e3, ri / 1e3, len(d["Ia_mA"]), ig2_note))
    mf.write_csv("tube_fit.csv", ["tube", "MU", "EX", "KG1", "KG2", "KP", "KVB", "LAM", "rms_err_v3_pct", "rms_err_fit_pct",
                                  "max_err_fit_pct", "Ia_250_250_m14_mA", "Ig2_mA", "gm_mA_per_V", "ri_kohm", "n_points",
                                  "screen_current_basis"], rows)
    plot(fits)


def plot(fits):
    plt = mf.plt
    fig, axs = plt.subplots(2, 2, figsize=(12.6, 9.0))
    cols = [mf.C1, mf.C2, mf.C3, mf.C4, mf.INK2, mf.C1, mf.C2, mf.C3, mf.C4]
    v3 = [V3[k] for k in PK]
    for j, (name, (p, d, _)) in enumerate(fits.items()):
        for i, kind in enumerate(("Ug2", "Ug1")):
            a = axs[i, j]
            if kind == "Ug2":          # family at Ug2 = 250 V, varying Ug1
                sel = (d["Ug2_V"] == 250) & (d["src"] != "table") & (d["src"] != "p100_Ug1_0") & (d["src"] != "chart1")
                fam = sorted(set(d["Ug1_V"][sel]), reverse=True)
                key, fixed = "Ug1_V", dict(ug2=250.0)
                title = f"({'ab'[j]}) {name}: Ug2 = 250 V"
            else:                      # family at Ug1 = 0, varying Ug2
                sel = (d["Ug1_V"] == 0) & ((d["src"] == "chart1") | (d["src"] == "p100_Ug1_0"))
                fam = sorted(set(d["Ug2_V"][sel]), reverse=True)
                key, fixed = "Ug2_V", dict(ug1=0.0)
                title = f"({'cd'[j]}) {name}: Ug1 = 0 V"
            ua = np.linspace(20, 440 if name == "6P3P" else 340, 200)
            for k, v in enumerate(fam):
                m = sel & (d[key] == v)
                col = cols[k % len(cols)]
                a.plot(d["Ua_V"][m], d["Ia_mA"][m], "o", ms=4, color=col, mec=mf.SURF, mew=0.8)
                g1 = v if key == "Ug1_V" else fixed["ug1"]
                g2 = v if key == "Ug2_V" else fixed["ug2"]
                a.plot(ua, ia_model(p, g1, g2, ua) * 1e3, color=col, lw=1.6)
                a.plot(ua, ia_model(v3, g1, g2, ua) * 1e3, color=col, lw=1, ls=":")
                lab = f"{'Ug1' if key == 'Ug1_V' else 'Ug2'} {v:+g} V" if key == "Ug1_V" else f"Ug2 {v:g} V"
                a.text(ua[-1], ia_model(p, g1, g2, ua[-1:])[0] * 1e3, " " + lab, fontsize=8, color=col, va="center")
            a.set(title=title, xlabel="Plate voltage (V)", ylabel="Plate current (mA)", ylim=(0, None),
                  xlim=(0, ua[-1] * 1.18))
    fig.tight_layout()
    mf.save(fig, "fig22_tube_fit.png",
            "Dots: digitized datasheet curves (docs/data/tube_curves). Solid: fitted model. Dotted: previous model v3 "
            "(Koren 6L6GC with KG1 1640). Data: docs/data/tube_fit.csv")


if __name__ == "__main__":
    main()
