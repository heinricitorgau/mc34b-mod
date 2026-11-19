#!/usr/bin/env python3
"""
ci_check.py -- quick regression check of the simulation baseline (about 30 s).

    python tools/ci_check.py

Runs in CI on every change and can be run locally.  It does not regenerate any
figure; it re-measures the handful of numbers the README states for the v1.5
baseline, straight from models/ and simulations/ltspice/amp_channel_v1.cir,
and fails if one has drifted:

  1. the LTspice schematic regenerates from the netlist with 0 mismatches;
  2. every netlist in simulations/ltspice/ runs in ngspice;
  3. the tube constants copied out of models/tubes_amp.inc (the netlist's
     KGA / KGB, NOM in make_figures.py) still match the model file;
  4. operating point, gain, bandwidth, damping factor, THD at 10 W and power
     at 1 % THD match the README within the tolerances below;
  5. loop stability into 4 ohm, the estimated ELT 10 and no load meets the
     pass marks used throughout the write-up (phase margin >= 20 deg, gain
     margin >= 3 dB).

The tolerances are a little wider than the README's rounding so that a
different ngspice release does not fail the check, but a changed part value
or tube model does.  If a design change moves one of these numbers on
purpose, update the README and docs/DESIGN.md tables and the EXPECT table
here in the same commit.

Requires: ngspice (>= 38) on PATH, Python 3.9+, numpy, matplotlib.
"""
import os
import re
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_figures as mf  # noqa: E402

# name: (expected, tolerance, unit) -- expected values as stated in the README (baseline v1.5)
EXPECT = {
    "idle current per tube": (34.4, 0.2, "mA"),
    "idle plate dissipation": (13.7, 0.2, "W"),
    "closed-loop gain": (24.2, 0.2, "x"),
    "-3 dB low": (7.6, 0.3, "Hz"),
    "-3 dB high": (32.0, 1.5, "kHz"),
    "damping factor": (11.6, 0.3, ""),
    "THD at 10 W, 1 kHz": (0.28, 0.04, "%"),
    "power at 1 % THD": (24.0, 1.5, "W"),
}
PM_MIN, GM_MIN = 20.0, 3.0
LOADS = [("4 ohm", {}), ("ELT 10 (estimated)", {"SPK": "1", "RL": "1e6"}), ("no load", {"RL": "1e6"})]
FATAL = re.compile(r"(?i)fatal|singular matrix|simulation\(s\) aborted|unknown subckt|no such")

failures = []


def report(name, ok, text):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name:28s} {text}")
    if not ok:
        failures.append(name)


def check_schematic():
    print("schematic")
    r = subprocess.run([sys.executable, os.path.join(mf.ROOT, "tools", "make_schematic.py")],
                       capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1].strip()
    report("netlist vs schematic", r.returncode == 0 and "0 mismatches" in last, last)


def check_netlists():
    print("netlists run in ngspice")
    d = os.path.join(mf.ROOT, "simulations", "ltspice")
    models = mf.ROOT.replace("\\", "/") + "/models/"
    for name in sorted(n for n in os.listdir(d) if n.endswith(".cir")):
        txt = open(os.path.join(d, name), encoding="utf-8").read().replace("../../models/", models)
        out, _ = mf._ngspice(mf.to_ngspice(txt), timeout=300)
        bad = FATAL.search(out)
        ok = bool(out) and not bad
        if ok and name.startswith("amp_"):          # amplifier netlists end in a Fourier analysis
            ok = "THD:" in out
        report(name, ok, "ran" if ok else (bad.group(0) if bad else "no result"))


def subckt_defaults():
    """{model name: {param: float}} from the PARAMS: defaults in models/tubes_amp.inc."""
    txt = open(os.path.join(mf.ROOT, "models", "tubes_amp.inc"), encoding="utf-8").read()
    out = {}
    for name, pars in re.findall(r"(?im)^\.SUBCKT\s+(\S+)[^\n]*?PARAMS:([^\n]*)", txt):
        out[name] = {k.upper(): float(v) for k, v in re.findall(r"(\w+)=([-+\d.eE]+)", pars)}
    return out


def check_model_sync():
    """The tube constants copied out of tubes_amp.inc must still match it.

    KG1 and MU of the tubes are repeated in two places that the netlist does not
    read back from the model: the netlist's KGA / KGB (instances override the
    6P3S-E default with KG1={KGA}) and NOM in make_figures.py (the nominal values
    the tube-spread study scales).  CLAUDE.md asks for all three to be updated
    together after tools/fit_tubes.py; a missed copy would not stop any netlist
    from running, it would silently simulate a different tube.
    """
    print("tube constants vs models/tubes_amp.inc")
    models = subckt_defaults()
    cir = open(mf.CIR, encoding="utf-8").read()
    inst = dict(re.findall(r"(?im)^(X\d+)\s+(?:\S+\s+){3,4}?(6N1|6N2|6P3S-E|6P3P)\b", cir))
    for ref, nom in mf.NOM.items():
        model = inst.get(ref)
        if model is None:
            report(f"NOM {ref}", False, "no such tube instance in amp_channel_v1.cir")
            continue
        bad = [f"{k} {v:g} != {models[model][k]:g}" for k, v in nom.items() if abs(v - models[model][k]) > 1e-9]
        report(f"NOM {ref} ({model})", not bad, "; ".join(bad) or "KG1 / MU match")
    kg1 = models["6P3S-E"]["KG1"]
    for p in ("KGA", "KGB"):
        v = mf.param(p)
        report(f"netlist {p}", v == kg1, f"{v:g} (6P3S-E KG1 {kg1:g})")


def check_baseline():
    print("baseline v1.5 against the README")
    op = mf.channel_op()
    ac = mf.ac_metrics()
    got = {
        "idle current per tube": op["ka"] * 1e3,
        "idle plate dissipation": (op["pa"] - op["ka"]) * op["ka"],
        "closed-loop gain": float(ac["gain"]),
        "-3 dB low": float(ac["flo"]),
        "-3 dB high": float(ac["fhi"]) / 1e3,
        "damping factor": float(ac["df"]),
        "THD at 10 W, 1 kHz": float(mf.thd_at_power(10.0)),
        "power at 1 % THD": float(mf.p_at_thd(1.0)),
    }
    for name, (want, tol, unit) in EXPECT.items():
        v = got[name]
        report(name, abs(v - want) <= tol, f"{v:.4g} {unit}  (README {want} +/- {tol})")


def check_stability():
    print(f"loop stability (pass: PM >= {PM_MIN:g} deg, GM >= {GM_MIN:g} dB)")
    for label, over in LOADS:
        _, pm, gm = mf.loop_margins(**over)
        report(label, pm >= PM_MIN and gm >= GM_MIN, f"PM {pm:.1f} deg, GM {gm:.1f} dB")


if __name__ == "__main__":
    check_schematic()
    check_netlists()
    check_model_sync()
    check_baseline()
    check_stability()
    if failures:
        sys.exit(f"\n{len(failures)} check(s) failed: " + ", ".join(failures))
    print("\nAll checks passed.")
