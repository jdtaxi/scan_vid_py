import os, time, re, random
from playwright.sync_api import sync_playwright
from cf_db import CF_VID
from datetime import datetime, timedelta, timezone

# 尝试导入 Stealth
try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

# ================= 配置区 =================
WORKER_URL = "https://vid.zshyz.us.ci"
API_KEY = "leaflow"
TARGET_PATTERN = "2PAAf74aG3D61qvfKUM5dxUssJQ9"
RUN_DURATION_MINUTES = 10
MAX_CONSECUTIVE_ERRORS = 10
# =========================================

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","SUCCESS":"✅","ERROR":"❌","WARN":"⚠️","TIMER":"⏱️"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}", flush=True)

def split_and_get_my_part(data_list):
    """根据脚本文件名末尾数字获取自己的那一份数据 (10分法)"""
    file_name = os.path.splitext(os.path.basename(__file__))[0]
    try:
        # 获取文件名末尾两位数字
        script_idx = int(re.search(r'(\d{2})$', file_name).group(1))
    except:
        log("文件名须以两位数字结尾 (如 script_01.py)，默认使用索引 0", "WARN")
        script_idx = 0
    
    # 将小时数据切成 10 份给 10 个脚本并行
    num_parts = 10
    avg = len(data_list) / num_parts
    parts = [data_list[int(i * avg): int((i + 1) * avg)] for i in range(num_parts)]
    
    # 安全取值：如果是 01-10 对应 0-9 索引
    idx = (script_idx - 1) if script_idx > 0 else 0
    return parts[idx] if idx < len(parts) else []

def run_task():
    # 1. 初始化数据库并获取当前小时分片 (24分法)
    cf = CF_VID(WORKER_URL, API_KEY)
    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    current_hour = bj_now.hour
    
    log(f"正在获取北京时间 {current_hour} 点的数据分片...", "INFO")
    db_res = cf.get_data_slice(copy=current_hour, copies=24)
    hour_data = db_res.get("data", [])
    
    # 2. 二级切分给并行脚本
    vender_ids = split_and_get_my_part(hour_data)
    log(f"本脚本分配到 {len(vender_ids)} 条任务", "INFO")

    if not vender_ids: return

    start_time = time.time()
    errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            viewport={'width': 390, 'height': 844},
            is_mobile=True
        )

        for vid in vender_ids:
            if (time.time() - start_time) / 60 >= RUN_DURATION_MINUTES:
                log("时长达到上限，退出", "TIMER")
                break
            
            page = context.new_page()
            stealth_sync(page)
            
            try:
                log(f"扫描店铺: {vid}")
                page.goto(f"https://shop.m.jd.com/shop/home?venderId={vid}", wait_until="domcontentloaded", timeout=20000)
                time.sleep(random.uniform(1.5, 3))

                # 执行接口检查
                res_json = page.evaluate("""
                    async () => {
                        const res = await fetch("https://api.m.jd.com/client.action", {
                            "method": "POST",
                            "headers": { "content-type": "application/x-www-form-urlencoded" },
                            "body": "functionId=whx_getShopHomeActivityInfo&body=%7B%22venderId%22%3A%22""" + str(vid) + """%22%2C%22source%22%3A%22m-shop%22%7D&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5"
                        });
                        return await res.json();
                    }
                """)

                if res_json and res_json.get("code") == "0":
                    errors = 0
                    isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                    if TARGET_PATTERN in isv_url:
                        log(f"🎯 命中店铺 {vid}", "SUCCESS")
                else:
                    errors += 1
                    log(f"异常 ({errors}/{MAX_CONSECUTIVE_ERRORS})", "WARN")
                
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    log("连续异常过多，IP 可能被封", "ERROR")
                    break

            except Exception as e:
                log(f"错误: {e}", "WARN")
            finally:
                page.close()
            
            time.sleep(random.uniform(2, 4))

        browser.close()

if __name__ == "__main__":
    run_task()
