/**
 * 基础请求客户端 (CommonJS 风格)
 */
class BaseClient {
  constructor(baseUrl, apiKey) {
    this.baseUrl = (baseUrl || '').replace(/\/+$/, '');
    this.headers = {
      'Authorization': (apiKey || '').startsWith('Bearer ') ? apiKey : `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    };
  }

  async request(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${this.baseUrl}${endpoint}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || 15000);

    try {
      const response = await fetch(url, {
        ...options,
        headers: { ...this.headers, ...options.headers },
        signal: controller.signal
      });
      clearTimeout(timeout);
      return response;
    } catch (error) {
      clearTimeout(timeout);
      if (error.name === 'AbortError') throw new Error('Request Timeout');
      throw error;
    }
  }
}

/**
 * 视频 ID 数据切片处理类
 */
class CF_VID extends BaseClient {
  async getDataSlice(copy, copies) {
    try {
      const res = await this.request('/get', {
        method: 'POST',
        body: JSON.stringify({ copy, copies })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      console.error(`❌ VID 获取异常: ${e.message}`);
      return { data: [] };
    }
  }
}

/**
 * Token 数据上传与查询类
 */
class CF_TOKEN extends BaseClient {
  _getBjDateStr(offsetDays = 0) {
    const now = new Date();
    if (offsetDays !== 0) now.setDate(now.getDate() + offsetDays);
    const formatter = new Intl.DateTimeFormat('en-GB', {
      month: '2-digit',
      day: '2-digit',
      timeZone: 'Asia/Shanghai'
    });
    const parts = formatter.formatToParts(now);
    const month = parts.find(p => p.type === 'month').value;
    const day = parts.find(p => p.type === 'day').value;
    return `${month}_${day}`;
  }

  async upload(data) {
    try {
      const res = await this.request('/upload', {
        method: 'POST',
        body: JSON.stringify(data)
      });
      const body = await res.text();
      return { code: res.status, body, ok: res.ok };
    } catch (e) {
      return { code: 500, body: e.message, ok: false };
    }
  }

  async getTodayData() { return this._fetch(this._getBjDateStr(0)); }
  async getYesterdayData() { return this._fetch(this._getBjDateStr(-1)); }

  async _fetch(dateStr) {
    try {
      console.log(`🔍 正在查询北京时间 ${dateStr} 的数据...`);
      const url = `/get?${new URLSearchParams({ date: dateStr })}`;
      const res = await this.request(url, { method: 'GET', timeout: 10000 });
      return res.ok ? await res.json() : [];
    } catch (e) {
      console.error(`Get Error: ${e.message}`);
      return [];
    }
  }
}

// 最终导出 (CommonJS)
module.exports = {
  CF_VID,
  CF_TOKEN,
  // 环境变量直接导出供主脚本初始化类使用
  URL_VID: process.env.WORKER_VID_URL,
  URL_TOKEN: process.env.WORKER_TOKEN_URL,
  API_KEY: process.env.API_KEY
};
