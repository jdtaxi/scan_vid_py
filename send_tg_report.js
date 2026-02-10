import { CF_TOKEN } from './cf_db.js'; // 假设上面的类保存在 cf_db.js

/**
 * 发送 Telegram 消息
 */
async function sendTgMsg(text) {
  const token = process.env.TG_BOT_TOKEN;
  const chatId = process.env.TG_CHAT_ID;

  if (!token || !chatId) {
    console.error("❌ 缺失 TG_BOT_TOKEN 或 TG_CHAT_ID");
    return;
  }

  const url = `https://api.telegram.org/bot${token}/sendMessage`;
  const payload = {
    chat_id: chatId,
    text: text,
    parse_mode: "Markdown"
  };

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    console.log(`📡 TG 发送状态: ${res.status}`);
  } catch (e) {
    console.error(`❌ TG 发送异常: ${e.message}`);
  }
}

/**
 * 运行报表逻辑
 */
async function runReport() {
  // 从环境变量读取配置
  const API_KEY = process.env.API_KEY || "leaflow";
  const WORKER_TOKEN_URL = process.env.WORKER_TOKEN_URL || "https://token.zshyz.us.ci";

  const client = new CF_TOKEN(WORKER_TOKEN_URL, API_KEY);

  // 1. 获取数据
  console.log("🚀 开始获取数据...");
  const resYesterday = await client.getYesterdayData();
  const resToday = await client.getTodayData();

  const yList = Array.isArray(resYesterday) ? resYesterday : (resYesterday.data || []);
  const tList = Array.isArray(resToday) ? resToday : (resToday.data || []);

  // 2. 计算数量与新增 (使用 Set 进行差集运算)
  const countYesterday = yList.length;
  const countToday = tList.length;

  const yTokens = new Set(yList.map(item => item.token).filter(Boolean));
  const tTokens = new Set(tList.map(item => item.token).filter(Boolean));

  // 计算新增：在 tTokens 中但不在 yTokens 中的元素
  let countNew = 0;
  for (let token of tTokens) {
    if (!yTokens.has(token)) countNew++;
  }

  // 3. 根据最后一个元素判断已执行批次
  let batchInfo = "0";
  if (tList.length > 0) {
    try {
      const lastItemTs = tList[tList.length - 1].ts_bj || "";
      // JS Date.parse 可以处理大部分 YYYY/MM/DD HH:MM 格式
      const lastDt = new Date(lastItemTs);
      
      if (!isNaN(lastDt.getTime())) {
        const hour = lastDt.getHours();
        const minute = lastDt.getMinutes();
        // 计算批次：1-46 (对应每半小时)
        const currentBatch = (hour * 2) + (minute >= 30 ? 1 : 0) + 1;
        batchInfo = `${currentBatch}`;
      }
    } catch (e) {
      batchInfo = "计算中";
    }
  }

  // 4. 构造消息
  const bjNowStr = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai'
  }).format(new Date());

  let msg = `📊 *VID 扫描任务汇总报表*\n`;
  msg += `---`;
  msg += `\n⏰ *汇报时间*: \`${bjNowStr}\``;
  msg += `\n📅 *昨日 Token 总数*: \`${countYesterday}\``;
  msg += `\n📅 *今日 Token 总数*: \`${countToday}\``;
  msg += `\n✨ *今日新增 Token*: \`+${countNew}\``;
  msg += `\n---`;
  msg += `\n🔢 *任务进度*: 已执行 \`${batchInfo}/46\` 批次`;

  // 5. 执行打印并发送
  console.log(msg);
  await sendTgMsg(msg);
}

// 执行脚本
runReport();
