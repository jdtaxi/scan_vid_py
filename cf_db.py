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
            return {"data": []}

class CF_TOKEN:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        auth_val = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        self.session.headers.update({"Authorization": auth_val, "Content-Type": "application/json"})

    def upload(self, data: dict):
        url = f"{self.base_url}/update" # 或者你的上传路径
        try:
            # 包装成数组，因为 Worker 通常接受批量上传
            res = self.session.post(url, json=[data], timeout=15)
            return res.status_code == 200
        except Exception as e:
            print(f"Token Upload Error: {e}")
            return False
