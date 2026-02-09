import os, time, re, random, sys
from playwright.sync_api import sync_playwright
from cf_db import CF_VID, CF_TOKEN
from datetime import datetime, timedelta, timezone

# 尝试导入 Stealth
try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

# ================= 配置区 (优先从环境变量读取) =================
# Secrets
API_KEY = os.environ.get("API_KEY", "leaflow")
TARGET_PATTERN = os.environ.get("TARGET_PATTERN", "2PAAf74aG3D61qvfKUM5dxUssJQ9")

# Variables
WORKER_VID_URL = os.environ.get("WORKER_VID_URL", "https://vid.zshyz.us.ci")
WORKER_TOKEN_URL = os.environ.get("WORKER_TOKEN_URL", "https://token.zshyz.us.ci")
RUN_DURATION_MINUTES = int(os.environ.get("RUN_DURATION_MINUTES", 10))
MAX_CONSECUTIVE_ERRORS = int(os.environ.get("MAX_CONSECUTIVE_ERRORS", 10))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 3))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 10))
COPIES = int(os.environ.get("COPIES", 24))
# ============================================================

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","SUCCESS":"✅","ERROR":"❌","WARN":"⚠️","TIMER":"⏱️"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}", flush=True)

def split_and_get_my_part(data_list):
    # GitHub Actions 中文件名通常固定，可以通过环境变量传 INDEX，或者解析文件名
    file_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    try:
        script_idx = int(re.search(r'(\d{2})$', file_name).group(1))
    except:
        script_idx = int(os.environ.get("SCRIPT_INDEX", 0))
    
    avg = len(data_list) / NUM_PARTS
    parts = [data_list[int(i * avg): int((i + 1) * avg)] for i in range(NUM_PARTS)]
    idx = (script_idx - 1) if script_idx > 0 else 0
    return parts[idx] if idx < len(parts) else []

def run_task():
    cf_vid = CF_VID(WORKER_VID_URL, API_KEY)
    cf_token = CF_TOKEN(WORKER_TOKEN_URL, API_KEY)
    
    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    current_hour = bj_now.hour
    
    log(f"当前北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"正在从 VID 库获取分片 (copy={current_hour}, copies={COPIES})...", "INFO")
    
    db_res = cf_vid.get_data_slice(copy=current_hour, copies=COPIES)
    hour_data = db_res.get("data", [])
    
    vender_ids = split_and_get_my_part(hour_data)
    log(f"本分片总任务数: {len(hour_data)} | 本脚本分配到: {len(vender_ids)} 条", "INFO")

    if not vender_ids:
        log("没有分配到任务，退出", "WARN")
        return

    start_time = time.time()
    consecutive_errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={'width': 390, 'height': 844},
            is_mobile=True
        )

        for vid in vender_ids:
            if (time.time() - start_time) / 60 >= RUN_DURATION_MINUTES:
                log("达到运行耗时限制，安全退出", "TIMER")
                break
            
            page_loaded = False
            for attempt in range(MAX_RETRIES):
                page = context.new_page()
                stealth_sync(page)
                try:
                    log(f"正在扫描: {vid} ({attempt+1}/{MAX_RETRIES})")
                    resp = page.goto(f"https://shop.m.jd.com/shop/home?venderId={vid}", 
                                   wait_until="domcontentloaded", timeout=20000)
                    if resp and resp.status < 400:
                        page_loaded = True
                        break
                except Exception as e:
                    log(f"页面加载失败: {str(e)[:30]}", "WARN")
                finally:
                    if not page_loaded: page.close()

            if not page_loaded:
                consecutive_errors += 1
                log(f"店铺 {vid} 多次加载失败，跳过", "ERROR")
                continue

            try:
                time.sleep(random.uniform(1, 2))
                res_json = page.evaluate("""
                    async () => {
                        try {
                            const res = await fetch("https://api.m.jd.com/client.action", {
                                "method": "POST",
                                "headers": { "content-type": "application/x-www-form-urlencoded" },
                                "body": "functionId=whx_getShopHomeActivityInfo&body=%7B%22venderId%22%3A%22""" + str(vid) + """%22%2C%22source%22%3A%22m-shop%22%7D&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5"
                            });
                            return await res.json();
                        } catch (e) { return { code: "-1", msg: e.toString() }; }
                    }
                """)

                code = res_json.get("code", "unknown")
                
                if code == "0":
                    consecutive_errors = 0
                    isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                    
                    if TARGET_PATTERN in isv_url:
                        token_match = re.search(r'token=([^&]+)', isv_url)
                        token = token_match.group(1) if token_match else "N/A"
                        log(f"🎯 命中! 店铺: {vid} | Code: {code} | Token: {token}", "SUCCESS")
                        
                        # 同步 Token 到云端数据库
                        if cf_token.upload({"vid": vid, "token": token, "type": "hit"}):
                            log("Token 已成功上传至云端", "SUCCESS")
                    else:
                        log(f"店铺: {vid} | Code: {code} | 未发现目标活动", "INFO")
                else:
                    consecutive_errors += 1
                    log(f"店铺: {vid} | Code: {code} | 接口返回异常", "WARN")
                
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    log("连续错误达到上限，可能触发风控，停止任务", "ERROR")
                    break

            except Exception as e:
                log(f"评估失败: {e}", "WARN")
            finally:
                page.close()
            
            time.sleep(random.uniform(1.5, 3))

        browser.close()

if __name__ == "__main__":
    run_task()
