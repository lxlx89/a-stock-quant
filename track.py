"""
盘中持仓追踪脚本
用法：
  python track.py 301308:533.133:500 300394:357.539:500 600330:34.379:6000 002342:22.046:17500
  格式: 代码:成本:股数
"""
import sys
from src.fast_fetcher import fetch_realtime_quotes
from src.stock_filter import load_and_clean

def clean_code(c):
    """去掉 sz/sh/bj 前缀，只留数字"""
    for p in ['sz','sh','bj','SZ','SH','BJ']:
        if c.startswith(p):
            return c[len(p):]
    return c

def parse_args():
    positions = []
    for arg in sys.argv[1:]:
        parts = arg.split(':')
        if len(parts) >= 2:
            code = parts[0]
            cost = float(parts[1])
            shares = int(parts[2]) if len(parts) >= 3 else 100
            positions.append((code, cost, shares))
    return positions

def track(positions):
    df = fetch_realtime_quotes()
    df = load_and_clean(df)

    total_pnl = 0
    print(f'{"代码":<10s} {"名称":<8s} {"现价":>7s} {"涨幅":>7s} {"换手":>6s} {"成本":>7s} {"浮盈%":>7s} {"盈亏":>8s}')
    print('-' * 70)

    for code_in, cost, shares in positions:
        matched = df[df['代码'].apply(lambda x: clean_code(str(x)) == clean_code(code_in))]
        if len(matched) > 0:
            r = matched.iloc[0]
            price = r['最新价']
            chg = r['涨跌幅']
            turnover = r.get('换手率', 0)
            pnl_pct = (price - cost) / cost * 100
            pnl_amt = (price - cost) * shares
            total_pnl += pnl_amt
            code_s = clean_code(str(r['代码']))
            name = str(r['名称'])[:6]
            print(f'{code_s:<10s} {name:<8s} {price:>7.2f} {chg:>+6.2f}% {turnover:>5.1f}% {cost:>7.2f} {pnl_pct:>+6.1f}% {pnl_amt:>+8.0f}')
        else:
            print(f'{code_in:<10s} {"未找到":<8s}')

    print('-' * 70)
    print(f'总浮动盈亏: {total_pnl:+.0f} 元')

if __name__ == '__main__':
    positions = parse_args()
    if not positions:
        print('用法: python track.py 代码:成本:股数 ...')
        print('示例: python track.py 301308:533.133:500 300394:357.539:500')
        sys.exit(1)
    track(positions)
