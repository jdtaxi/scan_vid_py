import requests
import json
import os
import base64
from nacl import encoding, public  # 需要安装 PyNaCl 库来加密 Secret

def get_public_key(auth_headers, repo):
    """获取 GitHub 仓库的公钥用于加密 Secret"""
    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    res = requests.get(url, headers=auth_headers)
    return res.json()

def update_secret(auth_headers, repo, secret_name, new_value):
    """更新 GitHub Secret"""
    public_key_data = get_public_key(auth_headers, repo)
    key_id = public_key_data['key_id']
    public_key = public_key_data['key']

    # 使用 PyNaCl 进行加密
    public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder)
    sealed_box = public.SealedBox(public_key_obj)
    encrypted_value = sealed_box.encrypt(new_value.encode("utf-8"))
    base64_value = base64.b64encode(encrypted_value).decode("utf-8")

    url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
    data = {"encrypted_value": base64_value, "key_id": key_id}
    res = requests.put(url, headers=auth_headers, data=json.dumps(data))
    
    if res.status_code in [201, 204]:
        print(f"成功更新 Secret: {secret_name}")
    else:
        print(f"更新失败: {res.text}")

def fetch_proxies():
    # ... (此处省略你之前的登录和抓取逻辑)
    # 假设最终拿到的去重列表是 proxy_list
    proxy_list = ["socks5://user:pass@ip:port", "socks5://user2:pass2@ip2:port2"]
    return ",".join(list(set(proxy_list)))

def main():
    # 配置
    token = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY") # 格式: 用户名/仓库名
    auth_headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 执行抓取
    proxies_str = fetch_proxies()
    
    if proxies_str:
        # 更新到名为 SOCKSPROXY 的 Secret
        update_secret(auth_headers, repo, "SOCKSPROXY", proxies_str)

if __name__ == "__main__":
    main()
