import os
import sys
import time
import json
import random
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from cf_db import CF_VID, CF_TOKEN

# 尝试导入 stealth
try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

# ================= 配置 =================
API_KEY = os.environ.get("API_KEY", "leaflow")
TARGET_PATTERN = os.environ.get("TARGET_PATTERN", "2PAAf74aG3D61qvfKUM5dxUssJQ9")
WORKER_VID_URL = os.environ.get("WORKER_VID_URL", "https://vid.zshyz.us.ci")
WORKER_TOKEN_URL = os.environ.get("WORKER_TOKEN_URL", "https://token.zshyz.us.ci")
RUN_DURATION_MINUTES = int(os.environ.get("RUN_DURATION_MINUTES", 10))
MAX_CONSECUTIVE_ERRORS = 3
COPIES = int(os.environ.get("COPIES", 23))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 10))
# =========================================

stats = {"success": 0, "hit": 0, "blocked": 0, "error": 0, "total_scanned": 0}

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STATS": "📊", "SYNC": "📡", "RAW": "📝"}
    print(f"[{timestamp}] {icons.get(level, '•')} {msg}", flush=True)

def split_and_get_my_part(data_list):
    file_name = os.path.splitext(os.path.basename(sys.argv[0]))[0]
    match = re.search(r'(\d+)$', file_name)
    script_idx = int(match.group(1)) if match else 0
    avg = len(data_list) / NUM_PARTS
    parts = [data_list[int(i * avg): int((i + 1) * avg)] for i in range(NUM_PARTS)]
    idx = (script_idx - 1) if script_idx > 0 else 0
    return parts[idx] if idx < len(parts) else []

# 🧠 冷却
def cooldown_sleep(streak):
    if streak == 1:
        t = random.uniform(8, 12)
    elif streak == 2:
        t = random.uniform(15, 25)
    else:
        t = random.uniform(25, 40)
    log(f"🧠 风控冷却 sleep {t:.1f}s", "WARN")
    time.sleep(t)

# 🔐 注入 JD 登录态
def inject_jd_cookie(context):
    pt_key = os.environ.get("JD_PT_KEY")
    pt_pin = os.environ.get("JD_PT_PIN")
    if not pt_key or not pt_pin:
        log("未配置 pt_key / pt_pin，使用匿名态")
        return
    context.add_cookies([
        {"name": "pt_key", "value": pt_key, "domain": ".jd.com", "path": "/", "httpOnly": True, "secure": True},
        {"name": "pt_pin", "value": pt_pin, "domain": ".jd.com", "path": "/", "httpOnly": True, "secure": True},
    ])
    log("🔐 已注入 pt_key / pt_pin", "SUCCESS")

def run_task():
    db_vid = CF_VID(WORKER_VID_URL, API_KEY)
    db_token = CF_TOKEN(WORKER_TOKEN_URL, API_KEY)

    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    log(f"⏰ 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} | 分片: {bj_now.hour}")

    result = db_vid.get_data_slice(copy=bj_now.hour, copies=COPIES)
    vender_ids = split_and_get_my_part(result.get("data", []))
    log(f"任务分配: 本脚本执行 {len(vender_ids)} 条", "INFO")
    if not vender_ids: return

    script_start_time = time.time()
    consecutive_errors = 0

    with sync_playwright() as p:
        # 优化 1：启动参数优化
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

        # 优化 2：深度伪造浏览器上下文
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={'width': 390, 'height': 844},
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai"
        )

        inject_jd_cookie(context)

        log("任务启动：已加载深度 Stealth 优化配置", "INFO")

        try:
            for vid in vender_ids:
                if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                    log("达到时长上限，停止", "TIMER")
                    break

                page = context.new_page()

                stealth_sync(page)
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
                """)

                try:
                    log(f"正在扫描店铺: {vid}", "INFO")
                    page.goto(f"https://shop.m.jd.com/shop/home?venderId={vid}",
                              wait_until="domcontentloaded",
                              timeout=20000)
                    time.sleep(random.uniform(1, 3))

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
                    res_json = page.evaluate(fetch_script)

                    if res_json and res_json.get("code") == "0":
                        stats["success"] += 1
                        stats["total_scanned"] += 1
                        consecutive_errors = 0
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"🎯 命中店铺 {vid} | Token: {token}", "SUCCESS")
                            up_res = db_token.upload({"vid": vid, "token": token})
                            log(f"📡 同步结果: OK={up_res.get('ok')} | Http={up_res.get('code')} | Msg={up_res.get('body')}", "SYNC")
                        else:
                            log(f"店铺 {vid} 正常无活动", "INFO")
                    else:
                        stats["error"] += 1
                        stats["total_scanned"] += 1
                        consecutive_errors += 1
                        error_msg = res_json.get('msg', '风控拦截')
                        log(f"店铺 {vid} 异常 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {error_msg}", "WARN")
                        cooldown_sleep(consecutive_errors)
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            log("连续报错 3 次，换 Context...", "ERROR")
                            context.close()
                            context = browser.new_context(
                                user_agent=random.choice([
                                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                                    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1"
                                ]),
                                viewport={'width': 390, 'height': 844},
                                device_scale_factor=3,
                                is_mobile=True,
                                has_touch=True,
                                locale="zh-CN",
                                timezone_id="Asia/Shanghai"
                            )
                            inject_jd_cookie(context)
                            consecutive_errors = 0

                except Exception as e:
                    consecutive_errors += 1
                    stats["error"] += 1
                    log(f"页面崩溃 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}", "WARN")
                    cooldown_sleep(consecutive_errors)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        context.close()
                        context = browser.new_context(
                            user_agent=random.choice([
                                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                                "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.7 Mobile/15E148 Safari/604.1"
                            ]),
                            viewport={'width': 390, 'height': 844},
                            device_scale_factor=3,
                            is_mobile=True,
                            has_touch=True,
                            locale="zh-CN",
                            timezone_id="Asia/Shanghai"
                        )
                        inject_jd_cookie(context)
                        consecutive_errors = 0

                finally:
                    page.close()
                    time.sleep(random.uniform(3, 7))

        finally:
            browser.close()
            log("任务结束，清理完成", "INFO")


if __name__ == "__main__":
    run_task()
