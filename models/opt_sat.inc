* =====================================================================
*  opt_sat.inc  --  push-pull UL output transformer with a saturable core
*  For the mc34b-mod simulations (LTspice / ngspice with ngbehavior=ltpsa).
*
*  Same windings, turns ratios, leakage and DCR as the linear coupled-
*  inductor OPT in amp_channel_v1.cir, but the core is a magnetic circuit:
*
*    every winding i :  v_i = n_i * dPhi/dt  + leakage L_i*(1-KC) + DCR
*    core MMF        :  F   = sum(n_i * i_i) + IDCX
*    core law        :  Phi = LSAT * x / (1 + |x|^PSH)^(1/PSH),
*                       x   = LMUL*LH*F / LSAT
*
*  Units: turns are relative to one half-primary (n = 1), so Phi is the
*  flux linkage of one half-primary (V*s) and F is in "half-primary amps".
*  Small-signal half-primary inductance = LMUL*LH; Phi saturates at LSAT.
*  A DC imbalance between the two output tubes (Ib - Ia) adds to F by
*  itself; IDCX injects an extra equivalent imbalance (A) for studies.
*  No hysteresis or core loss.  Large LSAT (e.g. 1e3) = linear core.
*
*  Pins: pa ula bp ulb pb out   (secondary returns to node 0)
*  Winding dots: pa, ula, bp, ulb (primary chain pa->pb) and node 0 on the
*  secondary, as in the linear model.
* =====================================================================
.SUBCKT OPT_SAT pa ula bp ulb pb out PARAMS: LH=10 TU=0.43 KC=0.9995 RAA=6k
+ LSAT=2.18 PSH=4 LMUL=1 IDCX=0
* ---- winding 1 : pa -> ula, n = 1-TU
E1 pa w1 VALUE={(1-TU)*V(dphi)}
V1 w1 x1 0
L1 x1 y1 {LH*(1-TU)*(1-TU)*(1-KC)}
R1 y1 ula 35
* ---- winding 2 : ula -> bp, n = TU
E2 ula w2 VALUE={TU*V(dphi)}
V2 w2 x2 0
L2 x2 y2 {LH*TU*TU*(1-KC)}
R2 y2 bp 25
* ---- winding 3 : bp -> ulb, n = TU
E3 bp w3 VALUE={TU*V(dphi)}
V3 w3 x3 0
L3 x3 y3 {LH*TU*TU*(1-KC)}
R3 y3 ulb 25
* ---- winding 4 : ulb -> pb, n = 1-TU
E4 ulb w4 VALUE={(1-TU)*V(dphi)}
V4 w4 x4 0
L4 x4 y4 {LH*(1-TU)*(1-TU)*(1-KC)}
R4 y4 pb 35
* ---- secondary : 0 -> out, n = 4/sqrt(RAA)  (4 ohm load -> RAA plate-plate)
E5 0 w5 VALUE={4/SQRT(RAA)*V(dphi)}
V5 w5 x5 0
L5 x5 y5 {16*LH/RAA*(1-KC)}
R5 y5 out 0.25
* ---- core: MMF -> flux linkage -> dPhi/dt
EF f 0 VALUE={(1-TU)*I(V1)+TU*I(V2)+TU*I(V3)+(1-TU)*I(V4)+4/SQRT(RAA)*I(V5)+IDCX}
EPHI phi 0 VALUE={LSAT*(LMUL*LH*V(f)/LSAT)/PWR(1+PWR(ABS(LMUL*LH*V(f)/LSAT),PSH),1/PSH)}
VD phi pd 0
CD pd 0 1
ED dphi 0 VALUE={I(VD)}
.ENDS OPT_SAT
