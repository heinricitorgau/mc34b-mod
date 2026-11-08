# CLAUDE.md

給 Claude（與其他協作者）的工作說明。使用者以繁體中文溝通，TODO 與回覆用繁體中文；README 有英文（`README.md`）與繁體中文（`README.zh-TW.md`）兩版，內容要同步；程式碼、網表註解與圖表文字用英文。

## 專案性質

- **純模擬專案**：6P3S-E 推挽 UL、固定偏壓立體聲真空管擴大機（6N2 → 直耦 6N1 長尾對 → 2 × 6P3S-E），以 Ming-Da MC34-B 變壓器規格為假設，負載 ELAC ELT 10（4 Ω）。
- **不要加入任何實機製作內容**（零件採購、佈線、機箱、安全接線步驟、調機程序等）。結論一律寫成「模擬顯示……」，不是施工指示。
- 變壓器、OPT、喇叭的數值都是假設或估計，文件中要標明。

## 檔案與資料流

| 檔案 | 角色 | 可否手改 |
|---|---|---|
| `models/tubes_amp.inc` | 6N1 / 6N2 / 6P3S-E / 6P3P 的 Koren 型模型（LTspice 語法：`PWR`、`PWRS`、`PARAMS:`） | 可 |
| `models/elt10_est.inc` | ELT 10 估計阻抗模型 | 可 |
| `docs/data/tube_curves/*.csv` | datasheet 曲線數位化資料（`tools/fit_tubes.py` 的輸入） | 可（新增資料） |
| `models/opt_sat.inc` | 可飽和鐵心 OPT（§4.10）；與線性 OPT 相同繞組，只用在 `OPT="sat"` | 可 |
| `simulations/ltspice/amp_channel_v1.cir` | 單聲道網表，**唯一的電路來源**；所有可調值在 `.param` 區 | 可 |
| `simulations/ltspice/psu_v1.cir` | 電源（B+ 與偏壓）單獨模擬 | 可 |
| `simulations/ltspice/amp_stereo_psu_v1.cir` | 立體聲 + 電源 | **否**，由 `make_figures.py stereo` 產生 |
| `simulations/ltspice/amp_channel_v1_sat.cir` | 單聲道 + 可飽和鐵心 OPT | **否**，由 `make_figures.py sat` / `fig21` 產生 |
| `simulations/ltspice/amp_channel_v1.asc`、`mc34b_*.asy` | LTspice 圖形化電路圖 | **否**，由 `make_schematic.py` 產生 |
| `docs/figures/*.png`、`docs/data/*.csv` | 圖表與數據 | **否**，由 `make_figures.py` 產生 |
| `README.md`、`README.zh-TW.md` | 設計說明與所有模擬結果（英文 / 繁體中文，兩版行對行對應，改一版就要改另一版） | 可 |
| `TODO.md` | 待辦事項（README 不放待辦） | 可 |

`tools/make_figures.py` 讀取 `amp_channel_v1.cir` 的電路區段，用 regex 覆寫 `.param`，再附加 ngspice 分析指令；它會在暫存目錄寫 `.spiceinit`（`set ngbehavior=ltpsa`），讓 ngspice 接受 LTspice 語法。

## 修改電路的流程

1. 改 `amp_channel_v1.cir`（或模型、`psu_v1.cir`）。新增可調值時用 `.param`，並沿用慣例：`1p` 代表電容「不加」，`1e9` 代表電阻「拿掉」（例：`RPZ=1e9` 即 v1.4）。
2. `python tools/make_schematic.py`：重新產生 `.asc`，輸出必須是 `0 mismatches`。
3. `python tools/make_figures.py`（全部，約 1–2 小時）或 `python tools/make_figures.py fig4 fig14`（部分）。立體聲相關的圖（8、9、10、19）每張要數分鐘到數十分鐘。
4. 依 `docs/data/*.csv` 與腳本印出的數值更新兩版 README 的表格與文字；**數字一定要從 CSV / 輸出讀，不要估**。改版時在對應章節加一段「> **v1.x（日期）**：……」說明改了什麼、為什麼。
5. 更新 `TODO.md`。

改功率管模型時：`python tools/fit_tubes.py` 擬合後把參數寫回 `tubes_amp.inc`，同時更新 `amp_channel_v1.cir` 的 `KGA` / `KGB`（實例用 `KG1={KGA}` 覆寫模型預設值）與 `make_figures.py` 的 `NOM`、圖 9 / 18 / 19 的 KG1 數值。

變更偏壓相關的東西（管子模型、`VB`、分壓電阻）後，要重新調整：單聲道 `VB`（`trim_bias()`，目標每管 34.4 mA），以及立體聲的可變電阻位置 `WA` / `WB`（在 `make_figures.py` 的 `build_stereo()` 中）。

## 設計基準（v1.5）

- B+ 400 V（理想）；偏壓 −42.9 V（單聲道）／可變電阻 0.598、約 −43.0 V（立體聲）；每管 34.4 mA、13.7 W。管子模型 v4（datasheet 多點擬合）。
- 高頻補償：6N2 屏極階梯 3.3 kΩ + 470 pF、迴授 2.7 kΩ ∥ 100 pF、Zobel 10 Ω + 1 µF、屏對屏 RC 4.7 kΩ + 2.2 nF。
- 穩定度要在 OPT 參數網格（`RAA` 4–8 k、`TU` 0.2–0.55、`LH` 5–10、`KC` 0.999–0.9998，共 120 組）的最壞情況下檢查，並包含 4 Ω、ELT 10（`SPK=1 RL=1e6`）、不接負載；繞組電容典型值 `CPP=300p CPS=1n`。及格線：相位裕度 ≥ 20°、增益裕度 ≥ 3 dB。

## ngspice 注意事項

- 40 Hz 方波用 20 ns 邊緣會讓 6N2 模型時間步長卡住；低於 1 kHz 用 1 µs 邊緣（`square()` 已處理）。
- 冷機開機暫態要 `.options method=gear` 並拿掉 `.ic`。
- 機器只有 2 顆 CPU；長時間掃描用 `ThreadPoolExecutor(2)`，背景執行並設足夠的 timeout。
- 停止背景 Python 時不要用會比對到自己 shell 指令的 `pkill -f`。
- 在使用者電腦上跑時，每個指令最長約 3 分鐘、背景程序會被結束：設 `MF_CACHE=<資料夾>` 後重複執行同一個指令，每次接著做（結果依網表快取）。那台電腦沒有系統安裝的 ngspice，用的是解開在 `$HOME/ngs` 的 ngspice 36（`PATH` 與 `SPICE_LIB_DIR` 要指過去）。

## Git

- Commit 訊息類型：`feat(sim)`、`fix(model)`、`docs(fig)`、`docs`、`chore`（見 README §7）。
- Repo 在 Windows / OneDrive 上，`core.autocrlf=true`，文字檔在工作目錄是 CRLF。
- 自動化環境沒有 GitHub 帳密：commit 在本機完成，`git push` 由使用者執行。
