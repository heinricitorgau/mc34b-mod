* =====================================================================
*  elt10_est.inc  --  ESTIMATED impedance model of the ELAC ELT 10
*  (LTspice / ngspice).  NOT a measurement: no impedance curve or driver
*  data for the ELT 10 is published.  Built from the published specs:
*    2-way bass reflex, 2 x 165 mm woofers + 25 mm dome, crossover 2.7 kHz,
*    4 ohm nominal, 38 Hz - 25 kHz, cabinet 850 x 230 x 310 mm.
*  Assumptions (typical values, edit freely):
*    each woofer: 8 ohm class, Re 6.2, Le 0.5 mH, Bl 6.5, Mms 14 g,
*      Cms 1.0 mm/N (fs 42.5 Hz), Rms 1.2 kg/s, Sd 133 cm^2
*    box: Vb 38 L (net), port tuned fb = 40 Hz, Ql = 7, Qp = 50
*    tweeter: Re 4.7, Le 0.05 mH, fs 1.1 kHz (closed back)
*    crossover: 2nd-order at 2.7 kHz (woofer 0.47 mH / 7.5 uF,
*      tweeter 5.6 uF / 0.68 mH, tweeter in reverse polarity)
*  Woofers are modelled electro-mechano-acoustically (Bl coupling,
*  impedance analogy: force = V, velocity = I; pressure = V, U = I),
*  both sharing one box.
*  Pins: P (+), N (-)
* =====================================================================
.subckt WOOFER65 P N AB PARAMS: RE=6.2 LE=0.5m BL=6.5 MMS=14m CMS=1.0m RMS=1.2 SD=0.0133
RE  P e1 {RE}
LE  e1 e2 {LE}
VE  e2 e3 0
HB  e3 N VM {BL}
* mechanical loop: drive force = BL*i
HF  m1 0 VE {BL}
VM  m1 m2 0
LMS m2 m3 {MMS}
CMS m3 m4 {CMS}
RMS m4 m5 {RMS}
EBK m5 0 AB 0 {SD}
* volume velocity into the box
FU  0 AB VM {SD}
.ends WOOFER65

.subckt ELT10_EST P N PARAMS: VB=0.038 FB=40 QL=7 QP=50
.param RHOC2=1.42e5
.param CAB={VB/RHOC2}
.param MAP={1/((6.28319*FB)**2*CAB)}
* ---- crossover: woofer low-pass (2nd order)
LW1 P w1 0.47m
RLW w1 w2 0.25
CW1 w2 N 7.5u
XW1 w2 N AB WOOFER65
XW2 w2 N AB WOOFER65
* ---- box + port (acoustic node AB, ground = outside air)
CAB AB 0 {CAB}
LMP AB p1 {MAP}
RAP p1 0 {6.28319*FB*MAP/QP}
RAL AB 0 {QL/(6.28319*FB*CAB)}
* ---- tweeter high-pass (2nd order) + simple motional model
CT1 P t1 5.6u
LT1 t1 N 0.68m
RTW t1 t2 4.7
LTW t2 t3 0.05m
RTM t3 N 6
LTM t3 N 0.43m
CTM t3 N 48u
.ends ELT10_EST
