# 安全政策

## 範圍

本專案是 SPICE 模擬與 Python 繪圖腳本，不是可部署的軟體服務。可能相關的安全問題例如：

- `tools/*.py` 處理網表或 CSV 時可能導致任意指令執行或寫入非預期路徑。
- repo 中意外提交的憑證或個人資訊。

模擬結果的正確性問題（模型誤差、數值錯誤）請直接開 [issue](https://github.com/heinricitorgau/mc34b-mod/issues/new/choose)，不屬於安全問題。

> 本專案只提供模擬，不提供任何實機製作或高壓安全指引；真空管電路涉及致命高壓，相關安全請另行參考專業資料。

## 支援版本

只維護 `main` 分支的最新版本。

## 回報方式

請**不要**以公開 issue 回報安全漏洞。請使用 GitHub 的
[Private vulnerability reporting](https://github.com/heinricitorgau/mc34b-mod/security/advisories/new)，
並說明：

- 問題描述與影響
- 重現步驟（相關檔案、指令）
- 可能的修正方式（若有）

維護者會盡量在 7 天內回覆，確認後修正並在 advisory 中致謝（除非你希望匿名）。
