import requests
import json
from datetime import datetime, timedelta, timezone
from typing import List, Any, Dict, Optional

class CF_VID:
    def __init__(self, base_url: str, api_key: str):
        """
        初始化数据库连接
        :param base_url: Worker 的 URL (例如 https://name.workers.dev)
        :param api_key: 校验密钥
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        # 使用 Session 自动处理连接池，提高性能
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def get_data_slice(self, start: int, copies: int) -> Dict[str, Any]:
        """
        获取数据库分片数据
        :param start: 数组起始位置
        :param copies: 分成几份 (决定获取的长度)
        :return: 包含 info 和 data 的字典
        """
        url = f"{self.base_url}/get"
        payload = {
            "start": start,
            "copies": copies
        }

        try:
            response = self.session.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"请求失败: {e}")
            return {"error": str(e), "data": []}


class CF_TOKEN:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": api_key
        }
        # 定义北京时区 (UTC+8)
        self.beijing_tz = timezone(timedelta(hours=8))
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _get_bj_now(self):
        """无论系统时区是什么，始终返回当前的北京时间对象"""
        return datetime.now(timezone.utc).astimezone(self.beijing_tz)

    def _format_date(self, dt_obj):
        """格式化为 MM_DD"""
        return dt_obj.strftime("%m_%d")

    def upload(self, data):
        """上传数据"""
        url = f"{self.base_url}/upload"
        try:
            response = self.session.post(url, data=json.dumps(data), timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Upload Error: {e}")
            return False

    def get_today_data(self):
        """获取北京时间的今天数据"""
        date_str = self._format_date(self._get_bj_now())
        return self._fetch(date_str)

    def get_yesterday_data(self):
        """获取北京时间的昨天数据"""
        yesterday_obj = self._get_bj_now() - timedelta(days=1)
        date_str = self._format_date(yesterday_obj)
        return self._fetch(date_str)

    def _fetch(self, date_str):
        """底层请求函数"""
        url = f"{self.base_url}/get"
        try:
            print(f"🔍 正在查询北京时间 {date_str} 的数据...")
            response = self.session.get(url, params={"date": date_str}, timeout=10)
            return response.json() if response.status_code == 200 else []
        except Exception as e:
            print(f"Get Error: {e}")
            return []

# --- 调用演示 ---
if __name__ == "__main__":
    worker = CF_TOKEN("https://token.zshyz.us.ci", "leaflow")
    
    # 获取昨天数据
    yesterday = worker.get_yesterday_data()
    print(f"昨天数据: {yesterday}")
    
    # 上传并获取今天
    worker.upload({"vid": 8999, "token": "cstoken"})
    today = worker.get_today_data()
    print(f"今天数据: {today}")

# --- 使用示例 ---
    # 配置信息
    WORKER_URL = "https://your-worker.workers.dev"
    SECRET_KEY = "my-secret-key"

    # 1. 初始化
    db = CF_VID(WORKER_URL, SECRET_KEY)

    # 2. 调用函数：从 0 开始，取总数的 1/10
    result = db.get_data_slice(start=0, copies=10)

    if "error" not in result:
        info = result.get("info", {})
        data = result.get("data", [])
        
        print(f"--- 数据获取成功 ---")
        print(f"数据库总条数: {info.get('total_in_db')}")
        print(f"本次切片长度: {info.get('chunk_size')}")
        print(f"获取到的条数: {len(data)}")
        # print(f"前 5 条内容: {data[:5]}")
