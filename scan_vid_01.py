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
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 3))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 10))
COPIES = int(os.environ.get("COPIES", 24))
# =========================================

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "TIMER": "⏱️"}
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
    cf_vid = CF_VID(WORKER_VID_URL, API_KEY)
    cf_token = CF_TOKEN(WORKER_TOKEN_URL, API_KEY)

    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    current_hour = bj_now.hour
    log(f"⏰ 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} | 分片: {current_hour}")
    
    result = cf_vid.get_data_slice(copy=current_hour, copies=COPIES)
    hour_data = result.get("data", [])
    vender_ids = split_and_get_my_part(hour_data)
    log(f"任务分配: 小时总数 {len(hour_data)} -> 本脚本执行 {len(vender_ids)}", "INFO")

    if not vender_ids: return

    script_start_time = time.time()
    consecutive_errors = 0 
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-position=0,0",
                "--ignore-certificate-errors",
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={'width': 390, 'height': 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai"
        )

        log("任务启动：已加载深度 Stealth 优化配置", "INFO")

        for vid in vender_ids:
            if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                log("达到时长上限，停止", "TIMER")
                break

            success_fetched = False
            for attempt in range(MAX_RETRIES):
                page = context.new_page()
                stealth_sync(page)
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
                """)

                try:
                    log(f"正在扫描店铺: {vid} (尝试 {attempt+1}/{MAX_RETRIES})")
                    
                    # 降低等待强度，只要 DOM 加载了就进去
                    page.goto(f"https://shop.m.jd.com/shop/home?venderId={vid}", 
                             wait_until="domcontentloaded", timeout=20000)
                    
                    # ⚠️ 关键补丁：强制休眠 3 秒，避开页面初始跳转的高发期
                    time.sleep(3)

                    # 实时 URL 检查
                    curr_url = page.url
                    if "captcha" in curr_url or "login" in curr_url:
                        log(f"店铺 {vid} 已被重定向至验证页: {curr_url[:40]}...", "WARN")
                        break # 既然跳了，重试也没用，跳过该店

                    fetch_script = f"""
                    async () => {{
                        try {{
                            const res = await fetch("https://api.m.jd.com/client.action", {{
                                "method": "POST",
                                "headers": {{ "content-type": "application/x-www-form-urlencoded" }},
                                "body": "functionId=whx_getShopHomeActivityInfo&body=%7B%22venderId%22%3A%22{vid}%22%2C%22source%22%3A%22m-shop%22%7D&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5"
                            }});
                            return await res.json();
                        }} catch (e) {{
                            return {{ code: "-1", msg: e.toString() }};
                        }}
                    }}
                    """
                    # 执行评估，捕获潜在的跳转异常
                    res_json = page.evaluate(fetch_script)
                    
                    code = res_json.get("code", "unknown")
                    if code == "0":
                        consecutive_errors = 0
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"🎯 命中店铺 {vid} | Code: {code} | Token: {token}", "SUCCESS")
                            cf_token.upload({"vid": vid, "token": token, "type": "hit"})
                        else:
                            log(f"店铺 {vid} | Code: {code} | 正常无活动", "INFO")
                        success_fetched = True
                        break 
                    else:
                        log(f"店铺 {vid} | Code: {code} | 接口拦截", "WARN")
                
                except Exception as e:
                    if "destroyed" in str(e).lower() or "navigation" in str(e).lower():
                        log(f"⚠️ 页面跳转导致上下文失效，跳过该店铺", "WARN")
                        break # 不重试了，避免卡死
                    else:
                        log(f"❌ 运行错误: {str(e)[:50]}", "ERROR")
                finally:
                    page.close()

            if not success_fetched:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    log(f"连续错误已达上限 {MAX_CONSECUTIVE_ERRORS}，停止", "ERROR")
                    break
            
            time.sleep(random.uniform(2, 5))

        browser.close()
        log("任务结束", "INFO")

if __name__ == "__main__":
    run_task()
