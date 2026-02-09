import requests
import json
import os
import base64
from nacl import encoding, public

# ===================== 基础配置 =====================
BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "cache-control": "no-cache",
    "content-type": "text/plain;charset=UTF-8",
    "domain": "www.ip2free.com",
    "lang": "cn",
    "webname": "IP2FREE",
    "Referer": "https://www.ip2free.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
}

# ===================== GitHub Secret 更新逻辑 =====================

def get_public_key(auth_headers, repo):
    """获取 GitHub 仓库公钥用于加密 Secret"""
    url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    print(f"[*] 正在请求 GitHub 公钥: {url}")
    res = requests.get(url, headers=auth_headers)
    if res.status_code == 200:
        print("[+] 成功获取公钥")
        return res.json()
    else:
        print(f"[-] 获取公钥失败: {res.text}")
        return None

def update_secret(token, repo, secret_name, new_value):
    """加密并更新 GitHub Secret"""
    auth_headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    public_key_data = get_public_key(auth_headers, repo)
    if not public_key_data: return

    key_id = public_key_data['key_id']
    public_key = public_key_data['key']

    # 使用 PyNaCl 加密
    print(f"[*] 正在加密 Secret: {secret_name}")
    public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder)
    sealed_box = public.SealedBox(public_key_obj)
    encrypted_value = sealed_box.encrypt(new_value.encode("utf-8"))
    base64_value = base64.b64encode(encrypted_value).decode("utf-8")

    url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
    data = {"encrypted_value": base64_value, "key_id": key_id}
    
    print(f"[*] 正在推送更新到 GitHub Secret...")
    res = requests.put(url, headers=auth_headers, data=json.dumps(data))
    
    if res.status_code in [201, 204]:
        print(f"[#] 恭喜！Secret '{secret_name}' 更新成功！")
    else:
        print(f"[-] 更新失败，状态码: {res.status_code}, 原因: {res.text}")

# ===================== IP2FREE 业务逻辑 =====================

def fetch_proxies_from_ip2free(email, password):
    """执行单个账号的登录、签到和抓取"""
    proxies = []
    try:
        print(f"\n>>> 账号: {email} <<<")
        # 1. 登录
        login_res = requests.post("https://api.ip2free.com/api/account/login?", 
                                 headers=BASE_HEADERS, 
                                 data=json.dumps({"email": email, "password": password}), timeout=30)
        login_json = login_res.json()
        if login_json.get("code") != 0:
            print(f"    [!] 登录失败: {login_json.get('msg')}")
            return []
        
        token = login_json["data"]["token"]
        headers = BASE_HEADERS.copy()
        headers["x-token"] = token
        print(f"    [+] 登录成功")

        # 2. 签到
        print(f"    [*] 检查每日签到...")
        task_res = requests.post("https://api.ip2free.com/api/account/taskList?", headers=headers, data="{}", timeout=30)
        tasks = task_res.json().get("data", {}).get("list", [])
        for task in tasks:
            if "点击就送" in task.get("task_name", "") and task.get("is_finished") == 0:
                requests.post("https://api.ip2free.com/api/account/finishTask?", 
                             headers=headers, data=json.dumps({"id": task.get("id")}), timeout=30)
                print(f"    [√] 签到完成")
                break

        # 3. 抓取
        print(f"    [*] 正在抓取列表...")
        payload = json.dumps({"keyword": "", "country": "", "city": "", "page": 1, "page_size": 10})
        
        # 限额列表
        f_res = requests.post("https://api.ip2free.com/api/ip/freeList?", headers=headers, data=payload, timeout=30)
        for i in f_res.json().get("data", {}).get("free_ip_list", []):
            proxies.append(f"{i.get('protocol')}://{i.get('username')}:{i.get('password')}@{i.get('ip')}:{i.get('port')}")
        
        # 无限列表
        t_res = requests.post("https://api.ip2free.com/api/ip/taskIpList?", headers=headers, data=payload, timeout=30)
        for i in t_res.json().get("data", {}).get("page", {}).get("list", []):
            proxies.append(f"{i.get('protocol')}://{i.get('username')}:{i.get('password')}@{i.get('ip')}:{i.get('port')}")
            
        print(f"    [+] 该账号抓取到 {len(proxies)} 条代理")
        return proxies
    except Exception as e:
        print(f"    [!] 发生异常: {str(e)}")
        return []

# ===================== 入口函数 =====================

def main():
    # 1. 获取环境变量
    gh_pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    accounts_raw = os.environ.get("IP2FREE_ACCOUNTS", "")

    if not gh_pat or not accounts_raw:
        print("[-] 错误: 环境变量 GH_PAT 或 IP2FREE_ACCOUNTS 未设置")
        return

    # 2. 遍历账号抓取
    all_proxies = []
    for acc in accounts_raw.split(","):
        if ":" in acc:
            u, p = acc.split(":", 1)
            all_proxies.extend(fetch_proxies_from_ip2free(u.strip(), p.strip()))

    # 3. 去重并合并
    unique_proxies = list(set(all_proxies))
    print(f"\n[*] 汇总完毕: 原始总数 {len(all_proxies)}, 去重后 {len(unique_proxies)}")
