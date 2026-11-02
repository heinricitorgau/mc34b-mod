# PSUD2 電源模型 — psu_v1

這個資料夾放 PSUD2 的設計檔（`.psu`）。
同一個電源也寫成了 SPICE 版本 `simulations/ltspice/psu_v1.cir`，兩邊用**完全相同的數值**，可以互相對照。
`.psu` 檔需要在 PSUD2 中依下表輸入後存檔（檔名建議 `psu_v1.psu`），再 commit 進來。

## 電路

```
 110 V / 60 Hz ── PT (HT 315.5 Vrms, Rs 40 Ω) ── 矽橋 ──┬── 47 Ω ──┬── B+ ──► 左右聲道 (OPT 中心抽頭 + 各自的 RD1/RD2 退耦)
                                                        │          │
                                                    C1 220 µF   C2 470 µF
                                                    ESR 0.5 Ω   ESR 0.3 Ω
```

## PSUD2 輸入表

| PSUD2 元件 | 欄位 | 值 | 對應 `psu_v1.cir` |
|---|---|---|---|
| Transformer | Voltage (RMS) | 315.5 V | `VSEC` |
| | Source resistance | 40 Ω | `RSEC` |
| | Mains frequency | 60 Hz | `VHT` 頻率 |
| Rectifier | Type | 矽二極體全橋（1N4007 類） | `D1`–`D4`, `DPWR` |
| Capacitor (C1) | Value / Series R | 220 µF / 0.5 Ω | `CIN`, `ESR1` |
| Resistor | Value | 47 Ω | `RFIL` |
| Capacitor (C2) | Value / Series R | 470 µF / 0.3 Ω | `COUT`, `ESR2` |
| Load | Constant current | 158 mA（立體聲靜態） | `ILOAD` |
| Simulation | Duration | 3 s | `.tran` |

**要另外跑的情境**

| 情境 | PSUD2 改法 | `psu_v1.cir` 改法 |
|---|---|---|
| 兩聲道滿功率 | Load 改 300 mA | `ILOAD=0.30` |
| 空載（管子尚未導通） | Load 改 0 mA | `ILOAD=0` |
| 市電 −10 % / +10 % | Voltage 改 284 V / 347 V | `MAINS=0.9` / `1.1` |

## SPICE 版本的結果（ngspice，與 LTspice 相同網表）

| 市電 | 負載 | B+ (V) | B+ 漣波 (mV p-p) | C1 漣波 (V p-p) |
|---|---|---|---|---|
| 99 V | 0 mA | 400 | 35 | 0.04 |
| 99 V | 158 mA | 357 | 220 | 4.4 |
| 99 V | 300 mA | 331 | 392 | 7.7 |
| **110 V** | **158 mA** | **400** | **223** | **4.5** |
| 110 V | 0 mA | 444 | 38 | 0.05 |
| 110 V | 300 mA | 374 | 397 | 7.8 |
| 121 V | 0 mA | **489** | 41 | 0.05 |
| 121 V | 158 mA | 443 | 224 | 4.5 |
| 121 V | 300 mA | 416 | 401 | 7.9 |

- 校準條件：市電 110 V、立體聲靜態 158 mA 時，B+ = 400 V。
- 最高電壓出現在「市電 +10 %、空載」：**489 V**。C1、C2 的額定電壓應以此為下限。
- 用 PSUD2 跑出來的 B+ 與漣波若和上表差超過幾 %，通常是整流二極體模型或變壓器內阻的設定不同。

## 接到擴大機上（完整立體聲模擬）

`simulations/ltspice/amp_stereo_psu_v1.cir` 把這個電源接上兩個完整聲道（由 `tools/make_figures.py` 自動產生），結果見主 README §4.2。
