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


def fetch_realtime_quotes():
    """
    快速获取 A 股全市场实时行情（Sina 数据源）

    替代原有的 AKShare push2.eastmoney.com 方案。
    10 线程并行抓取，预期耗时 < 5 秒。

    返回：
        pandas.DataFrame: 全市场股票实时行情（字段兼容原 data_fetcher）
    """
    print("  正在从 Sina 快速抓取全市场实时行情...")
    print("  （10 线程并行，预计 < 5 秒）")

    start_time = time.time()

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
        raise RuntimeError(
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

    return df
