"""
一夜持股回测：前天尾盘买入 → 昨天开盘/盘中卖出
用法: python backtest_overnight.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import baostock as bs
import pandas as pd
import numpy as np
from config import OVERNIGHT_RULES

rules = OVERNIGHT_RULES
TP_PCT = rules['next_day']['take_profit'] / 100  # 2%
SL_PCT = rules['next_day']['stop_loss'] / 100    # -1.5%

print("=" * 55)
print("  一夜持股回测：前天买入 → 昨天卖出")
print(f"  止盈 +{TP_PCT*100}%  止损 {SL_PCT*100}%")
print("=" * 55)

# ====== Step 1: 获取前天的强势股列表 ======
print("\n[1/3] 获取全市场股票代码...")

# 用常见的 A 股代码列表（取市值前500的活跃股 + 近期强势股）
# 先用今天的数据跑一遍一夜持股，拿到候选风格
from src.fast_fetcher import fetch_realtime_quotes
from src.stock_filter import load_and_clean, build_watchlist

df_today = fetch_realtime_quotes()
df_today = load_and_clean(df_today)
wl_today = build_watchlist(df_today)
pool_codes = wl_today['代码'].tolist()[:300]  # 取前300只活跃股回测

print(f"  回测候选池: {len(pool_codes)} 只活跃股")

# ====== Step 2: 拉前2天日K线 + 昨天5分钟线 ======
print("\n[2/3] 拉取历史数据...")

bs.login()
daily_data = {}
min5_data = {}

for i, code in enumerate(pool_codes):
    try:
        clean = code.replace('sz','').replace('sh','').replace('bj','')
        if clean.startswith(('6','5')):
            bs_code = f'sh.{clean}'
        else:
            bs_code = f'sz.{clean}'

        # 日K线（前3天）
        rs = bs.query_history_k_data_plus(
            bs_code, 'date,open,high,low,close,volume,amount',
            start_date='2026-05-10', end_date='2026-05-14',
            frequency='d', adjustflag='2'
        )
        if rs.error_code == '0':
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if len(rows) >= 3:
                df = pd.DataFrame(rows, columns=rs.fields)
                for col in ['open','high','low','close']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                daily_data[code] = df

        # 昨天5分钟线（判断是否触发止盈）
        rs5 = bs.query_history_k_data_plus(
            bs_code, 'time,open,high,low,close',
            start_date='2026-05-13', end_date='2026-05-13',
            frequency='5', adjustflag='2'
        )
        if rs5.error_code == '0':
            rows5 = []
            while rs5.next():
                rows5.append(rs5.get_row_data())
            if rows5:
                df5 = pd.DataFrame(rows5, columns=rs5.fields)
                for col in ['open','high','low','close']:
                    df5[col] = pd.to_numeric(df5[col], errors='coerce')
                min5_data[code] = df5
    except:
        pass

    if i % 50 == 0 and i > 0:
        print(f"  {i}/{len(pool_codes)}...")

bs.logout()
print(f"  日线数据: {len(daily_data)} 只")
print(f"  5分钟线: {len(min5_data)} 只")

# ====== Step 3: 应用一夜持股筛选 + 回测 ======
print("\n[3/3] 回测...")

# 前天 = 倒数第2个交易日 (May 12)
# 昨天 = 倒数第1个交易日 (May 13)
# 先筛选：前天收盘价满足一夜持股条件

candidates = []
for code, df_d in daily_data.items():
    if len(df_d) < 3:
        continue

    # 前天 = 倒数第2行, 大前天 = 倒数第3行
    day_before = df_d.iloc[-2]  # May 12 close
    yesterday = df_d.iloc[-1]   # May 13 open/close
    day_3 = df_d.iloc[-3]       # May 11

    pre_close = day_3['close']  # 前前天收盘
    buy_close = day_before['close']  # 前天收盘 = 买入价
    buy_high = day_before['high']
    buy_open = day_before['open']

    if buy_close <= 0 or pre_close <= 0:
        continue

    # 涨跌幅 = (前收 - 前前收) / 前前收 * 100
    chg_pct = (buy_close - pre_close) / pre_close * 100

    # 振幅
    amp = (buy_high - day_before['low']) / pre_close * 100

    # 收盘强度
    close_strength = buy_close / buy_high if buy_high > 0 else 0.9

    # 一夜持股筛选条件
    if not (rules['rise_min'] <= chg_pct <= rules['rise_max']):
        continue
    if amp > rules['amplitude_max']:
        continue
    if close_strength < rules['close_near_high']:
        continue

    candidates.append({
        'code': code,
        'buy_price': buy_close,
        'pre_close': pre_close,
        'chg_pct': chg_pct,
        'amp': amp,
        'close_strength': close_strength,
    })

print(f"\n  一夜持股候选: {len(candidates)} 只")

if not candidates:
    print("  无候选！可能前天国定假日或数据不足")
    sys.exit(0)

# 按收盘强度排序，取前10
candidates.sort(key=lambda x: x['close_strength'], reverse=True)
top10 = candidates[:10]

print(f"\n  Top 10 (按收盘强度):")

results = []
for c in top10:
    code = c['code']
    buy_price = c['buy_price']

    # 昨天日线
    df_d = daily_data[code]
    yesterday_open = df_d.iloc[-1]['open']
    yesterday_high = df_d.iloc[-1]['high']
    yesterday_low = df_d.iloc[-1]['low']
    yesterday_close = df_d.iloc[-1]['close']

    # 开盘卖出收益
    open_ret = (yesterday_open - buy_price) / buy_price * 100

    # 检查日内是否触发止盈/止损
    tp_price = buy_price * (1 + TP_PCT)
    sl_price = buy_price * (1 + SL_PCT)

    hit_tp = False
    hit_sl = False
    tp_time = ''
    sl_time = ''

    if code in min5_data:
        df5 = min5_data[code]
        for _, bar in df5.iterrows():
            if bar['high'] >= tp_price:
                hit_tp = True
                tp_time = str(bar['time'])
                break
            if bar['low'] <= sl_price:
                hit_sl = True
                sl_time = str(bar['time'])
                break

    # 高开情况
    gap = (yesterday_open - buy_price) / buy_price * 100

    result = {
        'code': code,
        'buy_price': buy_price,
        'chg': c['chg_pct'],
        'close_str': c['close_strength'],
        'y_open': yesterday_open,
        'y_high': yesterday_high,
        'y_low': yesterday_low,
        'y_close': yesterday_close,
        'open_ret': open_ret,
        'gap': gap,
        'hit_tp': hit_tp,
        'hit_sl': hit_sl,
        'tp_time': tp_time,
        'sl_time': sl_time,
    }
    results.append(result)

# 打印结果
print(f"  {'代码':<10} {'涨幅%':>6} {'收盘强度':>7} {'开盘价':>7} {'开盘盈亏%':>8} {'触止盈':>6} {'触止损':>6} {'最高价':>7}")
print(f"  {'-'*10} {'-'*6} {'-'*7} {'-'*7} {'-'*8} {'-'*6} {'-'*6} {'-'*7}")
wins = 0
losses = 0
tp_hits = 0
sl_hits = 0

for r in results:
    tp_str = 'TP ' + r['tp_time'] if r['hit_tp'] else '--'
    sl_str = 'SL ' + r['sl_time'] if r['hit_sl'] else '--'
    if r['hit_tp']:
        tp_hits += 1
    if r['hit_sl']:
        sl_hits += 1
    if r['open_ret'] > 0:
        wins += 1
    else:
        losses += 1
    print(f"  {r['code']:<10} {r['chg']:>+5.1f}% {r['close_str']:>6.1f}% {r['y_open']:>7.2f} {r['open_ret']:>+7.2f}% {tp_str:>6} {sl_str:>6} {r['y_high']:>7.2f}")

print()
print(f"  胜率(开盘卖): {wins}/{len(results)} = {wins/len(results)*100:.1f}%")
print(f"  触发止盈: {tp_hits}只  触发止损: {sl_hits}只")
avg_ret = np.mean([r['open_ret'] for r in results])
print(f"  平均开盘收益: {avg_ret:+.2f}%")

# 止盈触发时间分布
if tp_hits > 0:
    print()
    print("  止盈触发详情:")
    for r in results:
        if r['hit_tp']:
            print(f"    {r['code']} 买入{r['buy_price']:.2f} 止盈价{r['buy_price']*1.02:.2f} 触发时间:{r['tp_time']}")

print()
print("=" * 55)
print("  结论：")
if avg_ret > 0.5 and tp_hits >= 3:
    print(f"  策略有效！均收益{avg_ret:+.2f}%，{tp_hits}只触发止盈")
elif avg_ret > 0:
    print(f"  策略勉强有效，均收益{avg_ret:+.2f}%，可优化参数")
else:
    print(f"  策略需要优化，均收益{avg_ret:+.2f}%")
print("=" * 55)
