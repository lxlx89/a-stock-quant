# 迅股股 · 量化选股系统 交接文档

> 作者：刘迅 | 版本 v7.0 | 2026-05-14 | http://47.113.189.191

---

## 一、系统概述

A股 T+1 模拟盘（东方财富杯）量化选股系统，6大策略 + Web面板 + 截图识别持仓。

- **早盘推荐**（9:25）：强势股筛选，排除涨停
- **午间分析**（11:30）：持仓诊断 + 下午策略
- **一夜持股**（14:30）：尾盘选股 + 次日卖出计划
- **高换手猎手**：资金活跃短线爆发
- **低吸抄底**：缩量下跌博次日反弹
- **突破追涨**：放量突破惯性冲高

---

## 二、代码文件分布

### 核心模块 `src/`

| 文件 | 职责 | 关键函数 |
|------|------|----------|
| `src/fast_fetcher.py` | 主数据源，Sina API 10线程并发（4.5秒） | `fetch_realtime_quotes()` |
| `src/data_fetcher.py` | 备用数据源，AKShare | `fetch_history_kline()` |
| `src/stock_filter.py` | 清洗 + V2七维评分 + 一夜持股五重筛选 | `build_watchlist()`, `calculate_score_v2()`, `filter_overnight_candidates()` |
| `src/risk_control.py` | 风控评估 + 涨停检测 + 量能异常 | `assess_risks()`, `check_limit_up_risk()` |
| `src/strategy.py` | 策略引擎：买卖信号 + 三大推荐 | `generate_buy_signals()`, `generate_sell_signals()`, `generate_morning_recommendation()`, `generate_overnight_recommendation()` |
| `src/exporter.py` | Excel 导出（3 Sheet） | `export_to_excel()` |
| `src/utils.py` | 日志、格式化、交易时间判断 | `save_log()`, `is_trading_time()` |
| `src/network_diag.py` | 网络诊断（独立运行） | `run_diagnostic()` |

### 根目录脚本

| 文件 | 用途 |
|------|------|
| `main.py` | 本地7步管线（抓取→清洗→筛选→V2评分→风控→买卖信号→Excel） |
| `auto_morning.py` | 早盘自动推送（服务器 cron 9:25） |
| `backtest.py` | T+1策略回测 v2.0（Sharpe/最大回撤/Calmar），用法 `python backtest.py --days 30 --top 10` |
| `backtest_overnight.py` | 一夜持股专项回测（5/12→5/13 结果：止盈触发率 80%） |
| `overnight_test.py` | 一夜持股模拟交易 + 次日卖出场景分析 |
| `journal.py` | 交易日志 CLI：`python journal.py add/close/list/history` |
| `track.py` | 盘中持仓盈亏追踪：`python track.py 代码:成本:股数` |
| `monitor.py` | 单股价监控 + Windows弹窗 + QQ推送 |
| `config.py` | **集中配置文件**（筛选规则/评分权重/风控阈值/卖出规则/一夜持股参数/千问API Key） |

### Web 服务 `deploy/`

| 文件 | 说明 |
|------|------|
| `deploy/app.py` | **FastAPI 主程序**，全部 API + HTML 面板（~600行） |
| `deploy/deploy.sh` | 服务器 Docker 部署 |
| `deploy/upload.sh` | 本地上传脚本（scp） |
| `deploy/docker-compose.yml` | Docker Compose（app+nginx+postgres） |
| `deploy/nginx/nginx.conf` | Nginx 反向代理配置 |
| `deploy/requirements.txt` | 服务器 Python 依赖 |

### 数据文件 `data/`

| 路径 | 说明 |
|------|------|
| `data/trades.json` | 当前持仓（JSON） |
| `data/trade_history.json` | 历史交易记录 |
| `data/cache/stock_codes.json` | 股票代码缓存（6h TTL, ~5500只） |
| `data/outputs/` | Excel 导出 |
| `data/logs/run.log` | 运行日志 |

### 文档

| 文件 | 说明 |
|------|------|
| `HANDOFF.md` | **本文档**，完整交接说明 |
| `README.md` | 原始说明 |
| `REPORT.md` | 技术报告 |

---

## 三、服务器部署

- **IP**: 47.113.189.191
- **端口**: 80 (HTTP)
- **系统**: Ubuntu 22.04 (Aliyun ECS)
- **服务名**: `quant` (systemd)
- **项目目录**: `/opt/quant`
- **Python**: 3.10 (系统)

### 管理命令

```bash
systemctl restart quant      # 重启服务
systemctl status quant       # 查看状态
journalctl -u quant -n 30    # 最近30条日志
crontab -l                   # 查看定时任务
```

### 定时任务

```
25 1 * * 1-5   /usr/bin/python3 /opt/quant/auto_morning.py     # 09:25 早盘
30 14 * * 1-5  curl -s -X POST http://localhost/api/overnight   # 14:30 一夜持股
```

### 部署步骤

```bash
# 本地推送到服务器
scp config.py main.py auto_morning.py backtest.py root@47.113.189.191:/opt/quant/
scp src/*.py root@47.113.189.191:/opt/quant/src/
scp deploy/app.py root@47.113.189.191:/opt/quant/deploy/

# 服务器上重启
ssh root@47.113.189.191 "systemctl restart quant"
```

---

## 四、API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/morning` | 早盘推荐 |
| POST | `/api/midday` | 午间分析 |
| POST | `/api/overnight` | 一夜持股法 |
| POST | `/api/strategy/high-turnover` | 高换手猎手 |
| POST | `/api/strategy/oversold-bounce` | 低吸抄底 |
| POST | `/api/strategy/breakout` | 突破追涨 |
| POST | `/api/upload-positions` | 截图识别持仓（千问VL → OCR四层回退） |
| POST | `/api/positions/update` | 手动JSON更新持仓 |
| GET | `/api/result/{mode}` | 获取缓存结果 |

---

## 五、六大策略参数速查

### 1. 早盘推荐
涨幅 >= 2%, 成交额 >= 1亿, 换手率 >= 1%, 振幅 <= 15%
排除：涨停板（主板 10%/创业板 20%×95%阈值）、涨幅 > 8%
评分：V2七维（涨跌幅25%+成交额20%+换手率15%+振幅10%+量比10%+趋势10%+市值10%）

### 2. 午间分析
上午复盘总结 + 热点板块 + 持仓每只诊断 + 下午操作建议

### 3. 一夜持股法
涨幅 3%-5%, 换手率(主板>=3%/创业板>=5%, <=20%), 振幅 <=12%, 收盘/最高 >=94%
**次日**: 10:30前卖, 止盈+2%, 止损-1.5%, 低开>3%立刻离场
**回测**: 止盈触发率 80% (8/10)

### 4. 高换手猎手
换手率 5%-15%, 涨幅 2%-5%

### 5. 低吸抄底
跌幅 2%-7%, 换手率 2%-10%, 振幅 <=8%

### 6. 突破追涨
涨幅 4%-8%, 换手率 8%-20%, 收盘强度 >=95%

---

## 六、图片识别持仓

四层回退策略：
1. **千问 VL** (qwen-vl-max) — 最准，需 API Key
2. **Tesseract OCR 原始** — 直接识别
3. **Tesseract OCR 增强** — 灰度+对比度+锐化
4. **Tesseract OCR 模糊匹配** — 多PSM模式+宽松正则

API Key: `sk-2ef7c48f2b484c579127a367215bc74e` (千问 DashScope)

识别后自动数据校验：代码格式(6位数字)、成本范围(0.5-5000)、股数范围(100-10000000)

---

## 七、当前持仓（5/14 收盘）

| 代码 | 名称 | 股数 | 成本 | 现价 | 盈亏 |
|------|------|------|------|------|------|
| 300394 | 天孚通信 | 1000 | 373.54 | ~400 | +7% |
| 301308 | 江波龙 | 200 | 393.76 | ~614 | +56% |
| 600330 | 天通股份 | 6000 | 34.38 | ~34 | -0.1% |
| 002342 | 巨力索具 | 8700 | 24.87 | ~19 | -23% |

总市值 ~89万，可用 ~19万，总资产 ~108万

---

## 八、已知问题

1. **量比数据缺失** — Sina API 不返量比，一夜持股已跳过
2. **流通市值不可靠** — 已从一夜持股移除
3. **收盘后评分偏低** — 阈值已从65降到48，盘中会升高
4. **截图识别中文名偶尔不准** — 已加数据校验层
5. **SSH 端口不稳定** — 需阿里云安全组开放22端口

---

## 九、下一步计划

1. 明天验证一夜持股三只（筑博设计/海昌新材/广东明珠）
2. 加入北向资金/龙虎榜数据
3. QQ/微信推送通知
4. 移动端 WebView App
5. 持续优化一夜持股参数
