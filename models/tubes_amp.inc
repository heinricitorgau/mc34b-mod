* =====================================================================
*  tubes_amp.inc  --  Koren-type models for the mc34b-mod simulations
*  For LTspice (uses PWR / PWRS / PARAMS:).  v4  2026-11
*
*  Triode pins : A G K            Pentode/beam pins : A G2 G1 K
*
*  6N1 / 6N2 : parameters FITTED by me to datasheet typical points
*              (6N1P: 250V, Ug -4.5V, 7.5mA, S=4.35mA/V, mu=35
*               6N2P: 250V, Ug -1.5V, 1.8mA, S=2.1mA/V, mu=97.5)
*              Accurate around the class-A small-signal region;
*              less accurate near cutoff and at positive grid.
*  6P3S-E / 6P3P : Koren beam-tetrode form plus a plate slope term LAM;
*              v4: all parameters fitted to digitized datasheet curves,
*              separately for 6P3S-E and 6P3P (README 4.9).
*              Brand / sample spread: override KG1 per instance,
*              e.g.  X1 a g2 g1 k 6P3P KG1=1600   (higher KG1 = less Ia)
*  Inter-electrode capacitances are approximate.
*  v2: LOG(1+EXP(x)) rewritten as SOFTP(x)=MAX(x,0)+LOG(1+EXP(-ABS(x)))
*      (same math, no exp overflow / simulator exp-limiting).
*  v3: 6P3S-E / 6P3P KG1 1460 -> 1640, KG2 4500 -> 7500 (datasheet fit).
*  v4: 6P3S-E / 6P3P multi-point curve fits, separate parameters, LAM added.
* =====================================================================
.FUNC SOFTP(x) {MAX(x,0)+LOG(1+EXP(-ABS(x)))}

* ---------------- 6N1 (6N1P) : medium-mu twin triode, driver / LTP
.SUBCKT 6N1 A G K PARAMS: MU=35 EX=1.543 KG1=1202 KP=1042 KVB=300
+ RGI=2000 CCG=3.0P CGP=1.9P CCP=1.6P
E1 7 0 VALUE={V(A,K)/KP*SOFTP(KP*(1/MU+V(G,K)/SQRT(KVB+V(A,K)*V(A,K))))}
RE1 7 0 1G
G1 A K VALUE={(PWR(V(7),EX)+PWRS(V(7),EX))/KG1}
RCP A K 1G
C1 K G {CCG}
C2 G A {CGP}
C3 K A {CCP}
D3 5 K DX
R1 G 5 {RGI}
.MODEL DX D(IS=1N RS=1 CJO=10PF TT=1N)
.ENDS 6N1

* ---------------- 6N2 (6N2P) : high-mu twin triode, input stage
*  Similar to 12AX7 but ~1.5x hotter (lower ra ~42k vs ~62k).
.SUBCKT 6N2 A G K PARAMS: MU=97.5 EX=1.593 KG1=1414 KP=413 KVB=300
+ RGI=2000 CCG=2.3P CGP=1.6P CCP=0.9P
E1 7 0 VALUE={V(A,K)/KP*SOFTP(KP*(1/MU+V(G,K)/SQRT(KVB+V(A,K)*V(A,K))))}
RE1 7 0 1G
G1 A K VALUE={(PWR(V(7),EX)+PWRS(V(7),EX))/KG1}
RCP A K 1G
C1 K G {CCG}
C2 G A {CGP}
C3 K A {CCP}
D3 5 K DX
R1 G 5 {RGI}
.MODEL DX D(IS=1N RS=1 CJO=10PF TT=1N)
.ENDS 6N2

* ---------------- 6P3S-E (6П3С-Е, OTK) : 6L6 beam tetrode
*  Pins: A G2 G1 K.  Screen current clamped (fixes LOG of a negative
*  number in Koren's original when Vg1 < -Vg2/MU).
*  v4: MU EX KG1 KP KVB LAM fitted to 91 points digitized from the 6P3S /
*  6P3S-E datasheet curves (tools/fit_tubes.py, docs/data/tube_curves/);
*  KG2 from Ig2 = 5 mA at 250 V / 250 V / -14 V. rms error 9 %.
*  LAM: plate-voltage slope above the knee (not in Koren's form; 0 = off).
.SUBCKT 6P3S-E A G2 G1 K PARAMS: MU=10.33 EX=1.427 KG1=1698 KG2=5510
+ KP=30.21 KVB=22.38 LAM=4.366E-4 RGI=1000 CCG=11P CPG1=0.9P CCP=6.5P
E1 7 0 VALUE={MAX(V(G2,K),1M)/KP*SOFTP(KP*(1/MU+V(G1,K)/MAX(V(G2,K),1M)))}
RE1 7 0 1G
G1 A K VALUE={(PWR(V(7),EX)+PWRS(V(7),EX))/KG1*ATAN(V(A,K)/KVB)*(1+LAM*MAX(V(A,K),0))}
G2 G2 K VALUE={PWR(MAX(V(G2,K)/MU+V(G1,K),0),EX)/KG2}
RCP A K 1G
C1 G1 K {CCG}
C12 G1 A {CPG1}
C10 A K {CCP}
R1 G1 5 {RGI}
D1 5 K DX
.MODEL DX D(IS=1N RS=1 CJO=10PF TT=1N)
.ENDS 6P3S-E

* ---------------- 6P3P (Shuguang) : 6L6G-class beam tetrode
*  v4: fitted to 129 points digitized from the Chinese 6P3P handbook sheet
*  (r-type.org/pdfs/6p3p.pdf); KG2 from its Ig2 curve (about 10 mA at Ug1 = 0,
*  Ug2 = 250 V). rms error 10 %. Sweep KG1 / MU for sample spread.
.SUBCKT 6P3P A G2 G1 K PARAMS: MU=11.40 EX=1.194 KG1=766.2 KG2=3998
+ KP=37.16 KVB=18.71 LAM=7.263E-4 RGI=1000 CCG=11P CPG1=0.9P CCP=6.5P
E1 7 0 VALUE={MAX(V(G2,K),1M)/KP*SOFTP(KP*(1/MU+V(G1,K)/MAX(V(G2,K),1M)))}
RE1 7 0 1G
G1 A K VALUE={(PWR(V(7),EX)+PWRS(V(7),EX))/KG1*ATAN(V(A,K)/KVB)*(1+LAM*MAX(V(A,K),0))}
G2 G2 K VALUE={PWR(MAX(V(G2,K)/MU+V(G1,K),0),EX)/KG2}
RCP A K 1G
C1 G1 K {CCG}
C12 G1 A {CPG1}
C10 A K {CCP}
R1 G1 5 {RGI}
D1 5 K DX
.MODEL DX D(IS=1N RS=1 CJO=10PF TT=1N)
.ENDS 6P3P
