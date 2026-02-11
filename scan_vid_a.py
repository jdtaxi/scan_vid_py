import os
import sys
import time
import json
import random
import requests
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from cf_db import CF_VID, CF_TOKEN, CF_MSG

# 尝试导入 stealth
try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

# ================= 配置 =================
API_KEY = os.environ.get("API_KEY", "leaflow")
TARGET_PATTERN = os.environ.get("TARGET_PATTERN", "2PAAf74aG3D61qvfKUM5dxUssJQ9")
WORKER_VID_URL = os.environ.get("WORKER_VID_URL", "https://vid.zshyz.us.ci")
WORKER_MSG_URL = os.environ.get("WORKER_MSG_URL", "https://msg.zshyz.us.ci")
WORKER_TOKEN_URL = os.environ.get("WORKER_TOKEN_URL", "https://token.zshyz.us.ci")
RUN_DURATION_MINUTES = int(os.environ.get("RUN_DURATION_MINUTES", 10))
MAX_CONSECUTIVE_ERRORS = int(os.environ.get("MAX_CONSECUTIVE_ERRORS", 10))
COPIES = int(os.environ.get("COPIES", 46))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 20))
REPO = int(os.environ.get("REPO", 1))
MAX_RETRY_ROUNDS = 3  # 失败重试次数上限
script_idx = 0
# =========================================

stats = {"success": 0, "hit": 0, "blocked": 0, "error": 0, 'total_scanned': 0}

def generate_device_profile():
    device_configs = {
        "iPhone 15/14/13 Pro": {"width": 390, "height": 844, "ratio": 3},
        "iPhone 15/14 Pro Max": {"width": 430, "height": 932, "ratio": 3},
        "Pixel 7": {"width": 412, "height": 915, "ratio": 2.6},
        "Samsung Galaxy S23": {"width": 360, "height": 800, "ratio": 3},
        "Xiaomi 13": {"width": 393, "height": 873, "ratio": 3}
    }
    device_name = random.choice(list(device_configs.keys()))
    config = device_configs[device_name]
    viewport = {"width": config["width"], "height": config["height"]}
    if "iPhone" in device_name:
        ua = f"Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    else:
        chrome_ver = f"{random.randint(140, 146)}.0.{random.randint(6000, 7000)}.100"
        ua = f"Mozilla/5.0 (Linux; Android 14; {device_name}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_ver} Mobile Safari/537.36"
    return {"device": device_name, "ua": ua, "viewport": viewport, "deviceScaleFactor": config["ratio"]}

profile = generate_device_profile()
device_scale_factor = profile['deviceScaleFactor']
Viewport = profile['viewport']
user_agent = profile['ua']

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STATS": "📊", "SYNC": "📡", "RAW": "📝","RISK": "🧠"}
    print(f"[{timestamp}] {icons.get(level, '•')} {msg}", flush=True)

def split_and_get_my_part(data_list):
    global script_idx
    file_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    match = re.search(r'(\d+)$', file_name)
    script_idx = int(match.group(1)) if match else 0
    if not data_list: return []
    avg = len(data_list) / NUM_PARTS
    parts = [data_list[int(i * avg): int((i + 1) * avg)] for i in range(NUM_PARTS)]
    idx = (script_idx - 1) if script_idx > 0 else 0
    return parts[idx] if idx < len(parts) else []
    
def get_halved_array(data_list, repo_val):
    length = len(data_list)
    mid = length // 2
    if repo_val == 1: return data_list[:mid]
    elif repo_val == 2: return data_list[mid:]
    else: raise ValueError("REPO 的值必须是 1 或 2")
        
def cooldown_sleep(streak):
    if streak == 1: t = random.uniform(4, 6)
    elif streak == 2: t = random.uniform(8, 12)
    else: t = random.uniform(14, 18)
    time.sleep(t)

def run_task(): 
    global RUN_DURATION_MINUTES
    db_vid = CF_VID(WORKER_VID_URL, API_KEY)
    db_msg = CF_MSG(WORKER_MSG_URL, API_KEY)
    db_token = CF_TOKEN(WORKER_TOKEN_URL, API_KEY)

    try:
        current_ip = requests.get('https://api.ipify.org', timeout=10).text
        log(f"任务启动 IP: {current_ip}", "INFO")
    except: pass

    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    slice_idx = bj_now.hour * 2 + (1 if bj_now.minute >= 30 else 0)
    log(f"⏰ 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} | 分片: {slice_idx}")

    result = db_vid.get_data_slice(copy=slice_idx, copies=COPIES)
    vender_ids = split_and_get_my_part(result.get("data", []))
    vender_ids = get_halved_array(vender_ids, REPO)
    log(f"任务分配: 本分片({slice_idx}-{REPO})执行 {len(vender_ids)} 条", "INFO")
    
    passed_min = (bj_now.minute - 30 if bj_now.minute >= 30 else bj_now.minute)
    RUN_DURATION_MINUTES = max(1, RUN_DURATION_MINUTES - passed_min)
    log(f"修正分钟数({passed_min})，将运行 {RUN_DURATION_MINUTES}分钟。", "INFO")

    if not vender_ids: return

    script_start_time = time.time()
    consecutive_errors = 0
    pending_vids = vender_ids

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-setuid-sandbox","--disable-infobars","--ignore-certificate-errors"])
        context = browser.new_context(user_agent=user_agent, viewport=Viewport, device_scale_factor=device_scale_factor, is_mobile=True, has_touch=True, locale="zh-CN", timezone_id="Asia/Shanghai")

        def scan_round(target_list, round_tag):
            nonlocal consecutive_errors
            round_failed = []
            for vid in target_list:
                stats['total_scanned'] += 1
                if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                    log(f"达到时长上限，停止{round_tag}", "TIMER")
                    return False, round_failed

                page = context.new_page()
                stealth_sync(page)
                page.add_init_script("""
                    (() => {
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
                        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                        const getParameter = WebGLRenderingContext.prototype.getParameter;
                        WebGLRenderingContext.prototype.getParameter = function(parameter) {
                            if (parameter === 37445) return 'Apple Inc.'; 
                            if (parameter === 37446) return 'Apple GPU';
                            return getParameter.apply(this, arguments);
                        };
                    })();
                """)

                try:
                    page.goto(f"https://m.jd.com", wait_until="domcontentloaded", timeout=20000)
                    time.sleep(random.uniform(1.5, 3))

                    # 核心修正：这里保持你最原始、最长的那一串 body 内容，不删减任何字符
                    # 仅在 vid 的位置使用变量插入，并对 JS 大括号进行双括号 {{ }} 转义
                    fetch_script = f"""
                    async () => {{
                        try {{
                            const res = await fetch("https://api.m.jd.com/client.action", {{
                                "method": "POST",
                                "headers": {{
                                    "accept": "*/*",
                                    "accept-language": "zh-CN,zh;q=0.9",
                                    "cache-control": "no-cache",
                                    "content-type": "application/x-www-form-urlencoded",
                                    "pragma": "no-cache",
                                    "priority": "u=1, i",
                                    "sec-ch-ua": "\\"Not:A-Brand\\";v=\\"99\\", \\"Google Chrome\\";v=\\"145\\", \\"Chromium\\";v=\\"145\\"",
                                    "sec-ch-ua-mobile": "?0",
                                    "sec-ch-ua-platform": "\\"Windows\\"",
                                    "sec-fetch-dest": "empty",
                                    "sec-fetch-mode": "cors",
                                    "sec-fetch-site": "same-site",
                                    "x-referer-page": "https://shop.m.jd.com/shop/home",
                                    "x-rp-client": "h5_1.0.0"
                                }},
                                "body": "functionId=whx_getShopHomeActivityInfo&body=%7B%22venderId%22%3A%22{vid}%22%2C%22source%22%3A%22m-shop%22%7D&t=1770819694395&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5&area=1_72_2799_0&screen=2880*1920&uuid=17708115052001228857295&xAPIClientLanguage=zh_CN&h5st=20260211222138060%3Bwz6mawii96hhwq34%3Bea491%3Btk03wb1e11c7e18ndJpbT6LBMcwGg2s88Liyt_M5n533NhyhltvDDrxKkqBrjNfNijd4G3MHR0d0UgAFHWppJHyOQxwM%3Be930fb87d5eb5abfe4161b2422f335444b7e75b6f1069563e9308813cf2d8b51%3B5.2%3B1770819695060%3BeVxhk4BZtVOFqAbHr9OH4EKJ0I_DqYfZnZfF7YfZB5hWvZeZnZ-G_U7ZBh-f1ZPIt9_VwNOV9c_I8I7Uv9OJwRLTtNuVrRbV-MuU8IrU7YfZnZfFbwrI-MrE-hfZXx-ZuVrJsRLT8IrVtJbT8MLU98uVwJ_IqdOV-QLU7MbIqV7ZB5_Zuc7EzcrJ-hfZXx-Zwt-ZB5_ZtN6J-hfZXx-Zop-VzN_ECMbG4IrKsB7ZB5_ZrYfZB5hW-1LEXwNHRgqFoZeM8Y6ZB5_Z0kbIzc7F-hfZXx-ZvV_G4E8ZB5_Z7g6ZBh-f1taZB5BZyI9ZB5_ZudOE-YfZBhfZXx-VB5_ZwdOE-YfZBhfZXxfUwh-T-hOVsY7ZBhfZB5hWptfZnZ-VwN6J-hfZBh-f1ZfP01rIOULVvVsU-YfZnZPGyQ7GAY6ZBhfZB5hWxh-T-BOE-YfZBhfZXxfVB5_ZqN6J-hfZBh-f1JeZnZ-UsY7ZBhfZB5hWxh-T-NOE-YfZBhfZXxfVB5_ZtN6J-hfZBh-f1ROUB5_ZuN6J-hfZBh-f1ZPUzd_WxZfZnZPVsY7ZBhfZB5hWxh-T-1rE-hfZBh-f1NeZnZvF1YfZBhfZXxfVB5_Z1YfZBhfZXxfVB5_Z9E6ZBhfZB5xDB5_Z9oLItAKI-hfZXxPCmg-T-haF-hfZXx-ZtJeDB1eUrpLHKgvTxpfVwhfMTgvFqkbIz8rM-h-T-dLEuYfZB5xD%3Ba8dc368de986532e861d0509f14ed7a2c4b16326d7bdebc6a766f1ab0c4b7513%3BgRaW989Gy8bE_oLE7w-Gy8rFvM7MtoLI4wrJ1R6G88bG_wPD9k7J1RLHxgKJ&x-api-eid-token=jdd03L7W7SYDWCH7IJBMJDER7RQDJZP3TJWTTUEQSTSXDFVS7IXP7ZIEHS4U3ECNYQXFDIQH72VCDGRIRK2JXPNOPMWIXGYAAAAM4JUJA67IAAAAACO5KDV4HC7ZGNQX",
                                "mode": "cors",
                                "credentials": "include"
                            }});
                            return await res.json();
                        }} catch (e) {{
                            return {{ code: "-1", msg: e.toString() }};
                        }}
                    }}
                    """
                    res_json = page.evaluate(fetch_script)

                    if res_json and str(res_json.get("code")) == "0":
                        stats["success"] += 1
                        consecutive_errors = 0
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"{round_tag}{stats['total_scanned']}->🎯 命中 {vid} | Token: {token}", "SUCCESS")
                            db_token.upload({"vender": vid, "token": token})
                            stats["hit"] += 1
                        else:
                            log(f"{round_tag}{stats['total_scanned']}->店铺 {vid} 正常", "INFO")
                    else:
                        stats["error"] += 1
                        consecutive_errors += 1
                        log(f"{round_tag}{stats['total_scanned']}->店铺 {vid} 异常 code {res_json.get('code') if res_json else 'None'}", "WARN")
                        round_failed.append(vid)
                        cooldown_sleep(consecutive_errors)
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS: return False, round_failed
                except Exception as e:
                    consecutive_errors += 1
                    stats["error"] += 1
                    log(f"{round_tag}{stats['total_scanned']}->异常 {vid}: {str(e)[:50]}", "WARN")
                    round_failed.append(vid)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS: return False, round_failed
                    cooldown_sleep(consecutive_errors)
                finally:
                    page.close()
                    time.sleep(random.uniform(4, 6))
            return True, round_failed

        for attempt in range(MAX_RETRY_ROUNDS + 1):
            if not pending_vids: break
            tag = "[初次]" if attempt == 0 else f"[重试{attempt}]"
            is_ok, failed_list = scan_round(pending_vids, tag)
            pending_vids = failed_list
            if not is_ok: break
        stats['blocked']=len(pending_vids);
        db_msg.upload({"idx": f"{REPO}.{script_idx}", "stats": stats})
        browser.close()

if __name__ == "__main__":
    run_task()
