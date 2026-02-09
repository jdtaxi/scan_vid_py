import requests
import json

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
            print(f"❌ 获取VID失败: {e}")
            return {"data": []}

class CF_TOKEN:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        auth_val = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        self.session.headers.update({"Authorization": auth_val, "Content-Type": "application/json"})

    def upload(self, data: dict):
        """
        上传 Token 到云端。
        注意：请确保 Worker 端支持 /add 路径。如果你的路径是 /update，请修改此处。
        """
        url = f"{self.base_url}/add" 
        try:
            # 增加详细日志，方便调试
            res = self.session.post(url, json=data, timeout=15)
            
            # 返回详细结果字典，而不仅仅是布尔值
            return {
                "status": res.status_code,
                "text": res.text,
                "success": res.status_code == 200
            }
        except Exception as e:
            return {
                "status": 500,
                "text": str(e),
                "success": False
            }
