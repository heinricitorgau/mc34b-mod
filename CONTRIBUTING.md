# 貢獻指南

感謝你對本專案有興趣！請先讀這份指南與 [行為準則](CODE_OF_CONDUCT.md)。

## 專案範圍

這是**純模擬專案**：6P3S-E 推挽 UL、固定偏壓立體聲真空管擴大機的 SPICE 模擬（ngspice / LTspice）。

- 歡迎：模型修正、模擬方法改進、新的分析、datasheet 曲線數位化資料、文件錯誤修正。
- **不收**：任何實機製作內容（零件採購、佈線、機箱、安全接線步驟、調機程序等）。結論一律寫成「模擬顯示……」。
- 變壓器、OPT、喇叭的數值都是假設或估計，新增內容時請標明。

## 語言

- README 有英文（`README.md`）與繁體中文（`README.zh-TW.md`）兩版，改動時兩版都要更新。
- TODO、issue 與 PR 討論：繁體中文（英文也可以）。
- 程式碼、網表註解、圖表文字：英文。

## 環境

- Python 3（`numpy`、`matplotlib` 等，見 `tools/` 內各腳本的 import）
- ngspice（36 以上）；LTspice 可選，用來開 `.asc` 電路圖

執行方式見 [README §6](README.zh-TW.md#6-如何執行模擬)。

## 修改電路的流程

1. 只改「可手改」的檔案（見下表）。新增可調值用 `.param`，沿用慣例：`1p` 代表電容「不加」、`1e9` 代表電阻「拿掉」。
2. `python tools/make_schematic.py`，輸出必須是 `0 mismatches`。
3. `python tools/make_figures.py <圖編號…>` 重新產生受影響的圖與 CSV。
4. 依 `docs/data/*.csv` 與腳本輸出更新兩版 README；**數字一定要從 CSV / 輸出讀，不要估**。改版時在對應章節加一段「> **v1.x（日期）**：……」。
5. 更新 `TODO.md`。

| 可手改 | 由腳本產生（請勿手改） |
|---|---|
| `models/*.inc`、`simulations/ltspice/amp_channel_v1.cir`、`psu_v1.cir`、`docs/data/tube_curves/*.csv`、`README.md`、`README.zh-TW.md`、`TODO.md` | `amp_stereo_psu_v1.cir`、`amp_channel_v1_sat.cir`、`*.asc`、`*.asy`、`docs/figures/*.png`、`docs/data/*.csv` |

改到高頻補償或 OPT 相關參數時，請在 README 所述的 OPT 參數網格最壞情況下確認穩定度（相位裕度 ≥ 20°、增益裕度 ≥ 3 dB）。

## Commit 訊息

沿用 [README §7](README.zh-TW.md#7-commit-慣例) 的類型：

```
feat(sim)  fix(model)  docs(fig)  docs  chore
```

## Pull request

1. Fork 後從 `main` 開分支。
2. 一個 PR 處理一件事；說明改了什麼、為什麼、影響哪些圖與數據。
3. 填寫 PR 範本中的檢查清單。

## 回報問題

請用 [issue 範本](https://github.com/heinricitorgau/mc34b-mod/issues/new/choose)。附上 ngspice 版本、作業系統、執行的指令與錯誤輸出，會讓問題更快被釐清。
