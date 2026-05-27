# 迅股股 · 量化选股系统 交接文档

> 作者：刘迅 | 版本 v7.1 | 2026-05-28 | https://lhz456.xyz

---

## 一、系统概述

A股 T+1 模拟盘（东方财富杯）量化选股系统，**6 策略** + Web 面板 + 截图识别持仓 + GitHub 自动同步。

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
| `src/fast_fetcher.py` | 主数据源：Sina + **Tencent(qt.gtimg.cn)** + Cache | `fetch_realtime_quotes_sina()`, `fetch_realtime_quotes_tencent()`, `fetch_realtime_quotes_cache()` |
| `src/data_fetcher.py` | 备用数据源：AKShare/Eastmoney | `fetch_realtime_quotes_eastmoney()`, `fetch_history_kline()` |
| `src/__init__.py` | **多数据源 Fallback 链**：sina → tencent → eastmoney → cache | `fetch_realtime_quotes()` |
| `src/stock_filter.py` | 清洗 + V2七维评分 + 一夜持股五重筛选 | `build_watchlist()`, `calculate_score_v2()`, `filter_overnight_candidates()` |
| `src/risk_control.py` | 风控评估 + 涨停检测 + 量能异常 | `assess_risks()`, `check_limit_up_risk()` |
| `src/strategy.py` | 策略引擎：买卖信号 + 三大推荐 | `generate_buy_signals()`, `generate_sell_signals()`, `generate_morning_recommendation()` |
| `src/db.py` | PostgreSQL 持久化（可选）+ JSON 回退 | `save_trade()`, `load_trades()` |
| `src/market_regime.py` | 市场状态识别（牛市/熊市/震荡） | |
| `src/exporter.py` | Excel 导出（3 Sheet） | `export_to_excel()` |
| `src/utils.py` | 日志、格式化、交易时间判断 | `save_log()`, `is_trading_time()` |

### 根目录脚本

| 文件 | 用途 |
|------|------|
| `main.py` | 本地7步管线 |
| `auto_morning.py` | 早盘自动推送（服务器 cron 9:25） |
| `backtest.py` | T+1策略回测 v2.0 |
| `config.py` | **集中配置文件**（数据源顺序/评分权重/风控阈值/API Key） |
| `deploy_now.py` | 本地一键部署（SSH→SFTP→Docker重建）**[不提交Git]** |

### Web 服务 `deploy/`

| 文件 | 说明 |
|------|------|
| `deploy/app.py` | **FastAPI 主程序**，6策略 API + HTML 面板（~900行） |
| `deploy/Dockerfile` | Docker 镜像（python:3.10-slim + uvicorn） |
| `deploy/docker-compose.yml` | Docker Compose（app + nginx + postgres） |
| `deploy/nginx/nginx.conf` | Nginx 反向代理（lhz456.xyz → app:8000） |
| `deploy/requirements.txt` | **服务器 Python 依赖**（含 akshare, python-multipart） |
| `deploy/update.sh` | **服务器端一键更新脚本**（git pull + Docker rebuild） |

---

## 三、服务器部署（2026-05-28 重构）

### 服务器信息
- **IP**: 47.113.189.191 | **域名**: lhz456.xyz
- **系统**: Ubuntu 22.04 (Aliyun ECS, 深圳)
- **项目目录**: `/opt/quant`
- **部署方式**: Docker Compose（**不再是 systemd**）

### Docker 服务

| 容器 | 端口 | 说明 |
|------|------|------|
| quant-app | 8000 (内部) | FastAPI + uvicorn |
| quant-nginx | 80, 443 | Nginx 反向代理 |
| quant-db | 5432 (127.0.0.1) | PostgreSQL 16 (可选, DB_ENABLED=false) |

### 管理命令

```bash
# 查看服务状态
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 重启单个服务
cd /opt/quant && docker compose -f deploy/docker-compose.yml restart app

# 重建并重启（代码更新后）
cd /opt/quant && docker compose -f deploy/docker-compose.yml up -d --build app

# 查看日志
docker logs quant-app --tail 50

# 健康检查
curl http://localhost/api/health
```

### 定时任务（crontab）

```
25 1 * * 1-5  cd /opt/quant && /usr/bin/python3 /opt/quant/auto_morning.py >> /opt/quant/data/morning_cron.log 2>&1
30 14 * * 1-5  curl -s -X POST http://localhost/api/overnight > /dev/null 2>&1
```

**注意**: auto_morning.py 在主机运行（不经过Docker），依赖主机 Python3 + 依赖包。

---

## 四、数据源架构（重要!）

### Fallback 链

```
sina (vip.stock.finance.sina.com.cn, 并行, ~5s)
  ↓ 失败
tencent (qt.gtimg.cn, 并行, ~8s)      ← 2026-05-28 新增
  ↓ 失败
eastmoney (akshare, ~30s)
  ↓ 失败
cache (本地 parquet, 4h TTL)
```

### 数据源详情

| 数据源 | API | 格式 | 速度 | 阿里云可用? |
|--------|-----|------|------|-------------|
| Sina | `vip.stock.finance.sina.com.cn` | JSON | ~5s | **否**（被Sina防火墙拦截） |
| **Tencent** | `qt.gtimg.cn` | GBK文本 (`~`分隔) | ~8s | **是！** |
| Eastmoney | akshare → `push2.eastmoney.com` | DataFrame | ~30s | **否**（连接被拒） |
| Cache | 本地 parquet | DataFrame | 即时 | 是（过期4h后无用） |

### 腾讯数据源字段映射

Tencent API 返回 88 字段，关键索引：
```
[3]=最新价 [4]=昨收 [5]=今开 [6]=成交量(手) [31]=涨跌幅
[32]=涨跌额 [33]=最高 [34]=最低 [38]=换手率 [39]=市盈率
[43]=振幅 [44]=总市值(亿) [45]=流通市值(亿) [46]=市净率
[57]=成交额(万)
```

实现在 `src/fast_fetcher.py` 的 `fetch_realtime_quotes_tencent()`。

---

## 五、GitHub 同步工作流（2026-05-28 新增）

### 仓库
- **地址**: https://github.com/lxlx89/a-stock-quant (私有)
- **分支**: `main`
- **认证**: SSH Key（本地 + 服务器 Deploy Key）

### 日常更新流程

```bash
# 1. 本地修改代码后
git add .
git commit -m "描述改动"
git push

# 2. 服务器拉取并重建
ssh root@47.113.189.191 "cd /opt/quant && bash deploy/update.sh"
```

`deploy/update.sh` 做了：
1. `git pull origin main` — 拉取最新代码
2. `docker compose build app` — 重建 Docker 镜像
3. `docker compose up -d` — 重启服务
4. 健康检查

### 注意事项
- `.env` 和 `data/` 目录在 `.gitignore` 中，不会被覆盖
- `deploy_now.py` 不在 Git 中（含密码），仅本地使用
- 服务器初次设置部署密钥：https://github.com/lxlx89/a-stock-quant/settings/keys

---

## 六、部署排障记录（2026-05-28）

### 问题 1：端口 80 被占用
**现象**: Docker nginx 无法启动 `address already in use`
**原因**: 旧的 `systemd quant` 服务直接在主机运行 `uvicorn --port 80`
**解决**: `systemctl stop quant && systemctl disable quant`

### 问题 2：Docker 镜像缺少依赖
**现象**: `RuntimeError: Form data requires "python-multipart"`
**修复**: 添加到 `deploy/requirements.txt`

### 问题 3：Dockerfile 复制错 requirements.txt
**现象**: 复制的是根目录 `requirements.txt`（本地依赖），缺 `fastapi`/`uvicorn`
**修复**: 改为 `COPY deploy/requirements.txt`

### 问题 4：所有数据源在服务器上失败
**现象**: Sina 返回 Forbidden，Eastmoney 连接被拒
**根因**: 阿里云 ECS 的 IP 被 Sina/Eastmoney 防火墙限制
**解决**: 新增腾讯 `qt.gtimg.cn` 数据源作为主要回退

### 问题 5：akshare 不在服务器依赖中
**现象**: Eastmoney 回退失败 "未安装 akshare 库"
**修复**: 添加 `akshare>=1.10.0` 到 `deploy/requirements.txt`

---

## 七、API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 `{"status":"ok","version":"7.0"}` |
| POST | `/api/morning` | 早盘推荐（集合竞价后精选，排除涨停） |
| POST | `/api/midday` | 午间分析（持仓诊断 + 下午建议） |
| POST | `/api/overnight` | 一夜持股法（尾盘精选 + 明日卖出计划） |
| POST | `/api/strategy/high-turnover` | 高换手猎手（换手5-15%，涨幅2-5%） |
| POST | `/api/strategy/oversold-bounce` | 低吸抄底（跌幅2-7%，博次日反弹） |
| POST | `/api/strategy/breakout` | 突破追涨（放量上攻+强势收盘） |
| POST | `/api/upload-positions` | 截图识别持仓（千问VL → OCR三层回退） |
| POST | `/api/positions/update` | 手动JSON更新持仓 |
| GET | `/api/result/{mode}` | 获取上次缓存结果 |

---

## 八、图片识别持仓（四层回退）

1. **千问 VL** (qwen-vl-max) — AI视觉识别，最准
2. **Tesseract OCR 原始** — 直接 OCR
3. **Tesseract OCR 增强** — 灰度 + 对比度增强 + 锐化
4. **Tesseract OCR 模糊匹配** — 多 PSM 模式 + 宽松正则

识别后数据校验：代码格式(6位, 00/30/60/68开头)、成本范围(0.5-5000)、股数范围(100-10M)

**已知局限**: 中文名识别不准（尤其截图模糊时），建议后续升级 AI 模型或加手动编辑界面。

---

## 九、Web 面板前端（纯 HTML/CSS/JS，无框架）

`deploy/app.py` 的 `dashboard()` 返回完整 HTML，包含：
- **6 策略按钮**（3列2行网格布局）
- 推荐列表渲染（评分/换手/成交额/涨跌幅）
- 持仓分析卡片（卖/警戒/持有 三色边框）
- 板块热度标签
- 截图上传区
- Toast 通知

JavaScript 关键函数：
- `runMode(mode)` — 调用 API 并渲染
- `getApi(mode)` — 区分 `/api/` vs `/api/strategy/` 路径
- `render(d)` — 统一渲染引擎（处理 6 种 type）
- `doUpload(inp)` — 截图上传 + 自动刷新持仓

---

## 十、已知问题

1. ~~Sina API 在服务器不可用~~ → 已加腾讯数据源回退
2. ~~Eastmoney API 在服务器不可用~~ → 同上
3. 量比数据缺失 — Sina/Tencent 均不返回量比
4. 截图识别中文名偶尔不准 — 需优化 AI 模型
5. auto_morning.py cron 依赖主机 Python3 环境 — 未来可迁移到 Docker 内执行

---

## 十一、环境变量 (.env)

服务器 `/opt/quant/.env` 需配置：
```
QWEN_API_KEY=sk-xxx          # 千问 API Key（截图识别用）
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-vl-max
DEPLOY_HOST=47.113.189.191
DEPLOY_USER=root
DEPLOY_PASSWORD=xxx
DB_ENABLED=false
```

---

## 十二、下一步计划

1. 优化截图识别（换更强模型 或 加手动编辑 UI）
2. 将 auto_morning.py 迁移到 Docker 内执行
3. 移动端适配 / PWA
4. 加入北向资金/龙虎榜数据
5. 推送通知（微信/QQ）
