"""
策略引擎 — T+1 模拟盘闭环核心
功能：买入信号生成、卖出信号生成、模拟交易执行、持仓管理
版本: 1.0
"""
import json
import os
from datetime import datetime
from config import (
    TRADE_FILE, TRADE_HISTORY_FILE,
    SELL_RULES, TRADING_PARAMS, SCORE_WEIGHTS_V2
)


# ============================================================
# 持仓数据读写
# ============================================================

def _load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_positions():
    """获取当前持仓列表"""
    return _load_json(TRADE_FILE)


def get_trade_history():
    """获取历史交易"""
    return _load_json(TRADE_HISTORY_FILE)


# ============================================================
# 买入信号生成
# ============================================================

def generate_buy_signals(watchlist, positions=None):
    """
    从观察池生成买入信号

    条件：
    1. 非涨停板（买不到）
    2. 非高风险（可配置）
    3. 涨幅适中（<8%，非追高）
    4. score >= min_score
    5. 不与现有持仓重复
    6. 不超过最大持仓数

    返回：买入信号列表 [{code, name, price, score, risk, reason}]
    """
    if watchlist is None or watchlist.empty:
        return []

    params = TRADING_PARAMS
    positions = positions or get_positions()
    held_codes = {p['code'] for p in positions if p.get('status') == 'open'}
    max_new = params['max_positions'] - len([p for p in positions if p.get('status') == 'open'])

    signals = []

    for _, row in watchlist.iterrows():
        code = str(row.get('代码', '')).replace('sz', '').replace('sh', '').replace('bj', '')
        score = float(row.get('score', 0))
        risk = str(row.get('risk_level', '高风险'))
        name = str(row.get('名称', ''))
        price = float(row.get('最新价', 0))
        chg = float(row.get('涨跌幅', 0))

        # ---- 过滤：涨停板买不到 ----
        if _is_near_limit(code, chg):
            continue

        # ---- 过滤：涨幅>8%不追高 ----
        if chg > 8.0:
            continue

        # 过滤条件
        if score < params['min_score']:
            continue
        if risk == '高风险' and params['max_risk'] == '中风险':
            continue
        if code in held_codes:
            continue
        if price <= 0:
            continue

        # 计算建议买入量
        shares = int(params['position_size'] / price / 100) * 100
        if shares < 100:
            continue

        signals.append({
            'code': code,
            'name': name,
            'price': round(price, 2),
            'score': round(score, 1),
            'chg': round(chg, 2),
            'risk': risk,
            'risk_detail': str(row.get('risk_detail', '')),
            'shares': shares,
            'cost': round(price * shares, 2),
            'reason': str(row.get('reason', f'评分{score:.0f}+{risk}')),
        })

        if len(signals) >= max_new:
            break

    return signals


# ============================================================
# 卖出信号生成
# ============================================================

def generate_sell_signals(positions, quotes_df):
    """
    根据持仓 + 实时行情生成卖出信号

    检查维度（按优先级）：
    1. 硬止损：亏损 > 5%
    2. 尾盘时间：14:50 必须卖出
    3. 止损：亏损 > 2%
    4. 止盈：盈利 > 3%
    5. 大涨止盈：盈利 > 7%
    6. 移动止盈：从最高点回落 > 1.5%
    7. 滞涨：开盘2小时后横盘

    返回：卖出信号列表 [{code, name, buy_price, now_price, pnl_pct, reason, urgency}]
    """
    if not positions or quotes_df is None or quotes_df.empty:
        return []

    rules = SELL_RULES
    now = datetime.now()
    now_str = now.strftime('%H:%M')
    signals = []

    # 建立实时行情索引 {code: row}
    quote_map = {}
    for _, row in quotes_df.iterrows():
        code = str(row.get('代码', '')).replace('sz', '').replace('sh', '').replace('bj', '')
        quote_map[code] = row

    for pos in positions:
        if pos.get('status') != 'open':
            continue

        code = pos['code']
        buy_price = pos['price']
        shares = pos['shares']

        if code not in quote_map:
            continue

        row = quote_map[code]
        now_price = float(row.get('最新价', 0))
        if now_price <= 0:
            continue

        pnl_pct = (now_price - buy_price) / buy_price * 100
        high = float(row.get('最高', now_price))
        open_price = float(row.get('今开', now_price))

        sell_reason = None
        urgency = 'normal'  # normal / urgent / critical

        # ---- 1. 硬止损（最高优先级） ----
        if pnl_pct <= rules['stop_loss_hard']:
            sell_reason = f'硬止损 亏损{pnl_pct:+.1f}%'
            urgency = 'critical'

        # ---- 2. 尾盘时间到了 ----
        elif now_str >= rules['afternoon_sell_time']:
            sell_reason = f'尾盘平仓 {now_str} 盈亏{pnl_pct:+.1f}%'
            urgency = 'urgent'

        # ---- 3. 止损 ----
        elif pnl_pct <= rules['stop_loss']:
            sell_reason = f'止损 亏损{pnl_pct:+.1f}%'
            urgency = 'urgent'

        # ---- 4. 大涨止盈 ----
        elif pnl_pct >= rules['take_profit_full']:
            sell_reason = f'大涨止盈 +{pnl_pct:.1f}%'
            urgency = 'urgent'

        # ---- 5. 移动止盈 ----
        elif pnl_pct > rules['take_profit']:
            drop_from_high = (high - now_price) / high * 100
            if drop_from_high >= rules['trailing_stop_pct']:
                sell_reason = f'移动止盈 最高+{((high-buy_price)/buy_price*100):.1f}% 回落{drop_from_high:.1f}%'
                urgency = 'urgent'
            else:
                sell_reason = f'止盈信号 +{pnl_pct:.1f}%（未触发移动止盈）'
                urgency = 'normal'

        # ---- 6. 滞涨检测（开盘N小时后横盘） ----
        elif now.hour >= 11 and abs(pnl_pct) < rules['stall_threshold']:
            sell_reason = f'滞涨 横盘{pnl_pct:+.1f}%超{rules["stall_hours"]}小时'
            urgency = 'normal'

        if sell_reason:
            signals.append({
                'code': code,
                'name': pos.get('name', ''),
                'buy_price': round(buy_price, 2),
                'now_price': round(now_price, 2),
                'shares': shares,
                'cost': pos.get('cost', 0),
                'pnl_pct': round(pnl_pct, 2),
                'pnl_amount': round((now_price - buy_price) * shares, 2),
                'reason': sell_reason,
                'urgency': urgency,
            })

    # 排序：critical > urgent > normal
    order = {'critical': 0, 'urgent': 1, 'normal': 2}
    signals.sort(key=lambda s: order.get(s['urgency'], 9))

    return signals


# ============================================================
# 模拟交易执行
# ============================================================

def execute_paper_trade(signal, direction='buy'):
    """
    执行一笔模拟交易，记录到 trades.json / trade_history.json

    参数：
        signal: {code, name, price, shares, reason, ...}
        direction: 'buy' | 'sell'

    返回：交易记录
    """
    trades = get_positions()
    history = get_trade_history()

    if direction == 'buy':
        # 检查是否已在持仓中
        if any(t['code'] == signal['code'] and t.get('status') == 'open' for t in trades):
            return {'error': f"{signal['code']} 已在持仓中"}

        buy_id = max([t.get('id', 0) for t in trades], default=0) + 1
        trade = {
            'id': buy_id,
            'code': signal['code'],
            'name': signal['name'],
            'direction': 'buy',
            'price': signal['price'],
            'shares': signal['shares'],
            'cost': round(signal['price'] * signal['shares'], 2),
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'reason': signal.get('reason', ''),
            'status': 'open',
        }
        trades.append(trade)

    elif direction == 'sell':
        # 找到对应持仓并在 history 中记录盈亏
        target = None
        for t in trades:
            if t['code'] == signal['code'] and t.get('status') == 'open':
                target = t
                break

        if not target:
            return {'error': f"未找到 {signal['code']} 的持仓"}

        # 更新持仓状态
        target['status'] = 'closed'
        target['close_price'] = signal['now_price']
        target['close_date'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        target['pnl_pct'] = round(signal['pnl_pct'], 2)
        target['pnl_amount'] = round(signal['pnl_amount'], 2)
        target['sell_reason'] = signal.get('reason', '')

        # 移到历史
        history.append({**target})
        trades = [t for t in trades if t.get('status') != 'closed']

        trade = target

    _save_json(TRADE_FILE, trades)
    _save_json(TRADE_HISTORY_FILE, history)

    return trade


# ============================================================
# 持仓汇总
# ============================================================

def get_portfolio_summary(quotes_df):
    """
    获取持仓汇总 + 实时浮盈

    返回：{
        positions: [{code, name, buy_price, now_price, shares, cost, market_value, pnl_pct, pnl_amount}],
        total_cost, total_market_value, total_pnl, total_pnl_pct, position_count
    }
    """
    positions = get_positions()
    open_pos = [p for p in positions if p.get('status') == 'open']

    if not open_pos:
        return {
            'positions': [],
            'total_cost': 0,
            'total_market_value': 0,
            'total_pnl': 0,
            'total_pnl_pct': 0,
            'position_count': 0,
        }

    # 建立行情索引
    quote_map = {}
    if quotes_df is not None and not quotes_df.empty:
        for _, row in quotes_df.iterrows():
            code = str(row.get('代码', '')).replace('sz', '').replace('sh', '').replace('bj', '')
            quote_map[code] = row

    pos_list = []
    total_cost = 0
    total_market_value = 0

    for p in open_pos:
        code = p['code']
        buy_price = p['price']
        shares = p['shares']
        cost = p.get('cost', buy_price * shares)

        row = quote_map.get(code)
        if row is not None:
            now_price = float(row.get('最新价', buy_price))
        else:
            now_price = buy_price

        market_value = now_price * shares
        pnl = market_value - cost
        pnl_pct = (now_price - buy_price) / buy_price * 100

        total_cost += cost
        total_market_value += market_value

        pos_list.append({
            'code': code,
            'name': p.get('name', ''),
            'buy_price': round(buy_price, 2),
            'now_price': round(now_price, 2),
            'shares': shares,
            'cost': round(cost, 2),
            'market_value': round(market_value, 2),
            'pnl_pct': round(pnl_pct, 2),
            'pnl_amount': round(pnl, 2),
            'buy_date': p.get('date', ''),
            'reason': p.get('reason', ''),
        })

    total_pnl = total_market_value - total_cost
    total_pnl_pct = (total_market_value - total_cost) / total_cost * 100 if total_cost > 0 else 0

    return {
        'positions': pos_list,
        'total_cost': round(total_cost, 2),
        'total_market_value': round(total_market_value, 2),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'position_count': len(pos_list),
    }


# ============================================================
# 绩效统计
# ============================================================

def get_performance_stats():
    """计算历史交易绩效统计"""
    history = get_trade_history()
    if not history:
        return {
            'total_trades': 0,
            'win_rate': 0,
            'avg_return': 0,
            'total_return': 0,
            'max_win': 0,
            'max_loss': 0,
            'recent': [],
        }

    closed = [t for t in history if 'pnl_pct' in t]
    if not closed:
        return {'total_trades': 0, 'win_rate': 0, 'avg_return': 0, 'total_return': 0, 'max_win': 0, 'max_loss': 0, 'recent': []}

    wins = [t for t in closed if t['pnl_pct'] > 0]
    returns = [t['pnl_pct'] for t in closed]

    recent = sorted(closed, key=lambda t: t.get('close_date', ''), reverse=True)[:20]

    return {
        'total_trades': len(closed),
        'wins': len(wins),
        'losses': len(closed) - len(wins),
        'win_rate': round(len(wins) / len(closed) * 100, 1),
        'avg_return': round(sum(returns) / len(returns), 2),
        'total_return': round(sum(returns), 2),
        'max_win': round(max(returns), 2),
        'max_loss': round(min(returns), 2),
        'recent': [{
            'code': t['code'],
            'name': t.get('name', ''),
            'buy_date': t.get('date', ''),
            'close_date': t.get('close_date', ''),
            'pnl_pct': t['pnl_pct'],
            'pnl_amount': t.get('pnl_amount', 0),
            'reason': t.get('sell_reason', ''),
        } for t in recent],
    }


# ============================================================
# 早盘推荐生成
# ============================================================

def _is_near_limit(code, chg):
    """
    判断是否接近涨停（买不到）
    主板 ±10%，创业板/科创板 ±20%
    返回 True 表示接近涨停，不可买入
    """
    code_str = str(code)
    if code_str.startswith(('300', '688', '301')):
        limit = 20.0
    else:
        limit = 10.0
    return chg >= limit * 0.95  # 涨到上限的95%就算涨停


def _get_limit_pct(code):
    """获取涨停幅度"""
    code_str = str(code)
    return 20.0 if code_str.startswith(('300', '688', '301')) else 10.0


def generate_morning_recommendation(watchlist):
    """
    从观察池生成早盘推荐列表

    精选逻辑：低风险优先 + 高评分 + 适中涨幅
    过滤：排除涨停板（买不到）、涨幅>8%追高风险大
    """
    from config import MORNING_RULES

    if watchlist is None or watchlist.empty:
        return []

    rules = MORNING_RULES

    wl = watchlist.copy()

    # ---- 过滤涨停板：排除已涨停或接近涨停的 ----
    if '涨跌幅' in wl.columns and '代码' in wl.columns:
        before = len(wl)
        wl = wl[~wl.apply(lambda r: _is_near_limit(r['代码'], r['涨跌幅']), axis=1)]
        after = len(wl)
        if before > after:
            print(f"  [推荐] 排除涨停板: {before} -> {after}")

    # ---- 涨幅上限：不推荐涨幅>8%的（追高风险太大） ----
    if '涨跌幅' in wl.columns:
        wl = wl[wl['涨跌幅'] <= 8.0]

    # 低风险优先
    if rules['prefer_low_risk'] and 'risk_level' in wl.columns:
        wl['_risk_order'] = wl['risk_level'].map({'低风险': 0, '中风险': 1, '高风险': 2})
        wl = wl.sort_values(['_risk_order', 'score'], ascending=[True, False])
    else:
        wl = wl.sort_values('score', ascending=False)

    # 按评分过滤
    if 'score' in wl.columns:
        wl = wl[wl['score'] >= rules['min_score']]

    top = wl.head(rules['top_n'])
    recommendations = []

    for _, row in top.iterrows():
        code = str(row.get('代码', '')).replace('sz', '').replace('sh', '').replace('bj', '')
        chg = float(row.get('涨跌幅', 0))
        limit_pct = _get_limit_pct(code)

        recommendations.append({
            'code': code,
            'name': str(row.get('名称', '')),
            'price': round(float(row.get('最新价', 0)), 2),
            'chg': round(chg, 2),
            'score': round(float(row.get('score', 0)), 1),
            'risk': str(row.get('risk_level', '')),
            'amount': round(float(row.get('成交额', 0)) / 1e8, 1),
            'turnover': round(float(row.get('换手率', 0)), 1),
            'reason': str(row.get('reason', '')),
            'limit_pct': limit_pct,
        })

        if len(recommendations) >= rules['max_recommend']:
            break

    return recommendations


def generate_overnight_recommendation(watchlist):
    """
    一夜持股法推荐（14:30 尾盘选股）

    精选逻辑：
    1. 调用 filter_overnight_candidates 筛选
    2. 按 overnight_score 排序
    3. 添加次日卖出建议
    """
    from config import OVERNIGHT_RULES
    from src.stock_filter import filter_overnight_candidates

    if watchlist is None or watchlist.empty:
        return []

    rules = OVERNIGHT_RULES
    candidates = filter_overnight_candidates(watchlist)

    if candidates is None or candidates.empty:
        return []

    top = candidates.head(10)
    recommendations = []

    for _, row in top.iterrows():
        code = str(row.get('代码', '')).replace('sz', '').replace('sh', '').replace('bj', '')
        chg = float(row.get('涨跌幅', 0))
        price = float(row.get('最新价', 0))
        high = float(row.get('最高', price))

        close_ratio = round(price / high * 100, 1) if high > 0 else 100
        overnight_score = float(row.get('overnight_score', 0))

        # 次日卖出计划
        sell_plan = (
            f"明早{rules['next_day']['sell_by']}前卖出；"
            f"止盈+{rules['next_day']['take_profit']}%；"
            f"止损{rules['next_day']['stop_loss']}%；"
            f"低开{rules['next_day']['low_open_cut']}%立刻离场"
        )

        recommendations.append({
            'code': code,
            'name': str(row.get('名称', '')),
            'price': round(price, 2),
            'chg': round(chg, 2),
            'score': round(overnight_score, 1),
            'risk': str(row.get('risk_level', '')),
            'amount': round(float(row.get('成交额', 0)) / 1e8, 1),
            'turnover': round(float(row.get('换手率', 0)), 1),
            'volume_ratio': round(float(row.get('量比', 0)), 1) if '量比' in row else 0,
            'close_ratio': close_ratio,
            'sell_plan': sell_plan,
            'reason': f'收盘强度{close_ratio}% | 日内趋势稳健',
        })

    return recommendations
