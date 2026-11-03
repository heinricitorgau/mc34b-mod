#!/usr/bin/env python3
"""
make_schematic.py -- build an LTspice schematic (.asc) from amp_channel_v1.cir.

    python tools/make_schematic.py          # write .asc + .asy, then self-check

Every part is placed on a grid and every pin gets a net label (FLAG) with the
netlist node name, so LTspice connects the parts by name; no wires are drawn.
SPICE directives (.param, .include, K coupling, analyses) are placed as text.
Tube and speaker symbols (.asy) are written next to the schematic, where
LTspice looks for them.  After writing, the schematic is parsed back with the
same pin tables and compared element-by-element with the netlist.
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LTDIR = os.path.join(ROOT, "simulations", "ltspice")
CIR = os.path.join(LTDIR, "amp_channel_v1.cir")
ASC = os.path.join(LTDIR, "amp_channel_v1.asc")

# pin coordinates of LTspice's built-in symbols (orientation R0)
BUILTIN = {
    "res": [(16, 16), (16, 96)],
    "cap": [(16, 0), (16, 64)],
    "ind": [(16, 16), (16, 96)],
    "voltage": [(0, 16), (0, 96)],
}
# custom symbols written by this script: name -> [(pin name, x, y, label side)]
CUSTOM = {
    "mc34b_triode": [("A", 32, -64, "TOP"), ("G", -32, 0, "LEFT"), ("K", 32, 64, "BOTTOM")],
    "mc34b_pentode": [("A", 32, -64, "TOP"), ("G2", 96, -16, "RIGHT"), ("G1", -32, 16, "LEFT"), ("K", 32, 80, "BOTTOM")],
    "mc34b_speaker": [("P", 0, -48, "TOP"), ("N", 0, 48, "BOTTOM")],
}
TUBE_SYMBOL = {"6N1": "mc34b_triode", "6N2": "mc34b_triode", "6P3S-E": "mc34b_pentode",
               "6P3P": "mc34b_pentode", "ELT10_EST": "mc34b_speaker"}


def asy(name, pins, body):
    out = ["Version 4", "SymbolType CELL"] + body
    out += ["WINDOW 0 48 -40 Left 2", "WINDOW 3 48 40 Left 2", "SYMATTR Prefix X",
            f"SYMATTR Description {name} (mc34b-mod; subcircuit from models/*.inc)"]
    for i, (pn, x, y, side) in enumerate(pins, 1):
        off = 8
        out += [f"PIN {x} {y} {side} {off}", f"PINATTR PinName {pn}", f"PINATTR SpiceOrder {i}"]
    return "\n".join(out) + "\n"


def write_symbols():
    tri = ["CIRCLE Normal -16 -48 80 48", "LINE Normal 32 -64 32 -24", "LINE Normal 8 -24 56 -24",
           "LINE Normal -32 0 8 0", "LINE Normal 8 4 56 4", "LINE Normal 16 32 48 32", "LINE Normal 32 32 32 64"]
    pen = ["CIRCLE Normal -16 -56 80 72", "LINE Normal 32 -64 32 -32", "LINE Normal 8 -32 56 -32",
           "LINE Normal 8 -16 56 -16", "LINE Normal 56 -16 96 -16", "LINE Normal -32 16 8 16",
           "LINE Normal 8 16 56 16", "LINE Normal 16 48 48 48", "LINE Normal 32 48 32 80"]
    spk = ["RECTANGLE Normal -16 -24 16 24", "LINE Normal 16 -24 40 -48", "LINE Normal 40 -48 40 48",
           "LINE Normal 40 48 16 24", "LINE Normal 0 -48 0 -24", "LINE Normal 0 24 0 48"]
    for name, body in (("mc34b_triode", tri), ("mc34b_pentode", pen), ("mc34b_speaker", spk)):
        with open(os.path.join(LTDIR, name + ".asy"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(asy(name, CUSTOM[name], body))


def parse_netlist():
    txt = open(CIR, encoding="utf-8").read().replace("\r\n", "\n")
    elems, directives = [], []
    for line in txt.split("\n"):
        s = line.strip()
        if not s or s.startswith("*"):
            continue
        if s.lower() == ".end":
            break
        if s.startswith(".") or s[0].upper() == "K":
            directives.append(s)
            continue
        tok = s.split()
        kind = tok[0][0].upper()
        if kind in "RCL":
            elems.append(dict(name=tok[0], kind=kind, nodes=tok[1:3], value=" ".join(tok[3:])))
        elif kind == "V":
            val = " ".join(tok[3:])
            m = re.match(r"(.*?)\s+(AC\s+\S+)\s*$", val)
            elems.append(dict(name=tok[0], kind="V", nodes=tok[1:3], value=m.group(1) if m else val,
                              value2=m.group(2) if m else ""))
        elif kind == "X":
            sub = [t for t in tok[1:] if "=" not in t][-1]
            nn = len(CUSTOM[TUBE_SYMBOL[sub]])
            elems.append(dict(name=tok[0], kind="X", nodes=tok[1:1 + nn], value=sub,
                              spiceline=" ".join(t for t in tok[1 + nn:] if "=" in t)))
        else:
            sys.exit(f"unsupported element: {s}")
    return elems, directives


def build():
    elems, directives = parse_netlist()
    sym_of = {"R": "res", "C": "cap", "L": "ind", "V": "voltage"}
    out = ["Version 4", "SHEET 1 3200 2400"]
    cols, dx, dy = 12, 224, 288
    for i, e in enumerate(elems):
        x, y = 64 + (i % cols) * dx, 96 + (i // cols) * dy
        if e["kind"] == "X":
            sym = TUBE_SYMBOL[e["value"]]
            pins = [(px, py) for _, px, py, _ in CUSTOM[sym]]
        else:
            sym = sym_of[e["kind"]]
            pins = BUILTIN[sym]
        for (px, py), node in zip(pins, e["nodes"]):
            out.append(f"FLAG {x + px} {y + py} {node}")
        out.append(f"SYMBOL {sym} {x} {y} R0")
        out.append(f"SYMATTR InstName {e['name']}")
        out.append(f"SYMATTR Value {e['value']}")
        if e.get("value2"):
            out.append(f"SYMATTR Value2 {e['value2']}")
        if e.get("spiceline"):
            out.append(f"SYMATTR SpiceLine {e['spiceline']}")
    ty = 96 + ((len(elems) - 1) // cols + 1) * dy + 64
    out.append(f"TEXT 64 {ty - 48} Left 2 ;amp_channel_v1.asc -- GENERATED from amp_channel_v1.cir by tools/make_schematic.py. "
               "Parts connect through net labels. Edit the .cir and regenerate.")
    for j, d in enumerate(directives):
        out.append(f"TEXT {64 + (j % 2) * 1600} {ty + (j // 2) * 40} Left 2 !{d}")
    with open(ASC, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    return elems, directives


def check(elems, directives):
    """Re-derive every element's nodes from the .asc (flags at pin coordinates) and compare."""
    lines = open(ASC, encoding="utf-8").read().split("\n")
    flags = {}
    for l in lines:
        m = re.match(r"FLAG (-?\d+) (-?\d+) (\S+)", l)
        if m:
            flags[(int(m.group(1)), int(m.group(2)))] = m.group(3)
    parts, cur = [], None
    for l in lines:
        m = re.match(r"SYMBOL (\S+) (-?\d+) (-?\d+) R0", l)
        if m:
            cur = dict(sym=m.group(1), x=int(m.group(2)), y=int(m.group(3)))
            parts.append(cur)
        elif cur is not None and l.startswith("SYMATTR "):
            k, v = l[8:].split(" ", 1)
            cur[k] = v
    errors = 0
    for e, p in zip(elems, parts):
        pins = BUILTIN.get(p["sym"]) or [(px, py) for _, px, py, _ in CUSTOM[p["sym"]]]
        nodes = [flags.get((p["x"] + px, p["y"] + py)) for px, py in pins]
        if p["InstName"] != e["name"] or nodes != e["nodes"] or p["Value"] != e["value"]:
            errors += 1
            print("  MISMATCH", e, p, nodes)
    ndir = sum(1 for l in lines if l.startswith("TEXT") and " !" in l)
    print(f"  {len(elems)} parts, {len(flags)} net labels, {ndir} directives; {errors} mismatches")
    assert ndir == len(directives)
    return errors


if __name__ == "__main__":
    write_symbols()
    el, di = build()
    print("  wrote", os.path.relpath(ASC, ROOT), "+ mc34b_triode.asy, mc34b_pentode.asy, mc34b_speaker.asy")
    sys.exit(1 if check(el, di) else 0)
