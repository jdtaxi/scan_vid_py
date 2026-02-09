import os
import json
import time
import re
import random
import math
import sys
from playwright.sync_api import sync_playwright
from cf_db import CF_vid,CF_TOKEN
# 尝试导入混淆库
try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

# ================= 配置区 =================
TARGET_PATTERN = "2PAAf74aG3D61qvfKUM5dxUssJQ9"
RUN_DURATION_MINUTES = 10     
MAX_CONSECUTIVE_ERRORS = 10    # 连续报错停止阈值
# =========================================

def log(msg, level="INFO"):
    timestamp = time.strftime("%H:%M:%S", time.localtime())
    icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "TIMER": "⏱️"}
    print(f"[{timestamp}] {icons.get(level, '•')} {msg}", flush=True)

def getdata(my_array):
    # 1. 获取当前脚本文件名（不含扩展名）
    file_name = os.path.splitext(os.path.basename(__file__))[0]
    
    # 2. 提取最后两位数字并转为整数
    # 假设文件名是 'script_05.py'，则 index 为 5
    try:
        index = int(file_name[-2:])
    except ValueError:
        raise ValueError("文件名末尾必须是两位数字，例如：data_process_02.py")
    
    # 3. 准备你的数据数组
    
    
    # 4. 将数组分成10份
    def split_array(data, num_parts):
        avg = len(data) / float(num_parts)
        out = []
        last = 0.0
    
        while last < len(data):
            out.append(data[int(last):int(last + avg)])
            last += avg
    
        return out
    
    parts = split_array(my_array, 10)
    
    # 5. 根据索引获取对应的部分
    # 注意：如果 index 是从 1 开始的（01-10），需要减 1
    current_part = parts[index] 
    
    print(f"当前脚本索引: {index}")
    print(f"获取到的数据片段长度: {len(current_part)}")
    print(f"片段内容: {current_part}")
    return current_part


def run_task():
    vender_ids = [];
    copies = 23;
    // 获取北京时间小时数
    // Cloudflare Worker 的 Date.now() 是 UTC 时间，+8 小时得到北京时间
    const bjTime = new Date(Date.now() + 8 * 60 * 60 * 1000);
    const copy = bjTime.getUTCHours(); // 获取 0-23 之间的小时数
    # 初始化
    cf_vid = CF_VID("https://vid.zshyz.us.ci", "leaflow")
    
    result = cf_vid.get_data_slice(copy=copy, copies=copies)
        
    data = result.get("data", [])
    print(f"正在处理第 {copy+1} 份数据，获取到 {len(data)} 条")
    vender_ids=getdata(my_array)
        

    script_start_time = time.time()
    consecutive_errors = 0 # 连续错误计数器
    
    with sync_playwright() as p:
        # 优化 1：启动参数优化，禁用自动化控制特征
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
        # 模拟 iPhone 13 Pro 的典型硬件指纹
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
                if (time.time() - script_start_time) / 60 >= RUN_DURATION_MINUTES:
                    log("达到时长上限，停止", "TIMER")
                    break

                page = context.new_page()
                
                # 优化 3：Stealth 注入优化
                stealth_sync(page)
                
                # 优化 4：额外注入 JavaScript 屏蔽 Webdriver 检测
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
                """)

                try:
                    log(f"正在扫描店铺: {vid}", "INFO")
                    # 降低加载压力
                    page.goto(f"https://shop.m.jd.com/shop/home?venderId={vid}", 
                              wait_until="domcontentloaded", # 只要 DOM 好了就执行，减少被 WAF 捕捉的时间
                              timeout=20000)
                    
                    # 模拟随机人类行为：停留 1-3 秒
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
                        # 成功响应，重置连续错误计数
                        consecutive_errors = 0
                        isv_url = res_json.get("result", {}).get("signStatus", {}).get("isvUrl", "")
                        if TARGET_PATTERN in isv_url:
                            token = re.search(r'token=([^&]+)', isv_url).group(1) if "token=" in isv_url else "N/A"
                            log(f"🎯 命中店铺 {vid} | Token: {token}", "SUCCESS")
                        else:
                            log(f"店铺 {vid} 正常无活动", "INFO")
                    else:
                        # 触发风控或接口错误
                        consecutive_errors += 1
                        error_msg = res_json.get('msg', '风控拦截')
                        log(f"店铺 {vid} 异常 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {error_msg}", "WARN")
                        
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            log("连续报错 10 次，判断当前 IP 已被京东封锁，程序自毁中...", "ERROR")
                            break

                except Exception as e:
                    consecutive_errors += 1
                    log(f"页面崩溃 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}", "WARN")
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        break
                finally:
                    page.close()
                
                # 随机冷却，保护 IP
                time.sleep(random.uniform(3, 7))

        finally:
            browser.close()
            log("任务结束，清理完成", "INFO")

if __name__ == "__main__":
    run_task()
