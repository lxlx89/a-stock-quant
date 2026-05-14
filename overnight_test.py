"""
一夜持股模拟测试脚本
模拟：尾盘买入 → 次日开盘卖出
用法: python overnight_test.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 当前尾盘选中的一夜持股（2026-05-14 收盘前）
BUYS = [
    {"code": "300564", "name": "筑博设计", "buy_price": 18.50, "shares": 1000},
    {"code": "300885", "name": "海昌新材", "buy_price": 29.78, "shares": 1000},
    {"code": "600382", "name": "广东明珠", "buy_price": 8.79, "shares": 1000},
]

STOP_LOSS = -0.015   # -1.5%
TAKE_PROFIT = 0.02   # +2%


def get_next_open(codes):
    """获取次日开盘价（用 BaoStock 历史数据模拟）"""
    import baostock as bs
    bs.login()
    prices = {}
    for stock in codes:
        try:
            code = stock['code']
            clean = code
            if clean.startswith(('6', '5')):
                bs_code = f'sh.{clean}'
            else:
                bs_code = f'sz.{clean}'

            # 获取最近交易日数据
            rs = bs.query_history_k_data_plus(
                bs_code, 'date,open,close',
                frequency='d', adjustflag='2'
            )
            if rs.error_code == '0':
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if len(rows) >= 2:
                    # 倒数第二行是最近完整交易日
                    last_close = float(rows[-1][1])
                    # 用收盘价模拟次日开盘
                    prices[code] = last_close
        except Exception as e:
            print(f"  {code} fetch error: {e}")

    bs.logout()
    return prices


def simulate():
    """模拟次日开盘卖出"""
    print("=" * 50)
    print("  一夜持股模拟测试")
    print("  策略：尾盘买入 → 次日开盘卖出")
    print("=" * 50)

    total_cost = 0
    total_return = 0
    codes = [b['code'] for b in BUYS]

    # 实际运行时，等明天开盘后填入真实开盘价
    # 这里用假设场景测试
    print()
    print("--- 买入记录 ---")
    for b in BUYS:
        cost = b['buy_price'] * b['shares']
        total_cost += cost
        print(f"  {b['code']} {b['name']}: {b['shares']}股 × ¥{b['buy_price']} = ¥{cost:,.0f}")

    print(f"\n  总投入: ¥{total_cost:,.0f}")

    print()
    print("--- 次日卖出模拟 ---")
    print("  (输入明早开盘价来算实际盈亏)")
    print()
    print("  明天开盘后运行: python overnight_test.py --real")
    print("  然后输入每只股票的开盘价")

    # 预设场景
    print()
    print("--- 场景分析 ---")
    scenarios = [
        ("开盘+1%", 1.01),
        ("开盘+2%(止盈)", 1.02),
        ("开盘平开", 1.00),
        ("开盘-1.5%(止损)", 0.985),
        ("开盘-3%", 0.97),
    ]
    for name, mul in scenarios:
        pnl = 0
        for b in BUYS:
            sell_price = round(b['buy_price'] * mul, 2)
            ret = (sell_price - b['buy_price']) * b['shares']
            pnl += ret
        rate = (pnl / total_cost) * 100
        print(f"  {name}: 盈亏 ¥{pnl:+,.0f} ({rate:+.1f}%)")


def real_check():
    """明天开盘后实际检查"""
    print("=" * 50)
    print("  一夜持股 实际卖出检查")
    print("=" * 50)
    print()
    print("  请输入每只股票的开盘价：")

    total_cost = 0
    total_pnl = 0
    for b in BUYS:
        cost = b['buy_price'] * b['shares']
        total_cost += cost
        try:
            price_str = input(f"  {b['code']} {b['name']} 开盘价: ")
            open_price = float(price_str)
        except (ValueError, EOFError):
            open_price = b['buy_price']

        pnl = (open_price - b['buy_price']) * b['shares']
        pnl_pct = (open_price - b['buy_price']) / b['buy_price'] * 100
        total_pnl += pnl

        action = ""
        if pnl_pct >= TAKE_PROFIT * 100:
            action = "✅ 止盈卖出"
        elif pnl_pct <= STOP_LOSS * 100:
            action = "❌ 止损卖出"
        elif pnl_pct < 0:
            action = "⚠️ 小幅亏损，按纪律卖出"
        else:
            action = "✅ 盈利卖出"

        print(f"    → 盈亏: ¥{pnl:+,.0f} ({pnl_pct:+.1f}%) {action}")

    total_rate = total_pnl / total_cost * 100
    print(f"\n  总计: ¥{total_pnl:+,.0f} ({total_rate:+.1f}%)")
    print(f"  投入: ¥{total_cost:,.0f}")


if __name__ == '__main__':
    if '--real' in sys.argv:
        real_check()
    else:
        simulate()
