"""
早盘自动推送 v3.0 — 9:25 运行，精选推荐推送到服务器面板
用法: python auto_morning.py
"""
import sys, os, json, requests, urllib3
from datetime import datetime

urllib3.disable_warnings()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

from src.fast_fetcher import fetch_realtime_quotes
from src.stock_filter import load_and_clean, build_watchlist, sector_strength_analysis, calculate_score_v2, filter_momentum_stocks
from src.risk_control import assess_risks
from src.strategy import generate_morning_recommendation, generate_buy_signals, get_positions

SERVER = "https://47.113.189.191"
print(f"[{datetime.now():%H:%M:%S}] 早盘分析 v3.0 启动...")

# 1. 数据抓取 + 清洗 + 筛选
df = fetch_realtime_quotes()
df = load_and_clean(df)
wl = build_watchlist(df)
wl = calculate_score_v2(wl)
wl = assess_risks(wl)
wl = filter_momentum_stocks(wl)
sectors = sector_strength_analysis(wl)

# 2. 精选推荐（策略引擎）
recs = generate_morning_recommendation(wl)
buy_signals = generate_buy_signals(wl, get_positions())

# 3. 生成报告
top = wl.head(8)
lines = [
    f"=== {datetime.now():%m月%d日 %H:%M} 早盘快报 v3.0 ===",
    f"全市场{len(df)} | 强势股{len(wl)}",
    f"低风险{len(wl[wl['risk_level']=='低风险'])} | 中风险{len(wl[wl['risk_level']=='中风险'])} | 高风险{len(wl[wl['risk_level']=='高风险'])}",
    "",
    "=== 精选推荐（优先低风险+高评分）===",
]
for i, r in enumerate(recs):
    lines.append(f"  #{i+1} {r['code']} {r['name']} ¥{r['price']} {r['chg']:+.2f}% sc:{r['score']} {r['risk']} | {r['reason']}")

lines.append("")
lines.append("=== Top 8 强势股 ===")
for _, row in top.iterrows():
    code = str(row["代码"]).replace("sz","").replace("sh","").replace("bj","")
    name = str(row["名称"])[:6]
    momentum = str(row.get("momentum_tag", ""))
    lines.append(f"  {code} {name} {row['最新价']:.2f} {row['涨跌幅']:+.2f}% sc:{row['score']:.0f} {row['risk_level']} {momentum}")

if buy_signals:
    lines.append("")
    lines.append("=== 买入信号 ===")
    for s in buy_signals[:5]:
        lines.append(f"  {s['code']} {s['name']} ¥{s['price']} sc:{s['score']} {s['shares']}股 ~{s['cost']/1e4:.1f}万")

if len(sectors) > 0:
    lines.append("")
    lines.append("=== 强势板块 ===")
    for _, row in sectors.head(5).iterrows():
        lines.append(f"  {str(row.iloc[0]):<10s} {int(row['入选数量'])}只 均{row.get('涨跌幅',0):+.2f}%")

report = "\n".join(lines)
print(report)

# 4. 推送到服务器
try:
    payload = {"report": report, "recommendations": recs}
    r = requests.post(f"{SERVER}/api/morning", json=payload, verify=False, timeout=15)
    if r.status_code == 200:
        # 同时触发服务器上的早盘扫描
        requests.post(f"{SERVER}/api/morning/run", verify=False, timeout=30)
        print(f"面板已更新: {SERVER}")
    else:
        print(f"推送返回 {r.status_code}")
except Exception as e:
    print(f"推送失败: {e}")

# 5. 本地保存
os.makedirs("data", exist_ok=True)
with open("data/morning_report.txt", "w", encoding="utf-8") as f:
    f.write(report)

print(f"[{datetime.now():%H:%M:%S}] 完成 — {SERVER}")
