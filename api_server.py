import os
import re
import time
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

# 引入 curl_cffi 來完美偽裝瀏覽器指紋，突破 JGB 防火牆
from curl_cffi import requests

load_dotenv()

app = FastAPI()

# 設定
BASE_URL = 'https://www.jgbsmart.com'
LOGIN_PAGE_URL = f'{BASE_URL}/users/login'
LOGIN_API_URL = f'{BASE_URL}/api2/login/emailLogin'
BILLS_EXPORT_API_URL = f'{BASE_URL}/api3/bills/export'
BATCH_CODE_API_URL = f'{BASE_URL}/api2/getBatchCode'
BATCH_STATUS_API_URL = f'{BASE_URL}/api2/getBatchStatus'

CREDENTIALS = {
    'email': os.getenv("JGB_EMAIL", "mis@oneplace.com.tw"),
    'password': os.getenv("JGB_PASSWORD", "oneplace1"),
    'country': 'TW',
    'phone': '',
    '_method': '',
    'remember': 'true',
    'role': 'landlord'
}

class ExportRequest(BaseModel):
    """帳單匯出的請求參數"""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_type: Optional[str] = "due_at"
    bill_type: Optional[str] = "income"
    statuses: Optional[List[str]] = None
    cycle: Optional[str] = ""
    payment_method: Optional[str] = ""
    item_fee_type: Optional[str] = ""

class ExportContractRequest(BaseModel):
    """合約匯出的請求參數"""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_type: Optional[str] = "start"
    keyword_for: Optional[str] = "estateName"

def get_browser_session():
    """取得具備 Chrome 特徵的 Session 以避開 WAF"""
    session = requests.Session(impersonate="chrome110")
    session.headers.update({
        'Accept': 'application/json, text/plain, */*',
        'Referer': BASE_URL
    })
    return session

def perform_login(session):
    """執行登入動作，回傳 token"""
    print(f"1. 取得登入頁面: {LOGIN_PAGE_URL}")
    try:
        response_page = session.get(LOGIN_PAGE_URL)
        response_page.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"取得登入頁面失敗: {str(e)}")

    match = re.search(r'<input\s+type="hidden"\s+name="_token"\s+value="([^"]+)"', response_page.text)
    token = match.group(1) if match else ""
    
    login_payload = CREDENTIALS.copy()
    login_payload['_token'] = token

    print("\n2. 登入中...")
    try:
        response_login = session.post(LOGIN_API_URL, data=login_payload)
        if not response_login.ok or '"success":true' not in response_login.text:
            raise HTTPException(status_code=401, detail=f"登入失敗: {response_login.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"登入錯誤: {str(e)}")
        
    return token

@app.post("/api/export-bills")
def export_bills(request: ExportRequest):
    """觸發 JGB 帳單報表匯出並回傳下載網址"""
    session = get_browser_session()
    token = perform_login(session)

    # --- 步驟 2：設定日期範圍 ---
    date_type = request.date_type if request.date_type else "due_at"
    
    if date_type in ["ready_at", "all", ""]:
        bill_period_query = "ready_at" if date_type == "ready_at" else ""
        bill_period_range = ["", ""]
        request.start_date = ""
        request.end_date = ""
    else:
        bill_period_query = date_type
        now = datetime.now()
        if not request.start_date:
            request.start_date = f"{now.year}/{now.month:02d}/01"
        if not request.end_date:
            import calendar
            last_day = calendar.monthrange(now.year, now.month)[1]
            request.end_date = f"{now.year}/{now.month:02d}/{last_day:02d}"
        bill_period_range = [request.start_date, request.end_date]

    if not request.statuses:
        if request.bill_type == "expense":
            request.statuses = ['unpaid', 'paid', 'expired']
        else:
            request.statuses = ['unreceived', 'progress', 'received']

    # --- 步驟 3：查詢帳單 ID ---
    print(f"\n3. 查詢帳單 ({request.start_date} ~ {request.end_date})...")

    query_params = {
        'billPeriodQuery': bill_period_query,
        'billPeriodRange[]': bill_period_range,
        'cycle': request.cycle or '',
        'item_fee_type': request.item_fee_type or '',
        'paymentMethod': request.payment_method or '',
        'status': '',
        'statuses[]': request.statuses,
        'type': request.bill_type or 'income'
    }

    try:
        response_bills = session.get(BILLS_EXPORT_API_URL, params=query_params)
        response_bills.raise_for_status()
        bills_data = response_bills.json()

        bill_ids = []
        if isinstance(bills_data, dict):
            ext = bills_data.get('data', {}).get('ext', {})
            bill_ids = ext.get('billIds', [])

        print(f"   找到 {len(bill_ids)} 筆帳單")

        if not bill_ids:
            return JSONResponse(content={
                "success": False,
                "message": "沒有帳單需要匯出",
                "debug": str(bills_data)[:500]
            })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查詢帳單錯誤: {str(e)}")

    # --- 步驟 4：觸發批次匯出 ---
    print("\n4. 觸發批次匯出...")
    now_str = datetime.now().strftime("%Y%m%d%H%M%S")
    type_label = "收款" if request.bill_type == "income" else "支出"
    file_name = f"{now_str}_{type_label}帳單報表匯出.xlsx"
    start_compact = request.start_date.replace("/", "") if request.start_date else ""
    end_compact = request.end_date.replace("/", "") if request.end_date else ""

    export_payload = {
        '_token': token,
        '_method': '',
        'job_name': 'bill_export',
        'ext[status]': '',
        'ext[item_fee_type]': request.item_fee_type or '',
        'ext[fileName]': file_name,
        'ext[roleId]': '22120',
        'ext[startDate]': start_compact,
        'ext[endDate]': end_compact,
        'ext[currency]': 'TWD',
        'ext[locale]': 'zh-TW',
        'ext[debugExport]': 'false',
    }

    for i, bill_id in enumerate(bill_ids):
        export_payload[f'ext[billIds][{i}]'] = str(bill_id)

    try:
        response_batch = session.post(BATCH_CODE_API_URL, data=export_payload)
        response_data = response_batch.json()

        if response_data.get('success'):
            batch_code = response_data['data']['batch_code']
            print(f"   batch_code: {batch_code}")
        else:
            raise HTTPException(status_code=500, detail=f"取得 batch_code 失敗: {response_data}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批次匯出錯誤: {str(e)}")

    # --- 步驟 5：輪詢狀態 ---
    print(f"\n5. 輪詢匯出狀態 (batch_code: {batch_code})...")
    file_url = None

    for _ in range(30):
        try:
            status_url = f"{BATCH_STATUS_API_URL}?batch_code={batch_code}"
            response_status = session.get(status_url)
            status_data = response_status.json()

            process = status_data.get('data', {}).get('process', 0)
            is_success = status_data.get('success')
            print(f"   進度: {process}%")

            if is_success and process == 100:
                file_url = status_data.get('data', {}).get('url')
                break

            time.sleep(2)
        except Exception as e:
            print(f"   輪詢錯誤: {str(e)}")
            time.sleep(2)

    if not file_url:
        raise HTTPException(status_code=504, detail="匯出逾時或取得下載連結失敗")

    # 改為直接回傳網址給 N8N，由 N8N 的 HTTP Request (帶 Fake User-Agent) 進行下載
    return JSONResponse(content={
        "success": True,
        "data": {
            "url": file_url,
            "filename": file_name
        }
    })

@app.post("/api/export-contracts")
def export_contracts(request: ExportContractRequest):
    """觸發 JGB 合約報表匯出並回傳下載網址"""
    session = get_browser_session()
    token = perform_login(session)

    # --- 步驟 2：設定日期範圍與類型 ---
    now = datetime.now()
    if not request.start_date:
        request.start_date = f"{now.year}/{now.month:02d}/01"
    if not request.end_date:
        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        request.end_date = f"{now.year}/{now.month:02d}/{last_day:02d}"

    date_type_map = {
        "start": "合約起始日",
        "end": "合約終止日",
        "finish_sign": "合約簽署完成日"
    }
    date_type = request.date_type if request.date_type in date_type_map else "start"

    # --- 步驟 2.5：先打 getList 取得總筆數 (total) ---
    print(f"\n[步驟2.5] 取得合約總筆數...")
    timestamp = int(time.time() * 1000)
    
    get_list_url = f"{BASE_URL}/api2/contract/list/getList/"
    list_params = {
        'contractPeriodQuery': date_type,
        'contractPeriodRange[]': [request.start_date, request.end_date],
        'keyword_for': request.keyword_for or 'estateName',
        'page': '1',
        'status': '',
        'timestamp': str(timestamp)
    }

    total_contracts = '150'
    try:
        response_list = session.get(get_list_url, params=list_params)
        response_list.raise_for_status()
        list_data = response_list.json()
        if list_data.get('success'):
            total_contracts = str(list_data.get('data', {}).get('total', total_contracts))
            print(f"   總筆數擷取成功: {total_contracts}")
        else:
            print(f"   總筆數擷取失敗，使用預設值: {total_contracts}")
    except Exception as e:
        print(f"   取得 getList 發生錯誤: {e}")

    # --- 步驟 3：觸發批次匯出 ---
    print(f"\n3. 觸發合約批次匯出 ({request.start_date} ~ {request.end_date})...")

    now_str = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"{now_str}_合約報表匯出.xlsx"

    export_payload = {
        '_token': token,
        '_method': '',
        'job_name': 'contract_export',
        'communityIds': 'all',
        'searchOptions[keyword_for]': request.keyword_for or 'estateName',
        'searchOptions[contractPeriodQuery]': date_type,
        'searchOptions[page]': '1',
        'searchOptions[contractPeriodRange][0]': request.start_date,
        'searchOptions[contractPeriodRange][1]': request.end_date,
        'searchOptions[contractIds]': 'all',
        'total': total_contracts,
        'ext[roleId]': '22120',
        'ext[userId]': '27454',
        'ext[fileName]': file_name,
        'ext[locale]': 'zh-TW',
        'ext[currency]': 'TWD',
        'ext[debugExport]': 'false',
    }

    try:
        response_batch = session.post(BATCH_CODE_API_URL, data=export_payload)
        response_data = response_batch.json()

        if response_data.get('success'):
            batch_code = response_data['data']['batch_code']
            print(f"   batch_code: {batch_code}")
        else:
            raise HTTPException(status_code=500, detail=f"取得 batch_code 失敗: {response_data}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批次匯出錯誤: {str(e)}")

    # --- 步驟 4：輪詢狀態 ---
    print(f"\n4. 輪詢匯出狀態 (batch_code: {batch_code})...")
    file_url = None

    for _ in range(30):
        try:
            status_url = f"{BATCH_STATUS_API_URL}?batch_code={batch_code}"
            response_status = session.get(status_url)
            status_data = response_status.json()

            process = status_data.get('data', {}).get('process', 0)
            is_success = status_data.get('success')
            print(f"   進度: {process}%")

            if is_success and process == 100:
                file_url = status_data.get('data', {}).get('url')
                break

            time.sleep(2)
        except Exception as e:
            print(f"   輪詢錯誤: {str(e)}")
            time.sleep(2)

    if not file_url:
        raise HTTPException(status_code=504, detail="匯出逾時或取得下載連結失敗")

    # 改為直接回傳網址給 N8N，由 N8N 的 HTTP Request 進行最終下載
    return JSONResponse(content={
        "success": True,
        "data": {
            "url": file_url,
            "filename": file_name
        }
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
