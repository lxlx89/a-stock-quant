"""
交易日志 — 记录买卖、统计盈亏、复盘分析
用法:
  python journal.py add --code 300394 --name 天孚通信 --dir buy --price 357.54 --shares 500 --reason "早盘温和放量"
  python journal.py close --code 300394 --price 378.19 --reason "收盘"
  python journal.py list              # 显示所有持仓
  python journal.py history           # 显示已完成交易
  python journal.py pnl               # 显示当前浮盈
"""
import os
import json
import sys
import time
import argparse
from datetime import datetime

JOURNAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
JOURNAL_FILE = os.path.join(JOURNAL_DIR, 'trades.json')
HISTORY_FILE = os.path.join(JOURNAL_DIR, 'trade_history.json')
os.makedirs(JOURNAL_DIR, exist_ok=True)


def load_trades():
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_trades(trades):
    with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def cmd_add(args):
    trades = load_trades()
    trade = {
        'id': len(trades) + len(load_history()) + 1,
        'code': args.code,
        'name': args.name,
        'direction': args.dir,
        'price': args.price,
        'shares': args.shares,
        'cost': args.price * args.shares,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'reason': args.reason or '',
        'status': 'open'
    }
    trades.append(trade)
    save_trades(trades)
    print(f'已记录: {args.dir} {args.code} {args.name} {args.price:.2f}×{args.shares}股 = {args.price*args.shares:.0f}元')
    print(f'原因: {args.reason or "无"}')


def cmd_close(args):
    trades = load_trades()
    history = load_history()
    found = None
    for t in trades:
        if t['code'] == args.code and t['status'] == 'open':
            found = t
            break
    if not found:
        print(f'未找到 {args.code} 的未平仓记录')
        return
    trades.remove(found)
    found['close_price'] = args.price
    found['close_date'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    found['close_reason'] = args.reason or ''
    found['pnl'] = (args.price - found['price']) * found['shares']
    found['pnl_pct'] = (args.price - found['price']) / found['price'] * 100
    found['status'] = 'closed'
    history.append(found)
    save_trades(trades)
    save_history(history)
    print(f'已平仓: {found["code"]} {found["name"]} {found["price"]:.2f}→{args.price:.2f}')
    print(f'盈亏: {found["pnl"]:+.0f}元 ({found["pnl_pct"]:+.1f}%)')


def cmd_list(args):
    trades = load_trades()
    if not trades:
        print('当前无持仓记录')
        return
    total_cost = 0
    print(f'{"代码":<10s} {"名称":<8s} {"方向":<4s} {"价格":>7s} {"股数":>6s} {"成本":>8s} {"日期":<16s} {"原因"}')
    print('-' * 80)
    for t in trades:
        print(f'{t["code"]:<10s} {t["name"]:<8s} {t["direction"]:<4s} {t["price"]:>7.2f} {t["shares"]:>6d} {t["cost"]:>8.0f} {t["date"]:<16s} {t.get("reason","")[:20]}')
        total_cost += t['cost']
    print('-' * 80)
    print(f'持仓 {len(trades)} 只, 总成本 {total_cost:.0f} 元')


def cmd_history(args):
    history = load_history()
    if not history:
        print('无历史交易记录')
        return
    total_pnl = 0
    wins = 0
    print(f'{"代码":<10s} {"名称":<8s} {"买入":>7s} {"卖出":>7s} {"盈亏":>8s} {"盈亏%":>7s} {"日期"}')
    print('-' * 75)
    for t in history[-20:]:
        pnl = t.get('pnl', 0)
        total_pnl += pnl
        if pnl > 0:
            wins += 1
        print(f'{t["code"]:<10s} {t["name"]:<8s} {t["price"]:>7.2f} {t.get("close_price",0):>7.2f} {pnl:>+8.0f} {t.get("pnl_pct",0):>+6.1f}% {t.get("close_date","")[:16]}')
    print('-' * 75)
    win_rate = wins/len(history)*100 if history else 0
    print(f'已完成 {len(history)} 笔, 胜率 {win_rate:.0f}%, 总盈亏 {total_pnl:+.0f} 元')


def cmd_import(args):
    """导入当前持仓（一次性初始化）"""
    trades = load_trades()
    # 用户当前持仓
    positions = [
        ('301308', '江波龙', 'buy', 533.133, 500, '前期买入'),
        ('300394', '天孚通信', 'buy', 357.539, 500, '5/13早盘买入+4.5%'),
        ('600330', '天通股份', 'buy', 34.379, 6000, '前期买入'),
        ('002342', '巨力索具', 'buy', 22.046, 17500, '前期买入'),
    ]
    for code, name, d, price, shares, reason in positions:
        if not any(t['code'] == code for t in trades):
            trades.append({
                'id': len(trades) + len(load_history()) + 1,
                'code': code, 'name': name, 'direction': d,
                'price': price, 'shares': shares,
                'cost': price * shares,
                'date': '2026-05-13 09:30',
                'reason': reason, 'status': 'open'
            })
    save_trades(trades)
    print(f'已导入 {len(trades)} 只持仓')


def main():
    parser = argparse.ArgumentParser(description='交易日志')
    sub = parser.add_subparsers(dest='cmd')

    p_add = sub.add_parser('add', help='记录新交易')
    p_add.add_argument('--code', required=True)
    p_add.add_argument('--name', required=True)
    p_add.add_argument('--dir', choices=['buy','sell'], required=True)
    p_add.add_argument('--price', type=float, required=True)
    p_add.add_argument('--shares', type=int, required=True)
    p_add.add_argument('--reason')

    p_close = sub.add_parser('close', help='平仓')
    p_close.add_argument('--code', required=True)
    p_close.add_argument('--price', type=float, required=True)
    p_close.add_argument('--reason')

    sub.add_parser('list', help='显示持仓')
    sub.add_parser('history', help='显示历史交易')
    sub.add_parser('pnl', help='显示当前浮盈')
    sub.add_parser('import', help='导入当前持仓')

    args = parser.parse_args()
    if args.cmd == 'add': cmd_add(args)
    elif args.cmd == 'close': cmd_close(args)
    elif args.cmd == 'history': cmd_history(args)
    elif args.cmd == 'import': cmd_import(args)
    elif args.cmd == 'list': cmd_list(args)
    elif args.cmd == 'pnl':
        trades = load_trades()
        # 动态计算需要拉实时数据
        print('使用 track.py 获取实时盈亏')
        print('示例: python track.py 301308:533.133:500 ...')
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
