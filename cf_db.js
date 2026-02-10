/**
 * 基础请求客户端
 */
class BaseClient {
  constructor(baseUrl, apiKey) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.headers = {
      'Authorization': apiKey.startsWith('Bearer ') ? apiKey : `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    };
  }

  /**
   * 核心请求封装，包含超时处理
   */
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
export class CF_VID extends BaseClient {
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
 * Token 数据上传与查询类（支持北京时区）
 */
export class CF_TOKEN extends BaseClient {
  /**
   * 获取北京时间的格式化字符串 (MM_DD)
   * @param {number} offsetDays 相对今天的偏移天数
   */
  _getBjDateStr(offsetDays = 0) {
    const now = new Date();
    if (offsetDays !== 0) now.setDate(now.getDate() + offsetDays);
    
    // 强制转换为北京时间并提取月日
    const formatter = new Intl.DateTimeFormat('en-GB', {
      month: '2-digit',
      day: '2-digit',
      timeZone: 'Asia/Shanghai'
    });
    
    // 格式化结果通常为 "DD/MM"，这里通过 parts 确保顺序正确
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

  async getTodayData() {
    return this._fetch(this._getBjDateStr(0));
  }

  async getYesterdayData() {
    return this._fetch(this._getBjDateStr(-1));
  }

  async _fetch(dateStr) {
    try {
      console.log(`🔍 正在查询北京时间 ${dateStr} 的数据...`);
      // 构建带 query 字典的 URL
      const url = `/get?${new URLSearchParams({ date: dateStr })}`;
      const res = await this.request(url, { method: 'GET', timeout: 10000 });
      
      return res.ok ? await res.json() : [];
    } catch (e) {
      console.error(`Get Error: ${e.message}`);
      return [];
    }
  }
}
// cf_db.js
module.exports = {
  CF_VID: process.env.WORKER_VID_URL || '默认值',
  CF_TOKEN: process.env.WORKER_TOKEN_URL || '默认值'
};
