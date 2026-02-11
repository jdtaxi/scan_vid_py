// 使用 CommonJS 语法替换 import
const path = require('path');
const os = require('os');
const { chromium } = require('playwright');

// 导入你的数据库配置 (确保 cf_db.js 也是 module.exports 导出的)
const { CF_VID, CF_TOKEN } = require('./cf_db.js');

/**
 * 在 CJS 环境下，直接 require 即可。
 * Node.js 会根据同步脚本生成的 .js 文件进行加载。
 * 由于 CJS 不是强制严格模式，混淆代码中的 'with' 语句将不会报错。
 */
const dylib = require('./function/dylib.js');


// 如果你需要 __filename 或 __dirname，CJS 是原生支持的，不需要 fileURLToPath
// console.log(__dirname);
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
const currentUA = dylib['getUA']();
console.log(currentUA)
// --- 辅助工具 ---
const log = (msg, level = "INFO") => {
  const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const icons = { INFO: "ℹ️", SUCCESS: "✅", ERROR: "❌", WARN: "⚠️", STATS: "📊", RISK: "🧠" };
  console.log(`[${timestamp}] ${icons[level] || '•'} ${msg}`);
};

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const splitAndGetMyPart = (dataList) => {
  // 在 CommonJS 中，__filename 变量是直接可用的，不需要转换
  const fileName = path.basename(__filename); // ✅ 正确写法
  const match = fileName.match(/(\d+)/);
  const scriptIdx = match ? parseInt(match[1]) : 0;
  
  const avg = dataList.length / NUM_PARTS;
  const idx = scriptIdx > 0 ? scriptIdx - 1 : 0;
  
  // 模拟切分逻辑
  return dataList.slice(Math.floor(idx * avg), Math.floor((idx + 1) * avg));
};
// 2. 生成 screen (屏幕分辨率)
// 模拟常见移动端分辨率
const generateScreen = () => {
    const widths = [375, 390, 414, 430, 360];
    const heightMultiplier = [2.16, 2.33, 2.17, 2.41];
    const w = widths[Math.floor(Math.random() * widths.length)];
    const h = Math.floor(w * heightMultiplier[Math.floor(Math.random() * heightMultiplier.length)]);
    return {screen:`${w}*${h}`,w,h};
};
const Screen =generateScreen()
// 风控冷却
async function cooldownSleep(streak) {
  let t = streak === 1 ? Math.random() * 2 + 4 : 
          streak === 2 ? Math.random() * 4 + 8 : 
          Math.random() * 4 + 14;
  //log(`风控冷却 sleep ${t.toFixed(1)}s`, "RISK");
  await sleep(t * 1000);
}


/**
 * 随机生成京东 H5 请求上下文参数字符串
 */
function generateJdContextString() {
    // 1. 生成 area (省_市_县_镇)
    // 格式通常为 1-30 之间的数字
    const generateArea = () => {
        const p = Math.floor(Math.random() * 30) + 1; // 省
        const c = Math.floor(Math.random() * 100) + 1; // 市
        const d = Math.floor(Math.random() * 3000) + 1; // 县
        const t = 0; // 镇，通常默认为 0
        return `${p}_${c}_${d}_${t}`;
    };

    

    // 3. 生成 uuid
    // 逻辑：当前毫秒时间戳 + 10位左右的随机数字
    const generateUuid = () => {
        const timestamp = Date.now().toString(); // 13位
        const randomPart = Math.random().toString().slice(2, 12); // 10位
        return timestamp + randomPart;
    };

    // 参数组合
    const params = {
        //area: generateArea(),
        screen: Screen.screen,
        //uuid: generateUuid(),
        xAPIClientLanguage: "zh_CN" // 固定值
    };

    // 转换为 URL 查询字符串格式
    return Object.keys(params)
        .map(key => `${key}=${params[key]}`)
        .join('&');
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
        "--disable-setuid-sandbox",
        "--disable-infobars",
        "--window-position=0,0",
        "--ignore-certificate-errors"
    ]
  });

  const context = await browser.newContext({
    userAgent: currentUA,//"Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    viewport: { width: Screen.w, height: Screen.h },
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
    const originalCanvasToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        if (type === 'image/png') {
            const ctx = this.getContext('2d');
            if (ctx) {
                ctx.fillStyle = 'rgba(255, 255, 255, 0.01)';
                ctx.fillRect(1, 1, 1, 1);
            }
        }
        return originalCanvasToDataURL.apply(this, arguments);
    };
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Apple Inc.'; 
        if (parameter === 37446) return 'Apple GPU';
        return getParameter.apply(this, arguments);
    };
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
        //增加h5st等
        
        
        const jddToken = await dylib['jddToken'](currentUA);

        const config = {
          "appId": "ea491",
          "functionId": "whx_getShopHomeActivityInfo",
          "body": { "venderId":vid, "source": "m-shop" },
          "appid": "shop_m_jd_com",
          "clientVersion": currentUA.split(';')[2]||"11.0.0",
          "client": currentUA.split(';')[1]==='android'?'android':"ios"||"wh5",
          "code":1,
          "user":"jd_liuqiangdong",
          "ua": currentUA
        };
        //const signedBody = await dylans.getbody(config);

        // 执行接口注入
        body=`functionId=whx_getShopHomeActivityInfo&body=${encodeURIComponent(JSON.stringify({venderId: vid, source: "m-shop"}))}&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5&${generateJdContextString()}&x-api-eid-token=${jddToken.token}`
        //body=`${signedBody}&x-api-eid-token=${jddToken.token}&${generateJdContextString()}`;
        //log(signedBody, "INFO");
        //log(jddToken.token, "INFO");
        //log(generateJdContextString());
        const resJson = await page.evaluate(async (vId) => {
          try {
            const res = await fetch("https://api.m.jd.com/client.action", {
              method: "POST",
              headers: { 
                "content-type": "application/x-www-form-urlencoded",
                //"user-agent": currentUA,
                //"referer": "https://shop.m.jd.com/"
              },
              //body: body
              //functionId=whx_getShopHomeActivityInfo&body=%7B%22venderId%22%3A%2217868%22%2C%22source%22%3A%22m-shop%22%7D&t=1770723924622&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5&area=1_72_2799_0&screen=636*1408&uuid=17707234355951389497624&xAPIClientLanguage=zh_CN&h5st=20260210194527631%3B9z6gtm3itdwh36h5%3Bea491%3Btk03w82e21beb18nCPX67Xd8b9oUBFkkvL54f4PNvko4WcNGCf8hix-i6FLB3p8ZFtGkZuEZthqq_vM95DGyoMbw_hCQ%3B66557b3bf07520792b9114884ee00dc6d834716688b0f611cffc4a37e9bbf495%3B5.2%3B1770723924631%3BfZRCXZPU5IuV5EaIt8rV0QqIr5KT-h-T-h6I-hfZXx-Vvh-T-prJ_YfZB5hW-NbUoZOVsdeIwJLI7I_VodLV98eUsV_U9g_JsFOI7E_I-h-T-h6Q1E7J8E6ZBh-f1ZvV_ULU98OI7UeU7AOI8MeIoVOVrJrUwd_J9M_I8QrU_YfZnZvFAI6GAU7ZBh-f1ZPV0ZfZnZfUsY7ZBh-f1ZPTzZ_WsJqK8wLH7kMU5YfZnZ-E-hfZXx-ZK4NVt9tVAkNPvV6PLYfZnZPGyQ7GAY6ZBh-f1Z-VupLHKYfZnZ-IxYfZB5hWkgfZXZvGbYfZnZvVwN6J-hfZBh-f1ZeZnZPVwN6J-hfZBh-f1ROVB5_ZxdOE-YfZBhfZXxfT0h-T-ZOVsY7ZBhfZB5hW-1bOsZqM4M6Vu8OI-h-T-trG9oLJvYfZBhfZXxfVB5_ZpN6J-hfZBh-f1heZnZvUsY7ZBhfZB5hWrh-T-JOE-YfZBhfZXxfVB5_ZsN6J-hfZBh-f1heZnZfUsY7ZBhfZB5hWxJeZnZvVsY7ZBhfZB5hW-N_WwpfV-h-T-dOE-YfZBhfZXxfVB5_Z2E6ZBhfZB5hWsh-T-VaG-hfZBh-f1heZnZfG-hfZBh-f1heZnZfIqYfZBhfZX1aZnZfIzMbEpM7ZBh-f1tqDB5_Zxg6ZBh-f1Z-OpNORPstW9wLHsYdZshvFsAKITgvTxp-UBRLHyYaIzcdZmBKEz8bO-h-T-dLEuYfZB5xD%3Bc8ef6c97feaf50ee191927adb1bd2f5a9fb16f331807f59fd9c0ca5b3f0240f7%3BgRaW989Gy8bE_oLE7w-Gy8rFvM7MtoLI4wrJ1R6G88bG_wPD9k7J1RLHxgKJ&x-api-eid-token=jdd03LECKTEBYVODALUJUK5RJT7DIRBNR2KLS27VGCACIO6LWUQJ4A5GB4ZR5LUTPIFDA45QLXK5V4VDW4W2AKJJKMF6JSQAAAAM4I5PNESYAAAAACC3ODBGUPTN6EYX
              body: `functionId=whx_getShopHomeActivityInfo&body=${encodeURIComponent(JSON.stringify({venderId: vId, source: "m-shop"}))}&appid=shop_m_jd_com&clientVersion=11.0.0&client=wh5&${generateJdContextString()}`
            });
            log(` 异常1: ${res.toString()}`, "WARN");
            return await res.json();
          } catch (e) {
            log(` 异常2: ${e.toString()}`, "WARN");
            return { code: "-2", msg: e.toString() };
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
        log(`${roundTag}${stats.total_scanned}->店铺 ${vid} 异常3: ${e.toString()}`, "WARN");

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
