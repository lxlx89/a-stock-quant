"""
数据库持久化层 — PostgreSQL 读写 + JSON fallback

默认 DB_ENABLED=false，不破坏现有 JSON 流程。
设为 true 后交易数据写入 PostgreSQL，连接失败自动回退到 JSON。
"""
import os
import json
from datetime import datetime
from config import (
    BASE_DIR, DB_ENABLED, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    TRADE_FILE, TRADE_HISTORY_FILE,
)

_conn = None


def _get_conn():
    """获取数据库连接（延迟连接）"""
    global _conn
    if _conn is None and DB_ENABLED:
        try:
            import psycopg2
            _conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
            )
        except Exception as e:
            print(f"  [DB] 连接失败，将使用 JSON fallback: {e}")
            return None
    return _conn


def _ensure_tables():
    """确保表存在"""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    code VARCHAR(10) NOT NULL,
                    name VARCHAR(50),
                    direction VARCHAR(4) NOT NULL,
                    price NUMERIC(10,3),
                    shares INTEGER,
                    cost NUMERIC(15,2),
                    date TIMESTAMP DEFAULT NOW(),
                    reason TEXT,
                    status VARCHAR(10) DEFAULT 'open',
                    close_price NUMERIC(10,3),
                    close_date TIMESTAMP,
                    pnl_pct NUMERIC(8,2),
                    pnl_amount NUMERIC(15,2),
                    sell_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trades_code ON trades(code);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            """)
        conn.commit()
    except Exception as e:
        print(f"  [DB] 建表失败: {e}")


def _load_json_fallback(path):
    """JSON 文件回退读取"""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_json_fallback(path, data):
    """JSON 文件回退写入"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_trades():
    """
    加载当前持仓（DB 优先，失败回退 JSON）

    返回：
        list[dict]: 持仓列表
    """
    if not DB_ENABLED:
        return _load_json_fallback(TRADE_FILE)

    conn = _get_conn()
    if conn is None:
        return _load_json_fallback(TRADE_FILE)

    try:
        _ensure_tables()
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM trades WHERE status = 'open' ORDER BY id")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"  [DB] 查询失败，回退 JSON: {e}")
        return _load_json_fallback(TRADE_FILE)


def save_trade(trade_dict, direction='buy'):
    """
    保存一笔交易

    参数：
        trade_dict: 交易数据
        direction: 'buy' | 'sell'
    """
    if not DB_ENABLED:
        return _save_json_fallback_trade(trade_dict, direction)

    conn = _get_conn()
    if conn is None:
        return _save_json_fallback_trade(trade_dict, direction)

    try:
        _ensure_tables()
        with conn.cursor() as cur:
            if direction == 'buy':
                cur.execute("""
                    INSERT INTO trades (code, name, direction, price, shares, cost, date, reason, status)
                    VALUES (%(code)s, %(name)s, 'buy', %(price)s, %(shares)s, %(cost)s, %(date)s, %(reason)s, 'open')
                """, trade_dict)
            elif direction == 'sell':
                cur.execute("""
                    UPDATE trades SET status='closed', close_price=%(now_price)s,
                    close_date=%(close_date)s, pnl_pct=%(pnl_pct)s,
                    pnl_amount=%(pnl_amount)s, sell_reason=%(reason)s
                    WHERE code=%(code)s AND status='open'
                """, trade_dict)
        conn.commit()
    except Exception as e:
        print(f"  [DB] 写入失败，回退 JSON: {e}")
        _save_json_fallback_trade(trade_dict, direction)
        # 重置连接，下次重试
        global _conn
        _conn = None


def _save_json_fallback_trade(trade_dict, direction):
    """JSON 交易回退写入 — 复用 strategy 模块的写逻辑"""
    # 避免循环导入，直接操作 JSON 文件
    trades = _load_json_fallback(TRADE_FILE)
    history = _load_json_fallback(TRADE_HISTORY_FILE)

    if direction == 'buy':
        buy_id = max([t.get('id', 0) for t in trades], default=0) + 1
        trade = {
            'id': buy_id,
            'code': trade_dict['code'],
            'name': trade_dict.get('name', ''),
            'direction': 'buy',
            'price': trade_dict['price'],
            'shares': trade_dict['shares'],
            'cost': trade_dict.get('cost', trade_dict['price'] * trade_dict['shares']),
            'date': trade_dict.get('date', datetime.now().strftime('%Y-%m-%d %H:%M')),
            'reason': trade_dict.get('reason', ''),
            'status': 'open',
        }
        trades.append(trade)
    elif direction == 'sell':
        # 找到并关闭对应持仓
        for t in trades:
            if t['code'] == trade_dict['code'] and t.get('status') == 'open':
                t['status'] = 'closed'
                t['close_price'] = trade_dict.get('now_price')
                t['close_date'] = trade_dict.get('close_date', datetime.now().strftime('%Y-%m-%d %H:%M'))
                t['pnl_pct'] = trade_dict.get('pnl_pct')
                t['pnl_amount'] = trade_dict.get('pnl_amount')
                t['sell_reason'] = trade_dict.get('reason', '')
                history.append({**t})
                break
        trades = [t for t in trades if t.get('status') != 'closed']

    _save_json_fallback(TRADE_FILE, trades)
    _save_json_fallback(TRADE_HISTORY_FILE, history)


def load_trade_history():
    """
    加载历史交易（DB 优先，失败回退 JSON）

    返回：
        list[dict]: 历史交易列表
    """
    if not DB_ENABLED:
        return _load_json_fallback(TRADE_HISTORY_FILE)

    conn = _get_conn()
    if conn is None:
        return _load_json_fallback(TRADE_HISTORY_FILE)

    try:
        _ensure_tables()
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM trades WHERE status = 'closed' ORDER BY close_date DESC")
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"  [DB] 查询失败，回退 JSON: {e}")
        return _load_json_fallback(TRADE_HISTORY_FILE)
