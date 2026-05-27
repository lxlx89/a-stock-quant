"""
快速数据抓取模块（Sina 数据源）
push2.eastmoney.com 被墙，改用 Sina 并行批量抓取

架构：
  1. 股票代码列表缓存（data/cache/stock_codes.json，有效期 1 天）
  2. Sina Market Center API 分页获取（100 只/页，10 线程并行）
  3. 字段计算（振幅、涨跌额等）
  4. 输出 DataFrame 兼容现有管线
"""

import os
import json
import time
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import BASE_DIR

CACHE_DIR = os.path.join(BASE_DIR, 'data', 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'stock_codes.json')
CACHE_MAX_AGE_HOURS = 6  # 股票代码缓存有效期

SINA_API = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
BATCH_SIZE = 100
MAX_WORKERS = 10

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn/',
}


def _load_cached_codes():
    """加载缓存的股票代码列表，有效期内直接返回"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(CACHE_FILE):
        age_hours = (time.time() - os.path.getmtime(CACHE_FILE)) / 3600
        if age_hours < CACHE_MAX_AGE_HOURS:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                codes = json.load(f)
            if len(codes) > 4000:
                return codes
    return None


def _save_cached_codes(codes):
    """缓存股票代码列表"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(codes, f, ensure_ascii=False)


def _fetch_page(page, **kwargs):
    """抓取单页（线程安全）"""
    params = {
        'page': page,
        'num': BATCH_SIZE,
        'sort': 'symbol',
        'asc': '1',
        'node': 'hs_a',
    }
    try:
        resp = requests.get(SINA_API, params=params, headers=HEADERS, timeout=15, **kwargs)
        text = resp.content.decode('gbk', errors='replace')
        return json.loads(text)
    except Exception as e:
        return []


def _get_total_pages():
    """探测总页数"""
    data = _fetch_page(1)
    if not data:
        return 0
    # 如果返回不足 BATCH_SIZE，只有 1 页
    if len(data) < BATCH_SIZE:
        return 1
    # 试探法：找最后一页
    for test_page in [100, 80, 70, 60, 55]:
        d = _fetch_page(test_page)
        if d and len(d) > 0:
            # 继续探测
            for p in range(test_page, test_page + 5):
                d2 = _fetch_page(p)
                if not d2 or len(d2) == 0:
                    return p - 1
    return 60  # 默认估计


def _fetch_all_pages():
    """并行抓取所有页面，返回全部股票原始数据"""
    total_pages = 55  # 5500/100 ≈ 55 页
    all_data = []
    page_empty = set()

    def fetch_safe(page):
        if page in page_empty:
            return page, []
        data = _fetch_page(page)
        if not data or len(data) == 0:
            page_empty.add(page)
            return page, []
        return page, data

    # 先用第一页确定实际页数
    first_data = _fetch_page(1)
    if not first_data:
        return []
    all_data.extend(first_data)

    # 探测总页数
    test_pages = [60, 55, 50, 70]
    for tp in test_pages:
        td = _fetch_page(tp)
        if td and len(td) > 0:
            total_pages = tp + 5
            break

    # 并行抓取剩余页面
    pages_to_fetch = list(range(2, total_pages + 1))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_safe, p): p for p in pages_to_fetch}
        for future in as_completed(futures):
            page, data = future.result()
            if data:
                all_data.extend(data)

    return all_data


def _convert_to_dataframe(raw_data):
    """将 Sina JSON 数据转为标准 DataFrame，计算缺失字段"""
    if not raw_data:
        return pd.DataFrame()

    df = pd.DataFrame(raw_data)

    # 处理代码字段：优先用 symbol（带 sh/sz/bj 前缀），兼容原 AKShare 格式
    if 'symbol' in df.columns:
        df['代码'] = df['symbol'].astype(str).str.strip()
    elif 'code' in df.columns:
        df['代码'] = df['code'].astype(str).str.strip()

    # 重命名标准字段
    col_map = {
        'name': '名称',
        'trade': '最新价',
        'open': '今开',
        'high': '最高',
        'low': '最低',
        'settlement': '昨收',
        'volume': '成交量',
        'amount': '成交额',
        'changepercent': '涨跌幅',
        'pricechange': '涨跌额',
        'turnoverratio': '换手率',
        'per': '市盈率',
        'pb': '市净率',
        'mktcap': '总市值',
        'nmc': '流通市值',
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 只保留管线需要的列
    keep_cols = ['代码', '名称', '最新价', '今开', '最高', '最低', '昨收',
                 '成交量', '成交额', '涨跌幅', '涨跌额', '换手率',
                 '市盈率', '市净率', '总市值', '流通市值', '振幅', '量比', '板块']
    df = df[[c for c in keep_cols if c in df.columns]].copy()

    # 数值转换
    numeric_cols = ['最新价', '今开', '最高', '最低', '昨收', '成交量', '成交额',
                    '涨跌幅', '涨跌额', '换手率', '市盈率', '市净率', '总市值', '流通市值']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 计算 振幅 = (最高 - 最低) / 昨收 * 100
    if '振幅' not in df.columns:
        if all(c in df.columns for c in ['最高', '最低', '昨收']):
            valid = df['昨收'] > 0
            df['振幅'] = 0.0
            df.loc[valid, '振幅'] = (
                (df.loc[valid, '最高'] - df.loc[valid, '最低'])
                / df.loc[valid, '昨收'] * 100
            ).round(2)

    # 补充涨跌额
    if '涨跌额' not in df.columns:
        if all(c in df.columns for c in ['最新价', '昨收']):
            df['涨跌额'] = (df['最新价'] - df['昨收']).round(2)

    # 补充涨跌幅
    if '涨跌幅' not in df.columns:
        if all(c in df.columns for c in ['最新价', '昨收']):
            valid = df['昨收'] > 0
            df['涨跌幅'] = 0.0
            df.loc[valid, '涨跌幅'] = (
                (df.loc[valid, '最新价'] - df.loc[valid, '昨收'])
                / df.loc[valid, '昨收'] * 100
            ).round(2)

    # 量比字段（Sina 不提供，设为 NaN）
    if '量比' not in df.columns:
        df['量比'] = float('nan')

    # 板块字段（Sina 不提供，后续可以从 stock_filter 映射）
    if '板块' not in df.columns:
        df['板块'] = ''

    # 填充 NaN
    df = df.fillna({
        '涨跌幅': 0, '涨跌额': 0, '振幅': 0, '换手率': 0,
        '市盈率': 0, '市净率': 0, '总市值': 0, '流通市值': 0,
        '成交量': 0, '成交额': 0,
    })

    # 过滤无效数据
    if '最新价' in df.columns:
        df = df[df['最新价'] > 0]
    if '代码' in df.columns:
        df = df[df['代码'].notna()]
    if '名称' in df.columns:
        df = df[df['名称'].notna()]

    return df


def fetch_realtime_quotes_sina():
    """
    快速获取 A 股全市场实时行情（Sina 数据源）

    替代原有的 AKShare push2.eastmoney.com 方案。
    10 线程并行抓取，预期耗时 < 5 秒。

    返回：
        (pandas.DataFrame, None): 成功时返回数据和 None
        (None, str): 失败时返回 None 和错误信息
    """
    print("  正在从 Sina 快速抓取全市场实时行情...")
    print("  （10 线程并行，预计 < 5 秒）")

    start_time = time.time()

    try:
        # 第一步：获取股票代码列表（优先缓存）
        codes_cached = _load_cached_codes()
        if codes_cached:
            print(f"  [缓存] 使用缓存的 {len(codes_cached)} 个股票代码")
        else:
            print("  [缓存] 未命中，正在获取代码列表...")
            _fetch_page(1)  # 预热
            codes_cached = ['warmup']  # 占位

        # 第二步：并行抓取全量数据
        raw_data = _fetch_all_pages()

        if not raw_data:
            return (None,
                "Sina 数据抓取失败，请检查网络连接\n"
                "代理用户请将 sina.com.cn 加入直连白名单"
            )

        # 第三步：转换为 DataFrame
        df = _convert_to_dataframe(raw_data)

        # 缓存代码列表
        if '代码' in df.columns:
            codes = df['代码'].tolist()
            _save_cached_codes(codes)

        elapsed = time.time() - start_time
        print(f"  抓取完成，耗时 {elapsed:.1f} 秒（{len(df)} 只股票）")

        return df, None

    except Exception as e:
        return None, f"Sina 数据源异常: {e}"


def fetch_realtime_quotes_cache():
    """
    从本地缓存加载最近一次成功抓取的行情数据

    返回：
        (pandas.DataFrame, None): 缓存有效时
        (None, str): 缓存不存在或已过期时
    """
    import pandas as pd
    from config import DATA_CACHE_FILE, DATA_CACHE_MAX_AGE_HOURS

    cache_file = DATA_CACHE_FILE
    if not os.path.exists(cache_file):
        return None, "缓存文件不存在"

    age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
    if age_hours > DATA_CACHE_MAX_AGE_HOURS:
        return None, f"缓存已过期（{age_hours:.1f}小时 > {DATA_CACHE_MAX_AGE_HOURS}小时）"

    try:
        df = pd.read_parquet(cache_file)
        if df is not None and not df.empty:
            print(f"  [Cache] 从缓存加载 {len(df)} 只股票（{age_hours:.1f}小时前）")
            return df, None
        return None, "缓存文件为空"
    except Exception as e:
        return None, f"缓存读取失败: {e}"


# ============================================================
# Tencent 数据源（qt.gtimg.cn）
# ============================================================

TENCENT_API = 'http://qt.gtimg.cn/q='
TENCENT_BATCH_SIZE = 50
TENCENT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://stock.qq.com/',
}

# Tencent API 字段索引
_T_IDX = {
    'market': 0, 'name': 1, 'code': 2, 'price': 3, 'prev_close': 4,
    'open': 5, 'vol_lots': 6, 'high': 33, 'low': 34,
    'change_pct': 31, 'change_amt': 32, 'turnover': 38,
    'pe': 39, 'pb': 46, 'amplitude': 43,
    'mkt_cap': 44, 'circ_mkt_cap': 45, 'amount_wan': 57,
}


def _fetch_tencent_batch(codes):
    """抓取一批腾讯行情数据"""
    if not codes:
        return []
    url = TENCENT_API + ','.join(codes)
    try:
        resp = requests.get(url, headers=TENCENT_HEADERS, timeout=15)
        text = resp.content.decode('gbk', errors='replace')
    except Exception:
        return []

    results = []
    for line in text.strip().split(';'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        try:
            code_str = line[2:line.index('=')]
            start = line.index('"') + 1
            end = line.rindex('"')
            fields = line[start:end].split('~')
            if len(fields) < 46:
                continue
            results.append({
                'code_raw': code_str,
                'fields': fields,
            })
        except (ValueError, IndexError):
            continue
    return results


def _parse_tencent(results):
    """将腾讯原始数据转为标准 DataFrame"""
    if not results:
        return pd.DataFrame()

    rows = []
    for r in results:
        fields = r['fields']
        try:
            code = fields[_T_IDX['code']]
            market = fields[_T_IDX['market']]
            prefix = {'1': 'sh', '51': 'sz'}.get(market, market)
            price = float(fields[_T_IDX['price']]) if fields[_T_IDX['price']] else None
            prev_close = float(fields[_T_IDX['prev_close']]) if fields[_T_IDX['prev_close']] else None
            if price is None or price <= 0:
                continue

            # 成交量：手 → 股
            vol_lots = float(fields[_T_IDX['vol_lots']]) if fields[_T_IDX['vol_lots']] else 0
            volume = vol_lots * 100

            # 成交额：万元 → 元
            amt_wan = float(fields[_T_IDX['amount_wan']]) if _T_IDX['amount_wan'] < len(fields) and fields[_T_IDX['amount_wan']] else 0
            amount = amt_wan * 10000

            # 总市值/流通市值：亿 → 元
            mkt_cap = float(fields[_T_IDX['mkt_cap']]) * 1e8 if fields[_T_IDX['mkt_cap']] else 0
            circ_cap = float(fields[_T_IDX['circ_mkt_cap']]) * 1e8 if fields[_T_IDX['circ_mkt_cap']] else 0

            change_pct = float(fields[_T_IDX['change_pct']]) if fields[_T_IDX['change_pct']] else 0
            change_amt = float(fields[_T_IDX['change_amt']]) if fields[_T_IDX['change_amt']] else 0
            turnover = float(fields[_T_IDX['turnover']]) if fields[_T_IDX['turnover']] else 0
            pe = float(fields[_T_IDX['pe']]) if fields[_T_IDX['pe']] else 0
            pb = float(fields[_T_IDX['pb']]) if _T_IDX['pb'] < len(fields) and fields[_T_IDX['pb']] else 0
            amp = float(fields[_T_IDX['amplitude']]) if _T_IDX['amplitude'] < len(fields) and fields[_T_IDX['amplitude']] else 0
            high = float(fields[_T_IDX['high']]) if fields[_T_IDX['high']] else price
            low = float(fields[_T_IDX['low']]) if fields[_T_IDX['low']] else price
            open_p = float(fields[_T_IDX['open']]) if fields[_T_IDX['open']] else price
            name = fields[_T_IDX['name']]

            # 振幅回退计算
            if amp <= 0 and prev_close and prev_close > 0:
                amp = round((high - low) / prev_close * 100, 2)

            rows.append({
                '代码': f'{prefix}{code}',
                '名称': name,
                '最新价': price,
                '今开': open_p,
                '最高': high,
                '最低': low,
                '昨收': prev_close or price,
                '成交量': volume,
                '成交额': amount,
                '涨跌幅': change_pct,
                '涨跌额': change_amt,
                '换手率': turnover,
                '市盈率': pe,
                '市净率': pb,
                '总市值': mkt_cap,
                '流通市值': circ_cap,
                '振幅': amp,
                '量比': float('nan'),
                '板块': '',
            })
        except (ValueError, IndexError, TypeError):
            continue

    return pd.DataFrame(rows)


def fetch_realtime_quotes_tencent():
    """
    快速获取 A 股全市场实时行情（腾讯 qt.gtimg.cn 数据源）

    5500+ 股票，50只/批，10线程并行，预计 < 10秒

    返回：
        (pandas.DataFrame, None): 成功
        (None, str): 失败
    """
    print("  正在从腾讯 qt.gtimg.cn 抓取全市场实时行情...")
    print("  （50只/批，10线程并行）")

    start_time = time.time()

    try:
        codes = _load_cached_codes()
        if not codes:
            return None, "股票代码缓存不存在，请先运行 Sina 源生成缓存"

        print(f"  [缓存] {len(codes)} 个股票代码")

        # 分批
        batches = []
        for i in range(0, len(codes), TENCENT_BATCH_SIZE):
            batches.append(codes[i:i + TENCENT_BATCH_SIZE])

        # 并行抓取
        all_results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_tencent_batch, b): b for b in batches}
            for future in as_completed(futures):
                try:
                    data = future.result()
                    if data:
                        all_results.extend(data)
                except Exception:
                    pass

        if not all_results:
            return None, "腾讯数据源无返回数据"

        df = _parse_tencent(all_results)

        # 更新缓存
        if '代码' in df.columns and len(df) > 0:
            _save_cached_codes(df['代码'].tolist())

        elapsed = time.time() - start_time
        print(f"  抓取完成，耗时 {elapsed:.1f} 秒（{len(df)} 只股票）")

        return df, None

    except Exception as e:
        return None, f"腾讯数据源异常: {e}"
