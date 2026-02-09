import os
import json
import time
import re
import random
import sys
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from cf_db import CF_VID, CF_TOKEN

# ================= 配置区 =================
API_KEY = os.environ.get("API_KEY", "leaflow")
TARGET_PATTERN = os.environ.get("TARGET_PATTERN", "2PAAf74aG3D61qvfKUM5dxUssJQ9")
WORKER_VID_URL = os.environ.get("WORKER_VID_URL", "https://vid.zshyz.us.ci")
WORKER_TOKEN_URL = os.environ.get("WORKER_TOKEN_URL", "https://token.zshyz.us.ci")
RUN_DURATION_MINUTES = int(os.environ.get("RUN_DURATION_MINUTES", 10))
MAX_CONSECUTIVE_ERRORS = int(os.environ.get("MAX_CONSECUTIVE_ERRORS", 20))
NUM_PARTS = int(os.environ.get("NUM_PARTS", 10))
COPIES = int(os.environ.get("COPIES", 24))
# =========================================

stats = {"success": 0, "hit": 0, "blocked": 0, "error": 0, "total_scanned": 0}

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STATS": "📊", "SYNC": "📡"}
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
    log(f"⏰ 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')} | 分片: {bj_now.hour}")
    
    result = db_vid.get_data_slice(copy=bj_now.hour, copies=COPIES)
    vender_ids = split_and_get_my_part(result.get("data", []))
    log(f"任务分配: 本脚本执行 {len(vender_ids)} 条", "INFO")

    if not vender_ids: return

    script_start_time = time.time()
    consecutive_errors = 0 
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        )
        page = context.new_page()

        # 资源拦截逻辑：极致省流
        page.route("**/*", lambda route: 
            route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] 
            else route.continue_()
        )

        # 伪造空白页占坑
        page.route("**/empty.html", lambda route: 
            route.fulfill(status=200, body="<html><body></body></html>")
        )
        
        try:
            log("初始化极速扫描环境...", "INFO")
            page.goto("https://shop.m.jd.com/empty.html", wait_until="commit", timeout=10000)
        except Exception as e:
            log(f"环境初始化失败: {e}", "ERROR")
            return

        for vid in vender_ids:
            if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                log("达到时长上限，停止", "INFO")
                break

            try:
                # 核心 Fetch 逻辑
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
                code = str(res_json.get("code", "unknown"))

                # 打印每一个 VID 的返回码
                if code == "0":
                    stats["success"] += 1
                    consecutive_errors = 0
                    isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                    
                    if TARGET_PATTERN in isv_url:
                        token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                        log(f"🎯 命中 {vid} | Code: {code} | Token: {token[:8]}...", "SUCCESS")
                        stats["hit"] += 1
                        
                        # 同步数据库并打印响应
                        up_res = db_token.upload({"vid": vid, "token": token, "type": "hit"})
                        log(f"📡 同步结果: OK={up_res.get('ok')} | Http={up_res.get('code')} | Msg={up_res.get('body')[:30]}", "SYNC")
                    else:
                        # 只有在扫描间隔较长时建议开启此行打印，否则日志会非常多
                        # log(f"店铺 {vid} | Code: {code} | 正常无活动", "INFO")
                        pass
                else:
                    if code == "3":
                        stats["blocked"] += 1
                        log(f"⚠️ 店铺 {vid} | Code: {code} (IP被拦截)", "WARN")
                    else:
                        stats["error"] += 1
                        log(f"❌ 店铺 {vid} | Code: {code} (其他异常)", "ERROR")
                    consecutive_errors += 1

            except Exception as e:
                log(f"评测异常 {vid}: {str(e)[:50]}", "ERROR")
                consecutive_errors += 1

            # 统计汇总
            stats["total_scanned"] += 1
            if stats["total_scanned"] % 10 == 0:
                log(f"📊 阶段汇总({stats['total_scanned']}): 成功:{stats['success']} | 命中:{stats['hit']} | 拦截(Code3):{stats['blocked']} | 异常:{stats['error']}", "STATS")

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log(f"连续报错 {MAX_CONSECUTIVE_ERRORS} 次，判定 IP 暂时失效", "ERROR")
                break
            
            # 极速模式下建议保留 0.5s 左右的间隔
            time.sleep(random.uniform(6, 8))

        browser.close()
        log(f"任务结束。总计扫描: {stats['total_scanned']} | 命中总数: {stats['hit']}", "INFO")

if __name__ == "__main__":
    run_task()
