"""
策略回测 v2.0：选取 top-N 强势股，模拟卖出规则
用法: python backtest.py --days 30 --top 10
"""
import sys, os, json, time, argparse
import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SELL_RULES, TRADING_PARAMS, RISK_RULES


def get_stock_history_baostock(codes, days=10):
    """使用 BaoStock 拉取历史日K线"""
    try:
        import baostock as bs
    except ImportError:
        print("BaoStock not installed. pip install baostock")
        return {}

    bs.login()
    all_data = {}
    for i, code in enumerate(codes):
        try:
            clean = code.replace('sz','').replace('sh','').replace('bj','')
            if clean.startswith(('6','5')):
                bs_code = f'sh.{clean}'
            else:
                bs_code = f'sz.{clean}'
            rs = bs.query_history_k_data_plus(
                bs_code, 'date,open,high,low,close,volume,amount',
                frequency='d', adjustflag='2'
            )
            if rs.error_code == '0':
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    df = pd.DataFrame(rows, columns=rs.fields)
                    df['收盘'] = pd.to_numeric(df['close'], errors='coerce')
                    df['开盘'] = pd.to_numeric(df['open'], errors='coerce')
                    df['最高'] = pd.to_numeric(df['high'], errors='coerce')
                    df['最低'] = pd.to_numeric(df['low'], errors='coerce')
                    df = df.dropna(subset=['收盘','开盘'])
                    if len(df) >= 3:
                        all_data[code] = df.tail(days + 3)
        except Exception:
            pass
        if i % 50 == 0 and i > 0:
            print(f'  已拉取 {i}/{len(codes)}...')
    bs.logout()
    return all_data


def simulate_sell_rule(entry_price, day_data):
    """
    模拟卖出规则：
    - 次日开盘价买入参考
    - 检查止盈/止损触发
    - 返回卖出价和原因

    简化模拟：使用日内最高最低判断触发
    """
    if day_data.empty:
        return None

    open_price = day_data['开盘'].iloc[0]
    high = day_data['最高'].iloc[0]
    low = day_data['最低'].iloc[0]
    close = day_data['收盘'].iloc[0]

    # 检查止损（日内低点触发）
    if low <= entry_price * (1 + SELL_RULES['stop_loss'] / 100):
        sell_price = entry_price * (1 + SELL_RULES['stop_loss'] / 100)
        return {'sell_price': round(sell_price, 2), 'reason': '止损', 'ret': SELL_RULES['stop_loss']}

    if low <= entry_price * (1 + SELL_RULES['stop_loss_hard'] / 100):
        sell_price = entry_price * (1 + SELL_RULES['stop_loss_hard'] / 100)
        return {'sell_price': round(sell_price, 2), 'reason': '硬止损', 'ret': SELL_RULES['stop_loss_hard']}

    # 检查止盈（日内高点触发）
    if high >= entry_price * (1 + SELL_RULES['take_profit_full'] / 100):
        sell_price = entry_price * (1 + SELL_RULES['take_profit_full'] / 100)
        return {'sell_price': round(sell_price, 2), 'reason': '大涨止盈', 'ret': SELL_RULES['take_profit_full']}

    if high >= entry_price * (1 + SELL_RULES['take_profit'] / 100):
        sell_price = entry_price * (1 + SELL_RULES['take_profit'] / 100)
        return {'sell_price': round(sell_price, 2), 'reason': '止盈', 'ret': SELL_RULES['take_profit']}

    # 无触发：收盘卖出
    ret = (close - entry_price) / entry_price * 100
    return {'sell_price': round(close, 2), 'reason': '收盘卖出', 'ret': round(ret, 2)}


def backtest_with_sell_rules(hist_data, buy_date_idx, sell_date_idx):
    """
    用卖出规则回测：在 buy_date 收盘买入，sell_date 按规则卖出
    """
    results = []
    for code, df in hist_data.items():
        if len(df) <= max(buy_date_idx, sell_date_idx):
            continue
        buy_row = df.iloc[buy_date_idx]
        sell_day = df.iloc[sell_date_idx]
        buy_price = buy_row['收盘']
        if buy_price <= 0:
            continue

        # 构建卖出日的日内数据
        day_data = pd.DataFrame([{
            '开盘': sell_day['开盘'],
            '最高': sell_day['最高'],
            '最低': sell_day['最低'],
            '收盘': sell_day['收盘'],
        }])

        result = simulate_sell_rule(buy_price, day_data)
        if result:
            results.append({
                'code': code,
                'buy_date': str(buy_row.get('日期', '')),
                'buy_price': buy_price,
                'sell_price': result['sell_price'],
                'return': result['ret'],
                'sell_reason': result['reason'],
            })
    return pd.DataFrame(results)


def run_backtest(days=30, top_n=10, use_sell_rules=True):
    """回测主函数 v2.0"""
    print(f'回测参数: 过去{days}天, Top{top_n}只')
    print(f'卖出规则: {"启用" if use_sell_rules else "次日开盘卖"}')
    print()

    from src.fast_fetcher import fetch_realtime_quotes
    from src.stock_filter import load_and_clean, build_watchlist, calculate_score_v2
    from src.risk_control import assess_risks

    # Step 1: 股票池
    print('[1/4] 获取当前股票池...')
    df = fetch_realtime_quotes()
    df = load_and_clean(df)
    wl = build_watchlist(df)
    wl = calculate_score_v2(wl)
    wl = assess_risks(wl)

    pool = wl.head(200)
    codes = pool['代码'].tolist()
    print(f'  候选池: {len(codes)} 只')

    # Step 2: 拉历史数据
    print(f'[2/4] 拉取历史K线...')
    hist = get_stock_history_baostock(codes, days=days)
    print(f'  成功: {len(hist)} 只')

    # Step 3: 逐日回测
    print(f'[3/4] 逐日回测...')
    all_trades = []
    for d in range(1, days + 1):
        if use_sell_rules:
            bt = backtest_with_sell_rules(hist, buy_date_idx=-(d+1), sell_date_idx=-d)
        else:
            # Legacy: 次日开盘卖 (simple version)
            bt_trades = []
            for code_h, df_h in hist.items():
                if len(df_h) <= max(d+1, d):
                    continue
                br = df_h.iloc[-(d+1)]
                sr = df_h.iloc[-d]
                if br['收盘'] <= 0 or sr['开盘'] <= 0:
                    continue
                ret_v = (sr['开盘'] - br['收盘']) / br['收盘'] * 100
                bt_trades.append({'code': code_h, 'buy_date': str(br.get('日期','')),
                                  'buy_price': br['收盘'], 'sell_price': sr['开盘'],
                                  'return': ret_v, 'sell_reason': '次日开盘卖'})
            bt = pd.DataFrame(bt_trades)

        if len(bt) > 0:
            bt_sorted = bt.sort_values('return', ascending=False)
            picks = bt_sorted.head(top_n)
            for _, row in picks.iterrows():
                all_trades.append({
                    'date': row['buy_date'],
                    'code': row['code'],
                    'buy': row['buy_price'],
                    'sell': row['sell_price'],
                    'ret': row['return'],
                    'reason': row.get('sell_reason', '次日开盘卖'),
                })

    if not all_trades:
        print('无交易数据')
        return pd.DataFrame()

    results = pd.DataFrame(all_trades)

    # Step 4: 统计
    print()
    print('=' * 60)
    print(f'回测结果: {len(results)} 笔交易')
    print('=' * 60)

    returns = results['ret'].values
    wins = sum(returns > 0)
    win_rate = wins / len(returns) * 100
    avg_ret = np.mean(returns)
    total_ret = np.sum(returns)
    max_win = np.max(returns)
    max_loss = np.min(returns)
    std_ret = np.std(returns, ddof=1)

    # Sharpe ratio (annualized, approximate)
    sharpe = (avg_ret / std_ret) * np.sqrt(250) if std_ret > 0 else 0

    # Max drawdown
    cum_returns = np.cumsum(returns)
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = cum_returns - running_max
    max_drawdown = np.min(drawdowns)

    # Calmar ratio
    calmar = total_ret / abs(max_drawdown) if max_drawdown < 0 else total_ret

    print(f'胜率: {wins}/{len(returns)} = {win_rate:.1f}%')
    print(f'平均收益: {avg_ret:+.2f}%')
    print(f'累计收益: {total_ret:+.2f}%')
    print(f'最大单笔盈利: {max_win:+.2f}%')
    print(f'最大单笔亏损: {max_loss:+.2f}%')
    print(f'标准差: {std_ret:.2f}%')
    print(f'Sharpe比率(年化): {sharpe:.2f}')
    print(f'最大回撤: {max_drawdown:+.2f}%')
    print(f'Calmar比率: {calmar:.2f}')

    # 卖出原因分布
    if use_sell_rules and 'reason' in results.columns:
        print()
        print('卖出原因分布:')
        for reason, count in results['reason'].value_counts().items():
            avg_r = results[results['reason'] == reason]['ret'].mean()
            print(f'  {reason}: {count}笔, 均{avg_r:+.2f}%')

    # 逐日
    print()
    print('逐日表现:')
    for d in sorted(results['date'].unique()):
        day_trades = results[results['date'] == d]
        avg_r = day_trades['ret'].mean()
        print(f'  {d}: {len(day_trades)}笔, 均{avg_r:+.2f}%')

    # 评估
    print()
    if win_rate > 55 and avg_ret > 0.3 and sharpe > 0.5:
        print('评估: ★★★ 策略有效，胜率、正期望、夏普均达标')
    elif win_rate > 50 and avg_ret > 0:
        print('评估: ★★☆ 策略勉强有效，建议优化参数')
    else:
        print('评估: ★☆☆ 策略效果不佳')

    # 保存报告
    report = {
        'params': {'days': days, 'top_n': top_n, 'use_sell_rules': use_sell_rules},
        'summary': {
            'total_trades': len(returns),
            'wins': int(wins),
            'win_rate': round(win_rate, 1),
            'avg_return': round(avg_ret, 2),
            'total_return': round(total_ret, 2),
            'max_win': round(max_win, 2),
            'max_loss': round(max_loss, 2),
            'sharpe': round(sharpe, 2),
            'max_drawdown': round(max_drawdown, 2),
            'calmar': round(calmar, 2),
        },
        'trades': results.to_dict('records'),
    }

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'backtest_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'\n报告已保存: {report_path}')

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='量化策略回测 v2.0')
    parser.add_argument('--days', type=int, default=30, help='回测天数')
    parser.add_argument('--top', type=int, default=10, help='每日选股数')
    parser.add_argument('--no-sell-rules', action='store_true', help='禁用卖出规则，改用次日开盘卖')
    args = parser.parse_args()
    run_backtest(days=args.days, top_n=args.top, use_sell_rules=not args.no_sell_rules)
