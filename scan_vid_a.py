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
MAX_CONSECUTIVE_ERRORS = 10
COPIES = int(os.environ.get("COPIES", 23))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 10))
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

        try:
            for vid in vender_ids:
                stats['total_scanned'] += 1
                if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                    log("达到时长上限，停止", "TIMER")
                    break

                page = context.new_page()
                stealth_sync(page)
                page.add_init_script("""
                    (() => {
                        // 1. 深度隐藏 WebDriver
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        
                        // 2. 模拟真实的 Chrome 环境（针对移动端可进一步伪造）
                        window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
                        
                        // 3. 语言与插件伪造
                        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]}); // 避免为空
                
                        // 4. 优化 Canvas 混淆：注入微小噪点而非直接破坏
                        // 直接返回“随机乱码”会导致图片格式损坏，被风控识别为非法篡改
                        const originalCanvasToDataURL = HTMLCanvasElement.prototype.toDataURL;
                        HTMLCanvasElement.prototype.toDataURL = function(type) {
                            if (type === 'image/png') {
                                const ctx = this.getContext('2d');
                                if (ctx) {
                                    // 在坐标 (1, 1) 绘制一个肉眼不可见但能改变特征值的像素
                                    ctx.fillStyle = 'rgba(255, 255, 255, 0.01)';
                                    ctx.fillRect(1, 1, 1, 1);
                                }
                            }
                            return originalCanvasToDataURL.apply(this, arguments);
                        };
                
                        // 5. 补充：WebGL 渲染器伪造（非常重要）
                        const getParameter = WebGLRenderingContext.prototype.getParameter;
                        WebGLRenderingContext.prototype.getParameter = function(parameter) {
                            // 伪装显卡信息为常见移动端/桌面端硬件
                            if (parameter === 37445) return 'Apple Inc.'; 
                            if (parameter === 37446) return 'Apple GPU';
                            return getParameter.apply(this, arguments);
                        };
                    })();
                """)

                try:
                    # ======== 访问店铺（完全按你给的版本） ========
                    #log(f"正在扫描店铺: {vid}", "INFO")
                    page.goto(
                        f"https://m.jd.com",
                        #f"https://shop.m.jd.com/shop/home?venderId={vid}",
                        wait_until="domcontentloaded",
                        timeout=20000
                    )
                    page.mouse.move(random.randint(0, 100), random.randint(0, 100))
                    # 模拟向下滚动一屏再向上滚动一点
                    page.mouse.wheel(0, random.randint(500, 800))
                    time.sleep(1)
                    page.mouse.wheel(0, -200)

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
                    # ============================================

                    if res_json and res_json.get("code") == "0":
                        stats["success"] += 1
                        
                        consecutive_errors = 0
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"{stats['total_scanned']}->🎯 命中店铺 {vid} | Token: {token}", "SUCCESS")
                            up_res = db_token.upload({"vid": vid, "token": token})
                            log(f"📡 同步结果: OK={up_res.get('ok')} | Http={up_res.get('code')} | Msg={up_res.get('body')}", "SYNC")
                        else:
                            log(f"{stats['total_scanned']}->店铺 {vid} 正常无活动", "INFO")
                    else:
                        stats["error"] += 1
                        
                        consecutive_errors += 1
                        log(f"{stats['total_scanned']}->店铺 {vid} 异常 code {res_json.get("code")}({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})", "WARN")
                        cooldown_sleep(consecutive_errors)

                except Exception as e:
                    consecutive_errors += 1
                    stats["error"] += 1
                    log(f"{stats['total_scanned']}->页面崩溃 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}", "WARN")
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        break
                    cooldown_sleep(consecutive_errors)

                finally:
                    page.close()
                    time.sleep(random.uniform(5, 8))

        finally:
            browser.close()
            log("任务结束，清理完成", "INFO")


if __name__ == "__main__":
    run_task()
