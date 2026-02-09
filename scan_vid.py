import os
import json
import time
import re
import random
import sys
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from cf_db import CF_VID, CF_TOKEN

# 尝试导入混淆库
try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

# ================= 配置区 =================
API_KEY = os.environ.get("API_KEY", "leaflow")
TARGET_PATTERN = os.environ.get("TARGET_PATTERN", "2PAAf74aG3D61qvfKUM5dxUssJQ9")
WORKER_VID_URL = os.environ.get("WORKER_VID_URL", "https://vid.zshyz.us.ci")
WORKER_TOKEN_URL = os.environ.get("WORKER_TOKEN_URL", "https://token.zshyz.us.ci")
RUN_DURATION_MINUTES = int(os.environ.get("RUN_DURATION_MINUTES", 10))
MAX_CONSECUTIVE_ERRORS = int(os.environ.get("MAX_CONSECUTIVE_ERRORS", 10))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 2))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 10))
COPIES = int(os.environ.get("COPIES", 24))
# =========================================

stats = {"success": 0, "jump": 0, "hit": 0, "error": 0, "total_scanned": 0}
last_nav_url = "unknown" # 用于追踪最后一次跳转地址

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STATS": "📊"}
    print(f"[{timestamp}] {icons.get(level, '•')} {msg}", flush=True)

def split_and_get_my_part(data_list):
    file_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    match = re.search(r'(\d+)$', file_name)
    script_idx = int(match.group(1)) if match else 0
    avg = len(data_list) / NUM_PARTS
    parts = [data_list[int(i * avg): int((i + 1) * avg)] for i in range(NUM_PARTS)]
    idx = (script_idx - 1) if script_idx > 0 else 0
    return parts[idx] if idx < len(parts) else []

def run_task():
    db_vid = CF_VID(WORKER_VID_URL, API_KEY)
    db_token = CF_TOKEN(WORKER_TOKEN_URL, API_KEY)

    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    current_hour = bj_now.hour
    log(f"⏰ 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} | 分片: {current_hour}")
    
    result = db_vid.get_data_slice(copy=current_hour, copies=COPIES)
    vender_ids = split_and_get_my_part(result.get("data", []))
    log(f"任务分配: 本脚本执行 {len(vender_ids)} 条", "INFO")

    if not vender_ids: return

    script_start_time = time.time()
    consecutive_errors = 0 
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled","--no-sandbox","--ignore-certificate-errors"])
        context = browser.new_context(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")

        for vid in vender_ids:
            if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                log("达到时长上限，停止", "INFO")
                break

            success_fetched = False
            for attempt in range(MAX_RETRIES):
                page = context.new_page()
                stealth_sync(page)
                
                # 实时追踪跳转地址
                def handle_nav(frame):
                    global last_nav_url
                    last_nav_url = frame.url
                page.on("framenavigated", handle_nav)

                try:
                    # 步骤简化：直接跳转
                    page.goto(f"https://shop.m.jd.com/shop/home?venderId={vid}", wait_until="domcontentloaded", timeout=15000)
                    time.sleep(3) # 等待跳转稳定

                    fetch_script = f"""
                    async () => {{
                        const res = await fetch("https://api.m.jd.com/client.action", {{
                            "method": "POST",
                            "headers": {{ "content-type": "application/x-www-form-urlencoded" }},
                            "body": "functionId=whx_getShopHomeActivityInfo&body=%7B%22venderId%22%3A%22{vid}%22%2C%22source%22%3A%22m-shop%22%7D&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5"
                        }});
                        return await res.json();
                    }}
                    """
                    res_json = page.evaluate(fetch_script)
                    code = res_json.get("code", "unknown")

                    if code == "0":
                        stats["success"] += 1
                        consecutive_errors = 0
                        success_fetched = True
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"🎯 命中店铺 {vid} | Token: {token}", "SUCCESS")
                            stats["hit"] += 1
                            db_token.upload({"vid": vid, "token": token, "type": "hit"})
                        break 
                    else:
                        stats["error"] += 1
                        consecutive_errors += 1
                        break

                except Exception as e:
                    if "destroyed" in str(e).lower():
                        log(f"⚠️ 店铺 {vid} 跳转干扰 -> 目标页: {last_nav_url}", "WARN")
                        stats["jump"] += 1
                        break
                finally:
                    page.close()

            # 实时汇总逻辑：每 10 个打印一次
            stats["total_scanned"] += 1
            if stats["total_scanned"] % 10 == 0:
                log(f"📊 阶段汇总({stats['total_scanned']}): [成功:{stats['success']}] [跳转:{stats['jump']}] [命中:{stats['hit']}] [异常:{stats['error']}]", "STATS")

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log(f"连续错误达 {MAX_CONSECUTIVE_ERRORS} 次，停止", "ERROR")
                break
            
            time.sleep(random.uniform(0.5, 1.5))

        browser.close()
        log("任务结束", "INFO")

if __name__ == "__main__":
    run_task()
