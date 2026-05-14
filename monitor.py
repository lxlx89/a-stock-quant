"""
单股监控脚本 — 后台运行，到价提醒
用法:
  python monitor.py 002342 22.046 --buy 21.50 --stop 20.60
  监控巨力索具，反弹到21.50或跌破20.60时打印提醒
"""
import sys
import time
import argparse
from src.fast_fetcher import fetch_realtime_quotes
from src.stock_filter import load_and_clean

def clean_code(c):
    for p in ['sz','sh','bj','SZ','SH','BJ']:
        if c.startswith(p): return c[len(p):]
    return c

def main():
    parser = argparse.ArgumentParser(description='股票价格监控')
    parser.add_argument('code', help='股票代码')
    parser.add_argument('cost', type=float, nargs='?', default=None, help='成本价(可选)')
    parser.add_argument('--target', '-t', type=float, nargs='+', help='目标价（提醒卖出）')
    parser.add_argument('--stop', '-s', type=float, nargs='+', help='止损价（提醒卖出）')
    parser.add_argument('--interval', '-i', type=int, default=60, help='检查间隔(秒), 默认60')
    parser.add_argument('--once', action='store_true', help='只查一次')
    args = parser.parse_args()

    target_prices = args.target or []
    stop_prices = args.stop or []

    if not target_prices and not stop_prices:
        print('请至少指定 --target 或 --stop 价格')
        sys.exit(1)

    print(f'监控 {args.code}', end='')
    if args.cost:
        print(f' | 成本 {args.cost:.2f}', end='')
    if target_prices:
        print(f' | 目标 {target_prices}', end='')
    if stop_prices:
        print(f' | 止损 {stop_prices}', end='')
    print(f' | 间隔 {args.interval}s')
    print()

    last_price = None

    while True:
        try:
            df = fetch_realtime_quotes()
            df = load_and_clean(df)
            matched = df[df['代码'].apply(lambda x: clean_code(str(x)) == clean_code(args.code))]
            if len(matched) == 0:
                print(f'  [{time.strftime("%H:%M:%S")}] 未找到 {args.code}')
            else:
                r = matched.iloc[0]
                price = r['最新价']
                chg = r['涨跌幅']
                turnover = r.get('换手率', 0)
                amt = r['成交额'] / 1e8

                arrow = ''
                if last_price and price > last_price: arrow = '↑'
                elif last_price and price < last_price: arrow = '↓'
                last_price = price

                pnl_str = ''
                if args.cost:
                    pnl = (price - args.cost) / args.cost * 100
                    pnl_str = f' | 浮{pnl:+.1f}%'

                print(f'  [{time.strftime("%H:%M:%S")}] {price:.2f} {chg:+.2f}% {arrow} | 换{turnover:.1f}% | 成交{amt:.1f}亿{pnl_str}')

                # 检查提醒
                for tp in target_prices:
                    if price >= tp:
                        msg = f'巨力索具 002342 达到目标价 {tp}，当前 {price:.2f}，建议卖出减仓！'
                        print(f'\n  !!! 【提醒】{msg}\n')
                        _alert_windows(f'002342 达到目标价 {tp}', f'当前价 {price:.2f}，建议卖出')
                        _send_qq(msg)

                for sp in stop_prices:
                    if price <= sp:
                        msg = f'巨力索具 002342 跌破止损 {sp}，当前 {price:.2f}，建议立即止损！'
                        print(f'\n  !!! 【止损】{msg}\n')
                        _alert_windows(f'002342 跌破止损 {sp}', f'当前价 {price:.2f}，建议止损')
                        _send_qq(msg)

        except Exception as e:
            print(f'  [{time.strftime("%H:%M:%S")}] 抓取失败: {e}')

        if args.once:
            break
        time.sleep(args.interval)


def _alert_windows(title, body):
    """Windows 弹窗提醒"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, body, title, 0x40)
    except Exception:
        pass


def _send_qq(message):
    """通过 OpenClaw 发送 QQ 消息"""
    try:
        import subprocess
        cmd = [
            r'D:\Program Files\nodejs\node.exe',
            r'D:\Tools\npm-global\node_modules\openclaw\dist\index.js',
            'agent',
            '--session-id', '19c313a2-5b6b-4e06-a6bb-ff08f915cb17',
            '--channel', 'qqbot',
            '--message', f'[自动提醒] {message}。请简洁回复确认收到，不要展开分析。',
            '--deliver',
            '--timeout', '60'
        ]
        subprocess.run(cmd, capture_output=True, timeout=90)
        print(f'  [QQ] 已发送提醒')
    except Exception as e:
        print(f'  [QQ] 发送失败: {e}')


if __name__ == '__main__':
    main()
