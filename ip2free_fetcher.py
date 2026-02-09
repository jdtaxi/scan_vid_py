import requests
import json
import os
import base64
import sys
from nacl import encoding, public

# 强制即时打印日志，不等待缓存
def log(msg):
    print(f"{msg}", flush=True)

# ===================== 配置信息 =====================
BASE_HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "content-type": "text/plain;charset=UTF-8",
    "domain": "www.ip2free.com",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
}

def update_github_secret(token, repo, secret_name, value):
    log(f"\n[Step 3] 准备同步到 GitHub Secrets...")
    auth_headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        # 获取公钥
        pk_url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
        pk_res = requests.get(pk_url, headers=auth_headers)
        if pk_res.status_code != 200:
            log(f"[-] 失败: 无法获取仓库公钥，代码: {pk_res.status_code}")
            return
        pk_data = pk_res.json()

        # 加密
        public_key = public.PublicKey(pk_data['key'].encode("utf-8"), encoding.Base64Encoder)
        sealed_box = public.SealedBox(public_key)
        encrypted_value = sealed_box.encrypt(value.encode("utf-8"))
        base64_value = base64.b64encode(encrypted_value).decode("utf-8")

        # 写入
        secret_url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
        data = {"encrypted_value": base64_value, "key_id": pk_data['key_id']}
        put_res = requests.put(secret_url, headers=auth_headers, data=json.dumps(data))
        
        if put_res.status_code in [201, 204]:
            log(f"[√] 成功！Secret '{secret_name}' 已更新。")
        else:
            log(f"[×] 写入失败: {put_res.status_code}")
    except Exception as e:
        log(f"[×] 更新过程崩溃: {str(e)}")

def fetch_proxies(email, password):
    proxies = []
    log(f"\n[Step 2] 正在处理账号: {email}")
    try:
        # 登录
        login_res = requests.post("https://api.ip2free.com/api/account/login?", 
                                 headers=BASE_HEADERS, 
                                 data=json.dumps({"email": email, "password": password}), timeout=20)
        l_json = login_res.json()
        if l_json.get("code") != 0:
            log(f"    [-] 登录失败: {l_json.get('msg')}")
            return []
        
        token = l_json["data"]["token"]
        headers = BASE_HEADERS.copy()
        headers["x-token"] = token
        log(f"    [+] 登录成功")

        # 抓取逻辑 (简写)
        p_payload = json.dumps({"page": 1, "page_size": 10})
        # 抓取 freeList
        f_res = requests.post("https://api.ip2free.com/api/ip/freeList?", headers=headers, data=p_payload, timeout=20).json()
        items = f_res.get("data", {}).get("free_ip_list", [])
        for i in items:
            proxies.append(f"{i.get('protocol')}://{i.get('username')}:{i.get('password')}@{i.get('ip')}:{i.get('port')}")
        
        log(f"    [+] 抓取完成，获取到 {len(proxies)} 个代理")
        return proxies
    except Exception as e:
        log(f"    [!] 抓取崩溃: {str(e)}")
        return []

def main():
    log("==========================================")
    log("       IP2FREE 代理同步脚本启动           ")
    log("==========================================")
    
    # 获取环境变量
    gh_pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    acc_str = os.environ.get("IP2FREE_ACCOUNTS", "")

    log(f"[Step 1] 环境检查:")
    log(f"[*] Repository: {repo}")
    log(f"[*] GH_PAT: {'已配置' if gh_pat else '未配置'}")
    log(f"[*] ACCOUNTS: {'已配置' if acc_str else '未配置'}")

    if not all([gh_pat, repo, acc_str]):
        log("[-] 错误: 环境变量不完整，请检查 Secrets 配置！")
        sys.exit(1)

    all_results = []
    for account in acc_str.split(","):
        if ":" in account:
            u, p = account.split(":", 1)
            all_results.extend(fetch_proxies(u.strip(), p.strip()))

    unique_list = list(set(all_results))
    log(f"\n[汇总] 总计获取去重代理: {len(unique_list)} 个")

    if unique_list:
        update_github_secret(gh_pat, repo, "SOCKSPROXY", ",".join(unique_list))
    else:
        log("[-] 没有数据，不执行更新。")

if __name__ == "__main__":
    main()
