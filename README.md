# 迅股股 · A股量化选股系统 v7.0

> 刘迅的量化选股助手 | 东方财富杯模拟盘 | http://47.113.189.191

**6大策略 · Web面板 · 截图识别持仓 · 定时自动扫描 · 一夜持股回测**

---

## 快速开始

```bash
# 本地运行
cd D:\code\a_stock_quant_assistant
pip install akshare pandas openpyxl baostock
python main.py

# 启动 Web 服务
cd deploy && python app.py
```

访问 `http://47.113.189.191` 打开 Web 面板。

---

## 六大策略

| 策略 | 时间 | 说明 |
|------|------|------|
| ☼ **早盘推荐** | 9:25 | 强势股筛选，排除涨停/涨幅>8%，V2七维评分 |
| ☀ **午间分析** | 11:30 | 上午复盘 + 持仓诊断 + 下午策略建议 |
| ☽ **一夜持股** | 14:30 | 尾盘五重筛选 + 次日止盈止损计划（回测胜率80%触发止盈）|
| 📈 **高换手猎手** | 盘中 | 换手5-15%+涨幅2-5%，资金活跃短线爆发 |
| 📉 **低吸抄底** | 盘中 | 缩量下跌企稳，博次日反弹 |
| 🚀 **突破追涨** | 盘中 | 放量突破+强势收盘，次日惯性冲高 |

---

## 目录结构

```
a_stock_quant_assistant/
├── main.py                    # 本地7步管线
├── config.py                  # 集中配置（策略参数/API Key）
├── auto_morning.py            # 早盘自动推送（cron 9:25）
├── backtest.py                # T+1回测 v2.0（Sharpe/最大回撤）
├── backtest_overnight.py      # 一夜持股专项回测
├── journal.py                 # 交易日志CLI
├── track.py                   # 盘中持仓追踪
├── monitor.py                 # 价格监控+QQ推送
│
├── src/
│   ├── fast_fetcher.py        # Sina API 10线程并发（4.5秒）
│   ├── data_fetcher.py        # AKShare 备用数据源
│   ├── stock_filter.py        # 清洗+V2七维评分+一夜持股筛选
│   ├── strategy.py            # 策略引擎（买卖信号/推荐生成）
│   ├── risk_control.py        # 风控+涨停检测+量能异常
│   ├── exporter.py            # Excel 导出
│   └── utils.py               # 工具函数
│
├── deploy/
│   ├── app.py                 # FastAPI Web 主程序
│   ├── deploy.sh              # Docker 部署
│   └── upload.sh              # SCP 上传
│
├── data/
│   ├── trades.json            # 当前持仓
│   ├── trade_history.json     # 历史交易
│   ├── cache/                 # 代码缓存
│   └── outputs/               # Excel 导出
│
├── README.md                  # 本文件
├── HANDOFF.md                 # 完整交接文档
└── REPORT.md                  # 技术报告
```

---

## 一夜持股法（核心策略）

基于业界最佳实践，五重筛选：

| 条件 | 参数 |
|------|------|
| 涨幅 | 3% - 5% |
| 换手率 | 主板 >= 3%, 创业板 >= 5%, <= 20% |
| 振幅 | <= 12% |
| 收盘强度 | 收盘/最高 >= 94% |
| 成交额 | >= 1亿 |

次日操作：10:30前卖出，止盈 +2%，止损 -1.5%，低开 >3% 立刻离场。

**回测结果（2026-05-12 → 05-13）**：止盈触发率 80%（8/10只盘中触达+2%），开盘卖出胜率 30%。

---

## Web API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/morning` | 早盘推荐 |
| POST | `/api/midday` | 午间分析 |
| POST | `/api/overnight` | 一夜持股法 |
| POST | `/api/strategy/high-turnover` | 高换手猎手 |
| POST | `/api/strategy/oversold-bounce` | 低吸抄底 |
| POST | `/api/strategy/breakout` | 突破追涨 |
| POST | `/api/upload-positions` | 截图识别持仓（千问VL+OCR） |
| POST | `/api/positions/update` | JSON 手动更新持仓 |

---

## 服务器

- **地址**: 47.113.189.191:80 (HTTP)
- **系统**: Ubuntu 22.04 (Aliyun ECS)
- **服务**: systemd `quant`
- **定时**: 9:25 早盘 + 14:30 一夜持股
- **管理**: `systemctl restart quant`

详细部署说明见 `HANDOFF.md`。

---

## 注意事项

1. 仅供学习研究和模拟交易辅助，不构成投资建议
2. 不自动下单，不接券商交易接口
3. 一夜持股需配合次日盘中止盈纪律执行
4. 截图识别含千问 API Key，勿泄露
