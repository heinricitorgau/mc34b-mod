# 待辦事項（模擬）

本 repo 的模擬工作清單。完成的項目移到「已完成」並註明結果在 README 的哪一節；新的工作加在「未完成」。

## 未完成

- [ ] **OPT 鐵心參數**：若取得 MC34-B 的鐵心尺寸、圈數或低頻功率規格，用它取代 §4.10 假設的飽和頻率與電感倍數，並考慮加入磁滯與鐵損。
- [ ] **PSUD2 檔案**：依 [`simulations/psud2/README.md`](simulations/psud2/README.md) 的輸入表在 PSUD2 輸入，存成 `simulations/psud2/psu_v1.psu`，並與 SPICE 版（`psu_v1.cir`）的 B+、漣波對照。需要在 Windows 上操作 PSUD2，無法在自動化環境完成。
- [ ] **ELT 10 實測阻抗**：取得實測阻抗曲線（自己量或廠商資料）後，擬合 `models/elt10_est.inc` 的 `PARAMS:`，再重跑 `python tools/make_figures.py fig16 fig17`。目前沒有公開資料（README §4.5）。
- [ ] **6P3S-E / 6P3P 多點擬合**：取得多個工作點的實測曲線後，分別擬合 μ、EX、KG1、KG2。目前只對 datasheet 一個工作點擬合 KG1 / KG2，6P3P 沒有獨立資料、與 6P3S-E 共用（README §4.9）。

## 已完成

- [x] 電源模型 psu_v1（SPICE），接上立體聲網表；B+ / B2 / B3、漣波、壓降、開機暫態（README §4.2）
- [x] 市電 ±10 % 敏感度，含偏壓是否隨市電變動（§4.2）
- [x] 偏壓電源模型：偏壓繞組、半波整流、CRC、每管分壓與可變電阻（§4.7）
- [x] B+ 360–440 V 敏感度：偏壓固定 vs 隨 B+ 變動（§4.3）
- [x] OPT 敏感度：初級阻抗、UL 抽頭、初級電感、耦合係數（§4.3）
- [x] 高頻補償 v1.3：階梯網路 3.3 k + 470 pF、Zobel 4.7 Ω + 100 nF（§4.3）
- [x] ELT 10 估計阻抗模型；v1.4 改為 Zobel 10 Ω + 470 nF、拿掉 1 nF 相位超前電容（§4.5）
- [x] 方波響應：10 kHz / 1 kHz / 40 Hz、阻性與容性負載（§4.4）
- [x] 迴路增益、相位裕度、增益裕度：Middlebrook 電壓注入，含 OPT 網格最壞情況（§4.4）
- [x] 管子離散敏感度：功率管配對、整體偏移、推動管、200 台蒙地卡羅（§4.6）
- [x] OPT 繞組分布電容；v1.5 加入屏對屏 RC 4.7 kΩ + 2.2 nF（§4.8）
- [x] 純電容負載穩定度：v1.4 / v1.5 / v1.5-C 比較，結論是需以頻寬換取，v1.5 以 ELT 10 為準（§4.8）
- [x] 6P3S-E 模型依 6P3S datasheet 工作點重新擬合 KG1 / KG2（§4.9）
- [x] OPT 鐵心飽和：可飽和鐵心 OPT 模型（`opt_sat.inc`），低頻最大功率、低頻失真、直流不平衡敏感度（§4.10）
- [x] LTspice 圖形化電路圖 `amp_channel_v1.asc`，由 `tools/make_schematic.py` 從網表產生並自動比對（README §6）
