import requests
import json
import os

# 配置基础请求头
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

def fetch_proxies_for_account(email, password):
    """
    核心抓取函数：登录、签到、并返回代理列表
    """
    res_data = {"unlimited": [], "limited": [], "msg": "", "email": email}
    try:
        # 1. 登录
        login_payload = json.dumps({"email": email, "password": password})
        login_res = requests.post("https://api.ip2free.com/api/account/login?", 
                                 headers=BASE_HEADERS, 
                                 data=login_payload, timeout=30)
        login_json = login_res.json()
        
        if login_json.get("code") != 0:
            return None, f"登录失败: {login_json.get('msg')}"

        token = login_json["data"]["token"]
        headers = BASE_HEADERS.copy()
        headers["x-token"] = token
        
        # 2. 签到逻辑
        task_list_res = requests.post("https://api.ip2free.com/api/account/taskList?", headers=headers, data="{}", timeout=30)
        tasks = task_list_res.json().get("data", {}).get("list", [])
        
        check_in_msg = "无需签到"
        for task in tasks:
            if "点击就送" in task.get("task_name", "") and task.get("is_finished") == 0:
                task_id = task.get("id")
                finish_res = requests.post("https://api.ip2free.com/api/account/finishTask?", 
                                         headers=headers, data=json.dumps({"id": task_id}), timeout=30)
                check_in_msg = "签到成功 ✅" if finish_res.json().get("code") == 0 else "签到失败 ❌"
                break
            elif "点击就送" in task.get("task_name", ""):
                check_in_msg = "今日已签到 📅"
        
        res_data["msg"] = check_in_msg

        # 3. 抓取列表 (限额 + 无限)
        common_payload = json.dumps({"keyword": "", "country": "", "city": "", "page": 1, "page_size": 10})
        
        # 限额列表
        f_res = requests.post("https://api.ip2free.com/api/ip/freeList?", headers=headers, data=common_payload, timeout=30)
        for item in f_res.json().get("data", {}).get("free_ip_list", []):
            res_data["limited"].append(f"{item.get('protocol')}://{item.get('username')}:{item.get('password')}@{item.get('ip')}:{item.get('port')}")

        # 无限列表
        t_res = requests.post("https://api.ip2free.com/api/ip/taskIpList?", headers=headers, data=common_payload, timeout=30)
        for item in t_res.json().get("data", {}).get("page", {}).get("list", []):
            res_data["unlimited"].append(f"{item.get('protocol')}://{item.get('username')}:{item.get('password')}@{item.get('ip')}:{item.get('port')}")

        return res_data, "成功"
    except Exception as e:
        return None, str(e)

def get_all_proxies():
    """
    外部调用的统一入口
    从环境变量 IP2FREE_ACCOUNTS 获取账号信息
    格式示例: email1:pass1,email2:pass2
    """
    raw_accounts = os.environ.get("IP2FREE_ACCOUNTS", "")
    if not raw_accounts:
        print("错误: 未找到环境变量 IP2FREE_ACCOUNTS")
        return []

    # 解析环境变量
    account_list = []
    for item in raw_accounts.split(","):
        if ":" in item:
            email, pwd = item.split(":", 1)
            account_list.append({"email": email.strip(), "password": pwd.strip()})

    results = []
    for acc in account_list:
        data, status = fetch_proxies_for_account(acc["email"], acc["password"])
        if data:
            results.append(data)
        else:
            print(f"账号 {acc['email']} 获取失败: {status}")
    
    return results
