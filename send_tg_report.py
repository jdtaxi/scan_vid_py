import os
import requests
import time
from datetime import datetime, timedelta, timezone

def send_tg_msg(text):
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        print("❌ 缺失 TG 配置")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
        print("✅ TG 消息已发送")
    except Exception as e:
        print(f"❌ 发送失败: {e}")

def get_summary():
    api_key = os.environ.get("API_KEY")
    worker_url = os.environ.get("WORKER_TOKEN_URL") # 假设你的 db 有查询接口
    
    # 这里逻辑取决于你的 CF Worker 接口
    # 如果接口支持获取最新命中列表，可以直接调用
    # 示例演示：获取最近生成的数量
    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    
    msg = f"🔔 *VID 扫描任务汇总*\n"
    msg += f"📅 时间: `{bj_now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
    msg += f"---"
    
    # 建议在 CF Worker 侧写一个汇总统计接口
    # 如果没有接口，可以发送简单的任务完成通知
    msg += f"\n✅ 所有分片(20个)扫描流程已完成。"
    msg += f"\n📊 请前往数据库查看最新 Token 命中情况。"
    
    return msg

if __name__ == "__main__":
    report_content = get_summary()
    send_tg_msg(report_content)
