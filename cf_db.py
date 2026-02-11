import requests
import json
from datetime import datetime, timedelta, timezone

class CF_VID:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        auth_val = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        self.session.headers.update({"Authorization": auth_val, "Content-Type": "application/json"})

    def get_data_slice(self, copy: int, copies: int):
        url = f"{self.base_url}/get"
        try:
            res = self.session.post(url, json={"copy": copy, "copies": copies}, timeout=15)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"❌ VID获取异常: {e}")
            return {"data": []}

class CF_TOKEN:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        auth_val = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        self.session.headers.update({"Authorization": auth_val, "Content-Type": "application/json"})
        self.beijing_tz = timezone(timedelta(hours=8))

    def upload(self, data: dict):
        # 注意：这里请根据你 Worker 的逻辑改为 /add 或 /update
        url = f"{self.base_url}/upload" 
        try:
            res = self.session.post(url, json=data, timeout=15)
            return {"code": res.status_code, "body": res.text, "ok": res.status_code == 200}
        except Exception as e:
            return {"code": 500, "body": str(e), "ok": False}

    def _get_bj_now(self):
        """无论系统时区是什么，始终返回当前的北京时间对象"""
        return datetime.now(timezone.utc).astimezone(self.beijing_tz)

    def _format_date(self, dt_obj):
        """格式化为 MM_DD"""
        return dt_obj.strftime("%m_%d")

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

# ===================== 新增：按北京时间小时半点为Key的消息存储类 =====================
class CF_MSG:
    """
    消息存储操作类：对接Worker接口，按北京时间「小时.半点」格式（如1.00、1.30、14.30）为Key，
    实现消息上传、按Key查询、按日期范围查询的核心功能，与现有CF_VID/CF_TOKEN类风格统一
    """

    def __init__(self, base_url: str, api_key: str):
        """初始化类，配置请求基础信息（与现有类初始化风格完全一致）"""
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        # 统一鉴权头格式：支持直接传入带Bearer前缀或不带的api_key
        auth_val = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        self.session.headers.update({
            "Authorization": auth_val,
            "Content-Type": "application/json"
        })
        # 初始化北京时间时区（复用CF_TOKEN的时区逻辑，保持统一）
        self.beijing_tz = timezone(timedelta(hours=8))

    def _get_bj_now(self):
        """内部方法：获取当前北京时间对象（与CF_TOKEN逻辑一致，保证时区统一）"""
        return datetime.now(timezone.utc).astimezone(self.beijing_tz)

    def _generate_hour_half_key(self, offset_hours: int = 0):
        """
        内部方法：生成北京时间的小时半点Key（核心逻辑，格式如1.00、1.30、14.30）
        :param offset_hours: 小时偏移量，0=当前时间，正数=未来，负数=过去（如-24=昨天此时）
        :return: 小时半点Key（字符串格式，如"14.30"）
        """
        # 计算目标北京时间（加上偏移小时数）
        target_time = self._get_bj_now() + timedelta(hours=offset_hours)
        # 提取北京时间的小时和分钟
        hour = target_time.hour  # 24小时制小时（0-23）
        minute = target_time.minute

        # 核心归一逻辑：00-29分钟归为当前小时的整点，30-59分钟归为当前小时的半点
        key_minute = 0 if minute < 30 else 30
        # 格式化为 "小时.分钟"（分钟固定两位，如00、30）
        return f"{hour}.{key_minute:02d}"

    def upload(self, msg_data: dict):
        """
        上传消息：调用Worker的/upload接口，自动按当前北京时间小时半点生成Key存储
        :param msg_data: 消息内容字典（需为非空字典，如{"content": "test", "type": "text"}）
        :return: 上传结果字典（与现有CF_TOKEN.upload返回格式保持一致：code/body/ok）
        """
        # 基础校验：消息必须为非空字典
        if not isinstance(msg_data, dict) or not msg_data:
            return {
                "code": 400,
                "body": "消息内容必须为非空字典",
                "ok": False
            }

        url = f"{self.base_url}/upload"
        try:
            # 直接透传msg_data，由Worker处理Key生成和存储
            response = self.session.post(url, json=msg_data, timeout=15)
            return {
                "code": response.status_code,
                "body": response.text,
                "ok": response.status_code == 200
            }
        except Exception as e:
            return {
                "code": 500,
                "body": str(e),
                "ok": False
            }

    def query_by_key(self, time_key: str):
        """
        按指定小时半点Key查询消息（如查询"14.30"的消息）
        :param time_key: 小时半点Key，格式必须为"小时.分钟"（如1.00、14.30，分钟仅支持00/30）
        :return: 查询结果（与现有_fetch返回格式一致：正常返回JSON，异常返回空列表）
        """
        # 简单校验Key格式：必须包含"."，且分钟为00/30
        if "." not in time_key:
            print(f"❌ Key格式错误：{time_key}，需为“小时.分钟”格式（如1.00、14.30）")
            return []
        hour_str, minute_str = time_key.split(".")
        if minute_str not in ("00", "30"):
            print(f"❌ Key分钟部分仅支持00（整点）或30（半点），当前为：{time_key}")
            return []

        url = f"{self.base_url}/get"
        try:
            print(f"🔍 正在查询北京时间Key：{time_key} 的消息...")
            # 按Key查询，参数传递格式与Worker接口匹配（如?key=14.30）
            response = self.session.get(url, params={"key": time_key}, timeout=10)
            return response.json() if response.status_code == 200 else []
        except Exception as e:
            print(f"Get Error: {e}")
            return []

    def query_current_hour_half(self):
        """查询当前北京时间小时半点Key的消息（无参数调用，自动匹配当前时间对应的Key）"""
        current_key = self._generate_hour_half_key(0)
        return self.query_by_key(current_key)

    def query_hour_half_by_offset(self, offset_hours: int):
        """
        按小时偏移量查询对应北京时间小时半点Key的消息（如offset_hours=-24查询昨天此时）
        :param offset_hours: 小时偏移量，如-24=昨天此时，+24=明天此时
        :return: 查询结果（与_fetch格式一致）
        """
        key = self._generate_hour_half_key(offset_hours)
        return self.query_by_key(key)
