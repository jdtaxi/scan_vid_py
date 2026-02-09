import os
import sys
import time
import json
import random
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from cf_db import CF_VID, CF_TOKEN
from ip2free_fetcher import get_all_proxies
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
MAX_CONSECUTIVE_ERRORS = 10
COPIES = int(os.environ.get("COPIES", 46))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 20))
# =========================================

stats = {"success": 0, "hit": 0, "blocked": 0, "error": 0, 'total_scanned': 0}

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

def cooldown_sleep(streak):
    if streak == 1:
        t = random.uniform(8, 12)
    elif streak == 2:
        t = random.uniform(15, 25)
    else:
        t = random.uniform(25, 40)
    log(f"🧠 风控冷却 sleep {t:.1f}s", "WARN")
    time.sleep(t)

def run_task():
    # 获取所有账号的代理
    proxy_data = get_all_proxies()
    
    for account in proxy_data:
        print(f"账号: {account['email']} | 状态: {account['msg']}")
        print(f"无限代理数量: {len(account['unlimited'])}")
        # 打印具体的代理
        for p in account['unlimited']:
            print(f"可用代理: {p}")
        
    db_vid = CF_VID(WORKER_VID_URL, API_KEY)
    db_token = CF_TOKEN(WORKER_TOKEN_URL, API_KEY)

    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    log(f"⏰ 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} | 分片: {bj_now.hour}")

    result = db_vid.get_data_slice(copy=bj_now.hour, copies=COPIES)
    vender_ids = split_and_get_my_part(result.get("data", []))
    log(f"任务分配: 本脚本执行 {len(vender_ids)} 条", "INFO")
    if not vender_ids:
        return

    script_start_time = time.time()
    consecutive_errors = 0
    failed_vids = []  # 用于存放需要重试的 vid

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

        def scan_vids(target_list, is_retry=False):
            nonlocal consecutive_errors
            tag = "[重试]" if is_retry else ""
            
            for vid in target_list:
                stats['total_scanned'] += 1
                if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                    log(f"达到时长上限，停止{tag}", "TIMER")
                    return False # 结束整个函数

                page = context.new_page()
                stealth_sync(page)
                page.add_init_script("""
                    (() => {
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
                        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                        const originalCanvasToDataURL = HTMLCanvasElement.prototype.toDataURL;
                        HTMLCanvasElement.prototype.toDataURL = function(type) {
                            if (type === 'image/png') {
                                const ctx = this.getContext('2d');
                                if (ctx) {
                                    ctx.fillStyle = 'rgba(255, 255, 255, 0.01)';
                                    ctx.fillRect(1, 1, 1, 1);
                                }
                            }
                            return originalCanvasToDataURL.apply(this, arguments);
                        };
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
                    page.mouse.move(random.randint(0, 100), random.randint(0, 100))
                    page.mouse.wheel(0, random.randint(500, 800))
                    time.sleep(random.uniform(1.5, 3))

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
                        consecutive_errors = 0
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"{tag}{stats['total_scanned']}->🎯 命中 {vid} | Token: {token}", "SUCCESS")
                            db_token.upload({"vid": vid, "token": token})
                        else:
                            log(f"{tag}{stats['total_scanned']}->店铺 {vid} 正常", "INFO")
                    else:
                        stats["error"] += 1
                        consecutive_errors += 1
                        log(f"{tag}{stats['total_scanned']}->店铺 {vid} 异常 code {res_json.get('code')}", "WARN")
                        if not is_retry: failed_vids.append(vid) # 仅在初次扫描时加入重试队列
                        cooldown_sleep(consecutive_errors)
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS: return False

                except Exception as e:
                    consecutive_errors += 1
                    stats["error"] += 1
                    log(f"{tag}{stats['total_scanned']}->页面崩溃 {vid}: {e}", "WARN")
                    if not is_retry: failed_vids.append(vid)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS: return False
                    cooldown_sleep(consecutive_errors)
                finally:
                    page.close()
                    time.sleep(random.uniform(4, 7))
            return True

        # --- 执行初次扫描 ---
        should_continue = scan_vids(vender_ids, is_retry=False)

        # --- 执行重试扫描 (如果初次扫描因风控中断或有失败记录) ---
        if failed_vids and should_continue:
            log(f"🔄 开始重试第初次扫描失败的 {len(failed_vids)} 条数据...", "STATS")
            time.sleep(10) # 重试前多休息一会
            scan_vids(failed_vids, is_retry=True)

        log("任务结束，清理完成", "INFO")
        browser.close()

if __name__ == "__main__":
    run_task()
