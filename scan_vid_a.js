import os
import path
import { fileURLToPath } from 'url';
import { chromium } from 'playwright';
import { CF_VID, CF_TOKEN } from './cf_db.js';

// --- 配置加载 ---
const API_KEY = process.env.API_KEY || "leaflow";
const TARGET_PATTERN = process.env.TARGET_PATTERN || "2PAAf74aG3D61qvfKUM5dxUssJQ9";
const WORKER_VID_URL = process.env.WORKER_VID_URL || "https://vid.zshyz.us.ci";
const WORKER_TOKEN_URL = process.env.WORKER_TOKEN_URL || "https://token.zshyz.us.ci";
const RUN_DURATION_MINUTES = parseInt(process.env.RUN_DURATION_MINUTES || "10");
const MAX_CONSECUTIVE_ERRORS = 10;
const COPIES = parseInt(process.env.COPIES || "46");
const NUM_PARTS = parseInt(process.env.NUM_PARTS || "20");
const MAX_RETRY_ROUNDS = 3;

const stats = { success: 0, hit: 0, blocked: 0, error: 0, total_scanned: 0 };

// --- 辅助工具 ---
const log = (msg, level = "INFO") => {
  const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const icons = { INFO: "ℹ️", SUCCESS: "✅", ERROR: "❌", WARN: "⚠️", STATS: "📊", RISK: "🧠" };
  console.log(`[${timestamp}] ${icons[level] || '•'} ${msg}`);
};

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const splitAndGetMyPart = (dataList) => {
  const fileName = path.basename(fileURLToPath(import.meta.url));
  const match = fileName.match(/(\d+)/);
  const scriptIdx = match ? parseInt(match[1]) : 0;
  
  const avg = dataList.length / NUM_PARTS;
  const idx = scriptIdx > 0 ? scriptIdx - 1 : 0;
  
  // 模拟切分逻辑
  return dataList.slice(Math.floor(idx * avg), Math.floor((idx + 1) * avg));
};

async function cooldownSleep(streak) {
  let t = streak === 1 ? Math.random() * 2 + 4 : 
          streak === 2 ? Math.random() * 4 + 8 : 
          Math.random() * 4 + 14;
  //log(`风控冷却 sleep ${t.toFixed(1)}s`, "RISK");
  await sleep(t * 1000);
}

// --- 核心逻辑 ---
async function runTask() {
  const dbVid = new CF_VID(WORKER_VID_URL, API_KEY);
  const dbToken = new CF_TOKEN(WORKER_TOKEN_URL, API_KEY);

  // 1. 查询 IP
  try {
    const ipRes = await fetch('https://api.ipify.org');
    const currentIp = await ipRes.text();
    log(`任务启动 IP: ${currentIp}`, "INFO");
  } catch (e) { /* ignore */ }

  // 2. 计算分片
  const now = new Date();
  // 转换为北京时间
  const bjTime = new Date(now.toLocaleString("en-US", {timeZone: "Asia/Shanghai"}));
  const sliceIdx = bjTime.getHours() * 2 + (bjTime.getMinutes() >= 30 ? 1 : 0);
  
  log(`⏰ 北京时间: ${bjTime.toLocaleString()} | 分片: ${sliceIdx}`);

  const result = await dbVid.getDataSlice(sliceIdx, COPIES);
  const venderIds = splitAndGetMyPart(result.data || []);
  
  log(`任务分配: 本分片(${sliceIdx})执行 ${venderIds.length} 条`, "INFO");
  if (venderIds.length === 0) return;

  const scriptStartTime = Date.now();
  let consecutiveErrors = 0;
  let pendingVids = [...venderIds];

  // 3. 启动浏览器
  const browser = await chromium.launch({
    headless: true,
    args: [
      "--disable-blink-features=AutomationControlled",
      "--no-sandbox",
      "--disable-infobars"
    ]
  });

  const context = await browser.newContext({
    userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai"
  });

  // 模拟 Stealth (通过注入脚本)
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
    // ... 其他 Canvas/WebGL 指纹伪造逻辑同 Python 版
  });

  async function scanRound(targetList, roundTag) {
    const roundFailed = [];
    
    for (const vid of targetList) {
      stats.total_scanned++;
      if ((Date.now() - scriptStartTime) / 60000 >= RUN_DURATION_MINUTES) {
        log(`达到时长上限，停止 ${roundTag}`, "WARN");
        return { isOk: false, roundFailed };
      }

      const page = await context.newPage();
      try {
        // 访问首页模拟人工轨迹
        await page.goto("https://m.jd.com", { waitUntil: 'domcontentloaded', timeout: 20000 });
        await page.mouse.wheel(0, Math.random() * 300 + 500);
        await sleep(Math.random() * 1500 + 1500);

        // 执行接口注入
        const resJson = await page.evaluate(async (vId) => {
          try {
            const res = await fetch("https://api.m.jd.com/client.action", {
              method: "POST",
              headers: { "content-type": "application/x-www-form-urlencoded" },
              body: `functionId=whx_getShopHomeActivityInfo&body=${encodeURIComponent(JSON.stringify({venderId: vId, source: "m-shop"}))}&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5`
            });
            return await res.json();
          } catch (e) {
            return { code: "-1", msg: e.toString() };
          }
        }, vid);

        if (resJson?.code === "0") {
          stats.success++;
          consecutiveErrors = 0;
          const isvUrl = resJson.result?.signStatus?.isvUrl || "";
          
          if (isvUrl.includes(TARGET_PATTERN)) {
            const tokenMatch = isvUrl.match(/token=([^&]+)/);
            const token = tokenMatch ? tokenMatch[1] : "N/A";
            log(`${roundTag}${stats.total_scanned}->🎯 命中 ${vid} | Token: ${token}`, "SUCCESS");
            await dbToken.upload({ vender: vid, token: token });
          } else {
            log(`${roundTag}${stats.total_scanned}->店铺 ${vid} 正常`, "INFO");
          }
        } else {
          throw new Error(`Code ${resJson?.code}`);
        }

      } catch (e) {
        stats.error++;
        consecutiveErrors++;
        roundFailed.push(vid);
        log(`${roundTag}${stats.total_scanned}->店铺 ${vid} 异常: ${e.message}`, "WARN");

        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          log("连续异常达上限，中断本轮", "ERROR");
          return { isOk: false, roundFailed };
        }
        await cooldownSleep(consecutiveErrors);
      } finally {
        await page.close();
        await sleep(Math.random() * 2000 + 4000);
      }
    }
    return { isOk: true, roundFailed };
  }

  // --- 重试循环 ---
  for (let attempt = 0; attempt <= MAX_RETRY_ROUNDS; attempt++) {
    if (pendingVids.length === 0) break;

    const tag = attempt === 0 ? "[初次]" : `[重试${attempt}]`;
    if (attempt > 0) {
      log(`🔄 开始 ${tag} 扫描，剩余失败条数: ${pendingVids.length}`, "STATS");
      await sleep(5000);
    }

    const { isOk, roundFailed } = await scanRound(pendingVids, tag);
    pendingVids = roundFailed;
    if (!isOk) break;
  }

  log(`任务结束 | 总量: ${venderIds.length} | 成功: ${stats.success} | 最终失败: ${pendingVids.length}`, "STATS");
  await browser.close();
}

runTask().catch(err => console.error("Fatal Error:", err));
