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
            print(f"❌ VID获取异常: {e}")
            return {"data": []}

class CF_TOKEN:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        auth_val = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        self.session.headers.update({"Authorization": auth_val, "Content-Type": "application/json"})

    def upload(self, data: dict):
        # 注意：这里请根据你 Worker 的逻辑改为 /add 或 /update
        url = f"{self.base_url}/add" 
        try:
            res = self.session.post(url, json=data, timeout=15)
            return {"code": res.status_code, "body": res.text, "ok": res.status_code == 200}
        except Exception as e:
            return {"code": 500, "body": str(e), "ok": False}
