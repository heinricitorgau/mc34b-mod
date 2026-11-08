## 摘要

<!-- 改了什麼、為什麼 -->

## 類型

- [ ] `feat(sim)` 新增 / 修改模擬
- [ ] `fix(model)` 修正 SPICE 模型
- [ ] `docs(fig)` 更新圖表
- [ ] `docs` 更新說明文件
- [ ] `chore` 雜項

## 影響的圖與數據

<!-- 例：fig4、fig14、docs/data/xxx.csv -->

## 檢查清單

- [ ] 只手改「可手改」的檔案；產生的檔案由腳本重新產生
- [ ] `python tools/make_schematic.py` 輸出 `0 mismatches`（有改電路時）
- [ ] 受影響的圖已用 `tools/make_figures.py` 重新產生
- [ ] README 的數字從 CSV / 腳本輸出讀取，並加上 `> **v1.x（日期）**` 說明（有改版時）
- [ ] 穩定度在 OPT 參數網格最壞情況下仍符合 PM ≥ 20°、GM ≥ 3 dB（有改高頻補償 / OPT 時）
- [ ] `TODO.md` 已更新
- [ ] 不含實機製作內容；假設或估計的數值已標明
