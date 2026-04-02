# JGB 報表匯出 API 系統

這是一個為了繞過 JGB 防火牆（Cloudflare WAF / Bot Protection）並自動化匯出帳單與合約報表所設計的 API 服務。此專案專為搭配 n8n 自動化流程使用。

## 部署與使用須知

* **基於 Zeabur 部署**：支援直接推送到 GitHub 後由 Zeabur 自動部署。
* **核心技術**：利用 `curl_cffi` 來完美模擬瀏覽器指紋（Chrome），藉此突破 JGB 的登入驗證。
* **處理流程**：
  1. API 接收請求後，於背景啟動 Session 登入 JGB。
  2. 根據所設定條件進行報表查詢與總數計算。
  3. 觸發 JGB 的批次匯出背景任務，並輪詢任務進度 (`/api2/getBatchStatus`)。
  4. 當匯出進度達 100% 時，攔截並回傳最終的 Excel 下載網址 `url`。
  5. 最終由 n8n 取代 API 本身直接下載該檔案，降低系統負擔並解決二進位傳輸問題。

---

## API 說明書

所有端點都會收到 JSON 格式的請求，並回傳匯出報表的下載網址。

### 1. 匯出帳單報表 (`/api/export-bills`)

* **方法**：`POST`
* **Content-Type**：`application/json`
* **說明**：根據篩選條件匯出【收款】或【支出】帳單。

**請求參數 (Request Body)**：
| 參數名稱 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- |
| `start_date` | `string` | 起始日期，格式 `YYYY/MM/DD` | 當月 1 號 |
| `end_date` | `string` | 結束日期，格式 `YYYY/MM/DD` | 當月最後 1 天 |
| `date_type` | `string` | 日期類型（`due_at` 應繳日、`ready_at` 出帳日、`all` 不限） | `"due_at"` |
| `bill_type` | `string` | 帳單類型（`income` 收款、`expense` 支出） | `"income"` |
| `statuses` | `array` | 狀態過濾條件 | 收款預設：`["unreceived", "progress", "received"]` <br> 支出預設：`["unpaid", "paid", "expired"]` |

**範例 Request Payload**：
```json
{
  "start_date": "2026/04/01",
  "end_date": "2026/04/30",
  "date_type": "due_at",
  "bill_type": "income"
}
```

---

### 2. 匯出合約報表 (`/api/export-contracts`)

* **方法**：`POST`
* **Content-Type**：`application/json`
* **說明**：根據日期與關鍵字條件匯出合約報表。

**請求參數 (Request Body)**：
| 參數名稱 | 類型 | 說明 | 預設值 |
| :--- | :--- | :--- | :--- |
| `start_date` | `string` | 起始日期，格式 `YYYY/MM/DD` | 當月 1 號 |
| `end_date` | `string` | 結束日期，格式 `YYYY/MM/DD` | 當月最後 1 天 |
| `date_type` | `string` | 日期類型（`start` 起始日、`end` 終止日、`finish_sign` 簽署完成日） | `"start"` |
| `keyword_for` | `string` | 關鍵字對象（`id` JGBID、`tenant` 租客、`estateName` 案名、`phone` 手機、`email` 信箱） | `"estateName"` |
| `keyword` | `string` | 查詢的關鍵字 | `""` |

**範例 Request Payload**：
```json
{
  "start_date": "2026/04/01",
  "end_date": "2026/04/03",
  "date_type": "finish_sign",
  "keyword_for": "tenant",
  "keyword": "76962"
}
```

---

## 成功回應 (Response)
當 API 執行成功並取得產生的報表時，會回傳：

```json
{
  "success": true,
  "data": {
    "url": "https://sg.jgbsmart.com/bills/exports/xxxxx-xxxx.xlsx",
    "filename": "20260402140000_合約報表匯出.xlsx"
  }
}
```
> 後續在 n8n 裡面，可以透過 HTTP Request 節點 GET `data.url` 來取得真實檔案。
