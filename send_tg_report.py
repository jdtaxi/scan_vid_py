import os
import requests
from datetime import datetime, timedelta, timezone
# 假设上面的 DataWorkerClient 代码保存在 cf_db.py 中
from cf_db import DataWorkerClient 

def send_tg_msg(text):
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        print("❌ 缺失 TG_BOT_TOKEN 或 TG_CHAT_ID")
        return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"📡 TG 发送状态: {res.status_code}")
    except Exception as e:
        print(f"❌ 发送异常: {e}")

def run_report():
    # 从变量读取配置
    API_KEY = os.environ.get("API_KEY", "leaflow")
    WORKER_TOKEN_URL = os.environ.get("WORKER_TOKEN_URL", "https://token.zshyz.us.ci")
    
    client = DataWorkerClient(WORKER_TOKEN_URL, API_KEY)
    
    # 1. 获取数据
    yesterday_data = client.get_yesterday_data()  # 昨天的
    today_data = client.get_today_data()          # 今天的（包含刚刚扫描出的）

    # 2. 解析数据 (假设接口返回结构是 {"data": [...]} 或 直接是列表)
    y_list = yesterday_data.get("data", []) if isinstance(yesterday_data, dict) else yesterday_data
    t_list = today_data.get("data", []) if isinstance(today_data, dict) else today_data
    
    y_count = len(y_list)
    t_count = len(t_list)
    
    # 获取当前北京时间
    bj_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    
    # 3. 构造消息
    msg = f"📊 *VID 扫描任务汇总报表*\n"
    msg += f"---"
    msg += f"\n⏰ *汇报时间*: `{bj_now.strftime('%H:%M:%S')}`"
    msg += f"\n📅 *昨日总计 (Token)*: `{y_count}`"
    msg += f"\n🔥 *今日累计 (Token)*: `{t_count}`"
    msg += f"\n📈 *今日增长*: `+{max(0, t_count)}`" # 这里逻辑可根据具体需求调整
    msg += f"\n---"
    msg += f"\n🚀 *20个分片扫描已全部执行完毕*"
    msg += f"\n💡 _数据实时同步至 Cloudflare Worker_"

    send_tg_msg(msg)

if __name__ == "__main__":
    run_report()
