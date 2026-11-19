# mc34b-mod — 執行模擬

[English](USAGE.md) · **繁體中文** · [← 回到 README](../README.zh-TW.md)

目錄結構、如何執行各個網表與重新產生圖表，以及 commit 慣例。設計與模擬結果在 [DESIGN.zh-TW.md](DESIGN.zh-TW.md)。

---

## 5. 目錄結構

```
mc34b-mod/
├── .github/                issue 範本與 PR 範本；workflows/ci.yml（CI）
├── assets/                 README 橫幅
├── models/                 SPICE 模型 (tubes_amp.inc)、ELT 10 估計模型 (elt10_est.inc)、
│                           可飽和鐵心 OPT (opt_sat.inc)
├── simulations/
│   ├── ltspice/            amp_channel_v1.cir（單聲道）、psu_v1.cir（電源）、
│   │                       amp_stereo_psu_v1.cir（自動產生，勿手改）、curves_*.cir、
│   │                       amp_channel_v1.asc + mc34b_*.asy（圖形化電路圖，自動產生）、
│   │                       amp_channel_v1_sat.cir（可飽和鐵心版，自動產生）
│   └── psud2/              PSUD2 輸入表 (README.md) 與 .psu 檔
├── docs/
│   ├── DESIGN.md           設計與所有模擬結果（中文版 DESIGN.zh-TW.md）
│   ├── USAGE.md            執行模擬（中文版 USAGE.zh-TW.md，即本檔）
│   ├── figures/            模擬圖表（tools/make_figures.py 產生）
│   └── data/               掃描結果 CSV（與圖同時產生）；tube_curves/ 是 datasheet 曲線數位化資料
├── tools/                  make_figures.py（重新產生 docs/figures）、make_schematic.py（產生 .asc）、
│                           fit_tubes.py（功率管 datasheet 擬合）、ci_check.py（CI 執行的回歸檢查）
├── README.md               概覽與主要結果（英文）
├── README.zh-TW.md         繁體中文版
├── CITATION.cff            引用資訊（「Cite this repository」）
├── TODO.md                 待辦事項
├── CLAUDE.md               給 Claude / 協作者的工作說明
├── CONTRIBUTING.md         貢獻指南
├── CODE_OF_CONDUCT.md      行為準則
├── SECURITY.md             安全政策
├── LICENSE
└── .gitignore
```

## 6. 如何執行模擬

1. 用 LTspice 開啟 `simulations/ltspice/amp_channel_v1.cir`（File → Open，檔案類型選 All Files），按 **Run**。
2. 波形視窗加入 `V(out)`；THD 與功率結果在 **View → SPICE Error Log**。
3. 參數都集中在網表上方的 `.param` 區塊；可用 `.step param VB list -38 -42 -46` 掃描偏壓，或 `.step param KC list 0.998 0.9995` 掃描 OPT 耦合係數。
4. 要看直流工作點，在 `.tran` 前加 `.op`。屏耗 = V(pa) × V(ka)（RKO = 1 Ω，V(ka) 的數值即陰極電流）。
5. `curves_*.cir` 用來畫各管的屏極特性曲線，檢查模型是否合理。
6. `psu_v1.cir`：電源單獨模擬（B+ 用定電流負載，與 PSUD2 相同；偏壓匯流排接等效電阻 `RBLOAD`）。改 `ILOAD`、`MAINS` 看不同情境。
7. `amp_stereo_psu_v1.cir`：電源 + 兩個聲道。它由 `python tools/make_figures.py stereo` 從前兩個檔案產生，要改電路請改來源檔再重新產生。冷機開機模擬請加 `.options method=gear`，並拿掉 `.ic` 行。
8. 功率管不匹配：`amp_channel_v1.cir` 中的 `KGA`、`KGB` 分別是兩支功率管的 KG1；`DVB` 是 V4 相對 V3 的偏壓差（逐管調偏壓）。其他管子的參數可在實例後面加，例如 `X1 v1a ing v1k 6N2 KG1=1600 MU=95`。
9. 敏感度：`VBPLUS`、`RAA`、`TU`、`LH`、`KC` 都在 `amp_channel_v1.cir` 的 `.param` 中，可用 `.step param RAA list 5k 6k 6.6k` 這類語法掃描。
10. 只重畫敏感度圖（不重跑模擬）：`python tools/make_figures.py plot11 plot12`。
11. 負載：`RL` 是電阻負載（`1e6` = 不接），容性負載可在網表加一行 `CLD out 0 2u`。迴路增益的量法見 `tools/make_figures.py` 的 `loop_gain()`。
12. 接 ELT 10 估計模型：`.param SPK=1` 並把 `RL` 設成 `1e6`。喇叭參數在 `models/elt10_est.inc` 的註解與 `PARAMS:` 中，可自行修改。
13. OPT 繞組電容：`CPP`（屏對屏）、`CPS`（初次級，平均分到兩端）；預設 1 pF = 不加。例：`.param CPP=300p CPS=1n`。屏對屏 RC 是 `RPZ`、`CPZ`（`RPZ=1e9` = 拿掉，即 v1.4）。
14. 圖形化電路圖：LTspice 開啟 `simulations/ltspice/amp_channel_v1.asc`（同資料夾的 `mc34b_*.asy` 是管子與喇叭的符號）。每個接腳都用網路標籤（net label）連到網表的節點名稱，所以畫面上沒有導線，但電路與 `.cir` 完全相同。它由 `python tools/make_schematic.py` 從 `.cir` 產生，並會自動反向比對每個元件的節點；改電路請改 `.cir` 再重新產生。

15. OPT 鐵心飽和：`amp_channel_v1_sat.cir`，或在腳本中用 `channel(OPT="sat", LSAT=..., LMUL=..., IDCX=...)`（§4.10）。長時間的掃描可設環境變數 `MF_CACHE=<資料夾>`，把每次 ngspice 的結果存起來，中斷後重跑會跳過已完成的部分。

16. 功率管擬合：`python tools/fit_tubes.py` 會讀 `docs/data/tube_curves/*.csv`、擬合、印出參數並與 ngspice 的子電路核對，再畫圖 22（需要 scipy）。擬合結果要手動寫回 `models/tubes_amp.inc` 的 `PARAMS:`，並重新調整偏壓（`VB`、`WA` / `WB`）。

**檢查基準**（約 30 秒，CI 執行的就是這個）：`python tools/ci_check.py` 會重新產生電路圖、用 ngspice 執行每個網表，確認複製到網表（`KGA` / `KGB`）與 `make_figures.py`（`NOM`）的管子常數仍與 `models/tubes_amp.inc` 一致，並重新量測主要數字與迴路穩定裕度，與 README 所列的數值比對。

**重新產生圖表**（需要 [ngspice](https://ngspice.sourceforge.io/) 與 Python 的 numpy、matplotlib）：

```powershell
pip install numpy matplotlib
python tools/make_figures.py            # 全部
python tools/make_figures.py fig4 fig5  # 只更新部分
python tools/make_schematic.py          # 重新產生 LTspice 電路圖
```

## 7. Commit 慣例

```
feat(sim):    新增 / 修改模擬
fix(model):   修正 SPICE 模型
docs(fig):    更新圖表
docs:         更新說明文件（README、TODO、CLAUDE.md）
chore:        目錄、設定等雜項
```
