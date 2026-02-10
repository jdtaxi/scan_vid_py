import libsodium from 'libsodium-wrappers';

// 强制即时打印日志
const log = (msg) => {
  console.log(msg);
};

// ===================== 配置信息 =====================
const BASE_HEADERS = {
  "accept": "*/*",
  "accept-language": "zh-CN,zh;q=0.9",
  "cache-control": "no-cache",
  "content-type": "text/plain;charset=UTF-8",
  "domain": "www.ip2free.com",
  "lang": "cn",
  "webname": "IP2FREE",
  "Referer": "https://www.ip2free.com/",
  "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
};

/**
 * 更新 GitHub Secret
 * 需要 libsodium-wrappers 来处理加密
 */
async function updateGithubSecret(token, repo, secretName, value) {
  log(`\n[Step 3] 准备同步到 GitHub Secrets...`);
  const authHeaders = {
    "Authorization": `token ${token}`,
    "Accept": "application/vnd.github.v3+json"
  };

  try {
    await libsodium.ready;
    
    // 1. 获取公钥
    const pkUrl = `https://api.github.com/repos/${repo}/actions/secrets/public-key`;
    const pkRes = await fetch(pkUrl, { headers: authHeaders });
    if (!pkRes.ok) {
      log(`[-] 失败: 无法获取仓库公钥，状态码: ${pkRes.status}`);
      return;
    }
    const { key, key_id } = await pkRes.json();

    // 2. 加密逻辑 (密封箱加密)
    const bckey = Buffer.from(key, 'base64');
    const bValue = Buffer.from(value);
    const encrypted = libsodium.crypto_box_seal(bValue, bckey);
    const base64Value = Buffer.from(encrypted).toString('base64');

    // 3. 写入 Secret
    const secretUrl = `https://api.github.com/repos/${repo}/actions/secrets/${secretName}`;
    const putRes = await fetch(secretUrl, {
      method: 'PUT',
      headers: authHeaders,
      body: JSON.stringify({
        encrypted_value: base64Value,
        key_id: key_id
      })
    });

    if (putRes.status === 201 || putRes.status === 204) {
      log(`[√] 成功！Secret '${secretName}' 已同步更新。`);
    } else {
      log(`[×] 写入失败: ${putRes.status}`);
    }
  } catch (e) {
    log(`[×] 更新过程崩溃: ${e.message}`);
  }
}

/**
 * 抓取代理逻辑
 */
async function fetchProxies(email, password) {
  const proxies = [];
  log(`\n[Step 2] 正在处理账号: ${email}`);

  try {
    // 1. 登录
    const loginRes = await fetch("https://api.ip2free.com/api/account/login?", {
      method: 'POST',
      headers: BASE_HEADERS,
      body: JSON.stringify({ email, password }),
      signal: AbortSignal.timeout(25000)
    });
    
    const lJson = await loginRes.json();
    if (lJson.code !== 0) {
      log(`    [-] 登录失败: ${lJson.msg}`);
      return [];
    }

    const token = lJson.data.token;
    const headers = { ...BASE_HEADERS, "x-token": token };
    log(`    [+] 登录成功`);

    // 2. 签到逻辑
    log(`    [*] 正在检查每日任务...`);
    const taskRes = await fetch("https://api.ip2free.com/api/account/taskList?", {
      method: 'POST',
      headers: headers,
      body: "{}",
      signal: AbortSignal.timeout(25000)
    });
    const tasks = (await taskRes.json()).data?.list || [];

    for (const task of tasks) {
      if (task.task_name?.includes("点击就送")) {
        if (task.is_finished === 0) {
          log(`    [*] 发现未完成签到任务: ${task.task_name} (ID: ${task.id})`);
          const finishRes = await fetch("https://api.ip2free.com/api/account/finishTask?", {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ id: task.id }),
            signal: AbortSignal.timeout(25000)
          });
          const fJson = await finishRes.json();
          log(fJson.code === 0 ? "    [√] 签到成功 ✅" : `    [×] 签到失败: ${fJson.msg}`);
        } else {
          log("    [i] 今日已签到 📅");
        }
        break;
      }
    }

    // 3. 抓取逻辑
    const commonPayload = JSON.stringify({ keyword: "", country: "", city: "", page: 1, page_size: 10 });
    
    const endpoints = [
      { name: "限额列表", url: "https://api.ip2free.com/api/ip/freeList?", key: "free_ip_list" },
      { name: "无限列表", url: "https://api.ip2free.com/api/ip/taskIpList?", key: "list" }
    ];

    for (const ep of endpoints) {
      log(`    [*] 正在抓取${ep.name}...`);
      const res = await fetch(ep.url, {
        method: 'POST',
        headers,
        body: commonPayload,
        signal: AbortSignal.timeout(25000)
      });
      const resJson = await res.json();
      
      let items = [];
      if (ep.key === "list") {
        // 无限列表可能在 data.page.list 或 data.list
        items = resJson.data?.page?.list || resJson.data?.list || [];
      } else {
        items = resJson.data?.[ep.key] || [];
      }

      items.forEach(item => {
        proxies.push(`${item.protocol}://${item.username}:${item.password}@${item.ip}:${item.port}`);
      });
    }

    log(`    [+] 账号处理完毕，获取到 ${proxies.length} 个代理`);
    return proxies;
  } catch (e) {
    log(`    [!] 抓取过程发生异常: ${e.message}`);
    return [];
  }
}

/**
 * 主函数
 */
async function main() {
  log("==========================================");
  log("      IP2FREE 代理同步工具 (JS版)        ");
  log("==========================================");

  const ghPat = process.env.GH_PAT;
  const repo = process.env.GITHUB_REPOSITORY;
  const accStr = process.env.IP2FREE_ACCOUNTS || "";

  log(`[Step 1] 环境自检:`);
  log(`[*] 仓库: ${repo}`);
  const accounts = accStr.split(",").filter(a => a.includes(":"));
  log(`[*] 配置账号数: ${accounts.length}`);

  if (!ghPat || !repo || accounts.length === 0) {
    log("[-] 错误: 关键环境变量缺失！");
    process.exit(1);
  }

  let allResults = [];
  for (const account of accounts) {
    const [u, p] = account.split(":");
    const results = await fetchProxies(u.trim(), p.trim());
    allResults = allResults.concat(results);
  }

  const uniqueList = [...new Set(allResults)];
  log(`\n[汇总] 抓取完成！原始总计: ${allResults.length}，去重后: ${uniqueList.length}`);

  if (uniqueList.length > 0) {
    await updateGithubSecret(ghPat, repo, "SOCKSPROXY", uniqueList.join(","));
  } else {
    log("[-] 警告: 未获取到任何有效代理，不执行 Secret 更新。");
  }
}

main();
