"""
选股模块 - 负责数据清洗和强势股筛选
"""

import pandas as pd
import numpy as np
from config import (
    WATCHLIST_RULES,
    SCORE_WEIGHTS,
    SCORE_WEIGHTS_V2,
    EXCLUDE_ST,
    EXCLUDE_BEIJING,
    MARKET_INCLUDE,
    OVERNIGHT_RULES,
    SECTOR_STRENGTH_MIN_STOCKS
)


# ============================================================
# 公共工具函数
# ============================================================

def _normalize_columns(df):
    """
    标准化 DataFrame 列名——将 AKShare 各种可能的字段名统一为中文标准名
    已暴露为公开接口，供 data_fetcher 等模块复用

    返回：
        DataFrame: 列名标准化后的副本
    """
    if df is None or df.empty:
        return df

    # 常见字段名映射（标准名 -> 可能的别名列表）
    field_mappings = {
        '代码': ['代码', 'code', 'symbol', '股票代码', 'stock_code'],
        '名称': ['名称', 'name', '股票名称', 'stock_name'],
        '最新价': ['最新价', '最新价', 'close', 'current', 'price', '最新价格'],
        '涨跌幅': ['涨跌幅', 'change_pct', 'pct_change', 'pct_chg', '涨跌%', '涨幅'],
        '涨跌额': ['涨跌额', 'change', 'price_change', 'chg', '涨跌'],
        '成交量': ['成交量', 'volume', 'vol'],
        '成交额': ['成交额', 'amount', 'turnover', 'trade', '成交金额'],
        '振幅': ['振幅', 'amplitude', 'amp', '振幅%'],
        '最高': ['最高', 'high', '最高价'],
        '最低': ['最低', 'low', '最低价'],
        '今开': ['今开', 'open', '开盘', '开盘价'],
        '昨收': ['昨收', 'previous_close', 'pre_close', 'preclose', '昨收价'],
        '换手率': ['换手率', 'turnover_rate', 'turn', '换手', '换手%'],
        '市盈率': ['市盈率', 'pe', 'PE'],
        '市净率': ['市净率', 'pb', 'PB'],
        '总市值': ['总市值', 'market_cap', 'total_mv', '市值'],
        '流通市值': ['流通市值', 'float_market_cap', 'circ_mv', '流通市值'],
        '板块': ['板块', 'sector', 'market', '行业', 'industry', '板块名称'],
        '量比': ['量比', 'volume_ratio', 'vol_ratio'],
    }

    rename_dict = {}
    unmapped_found = []

    for standard_name, possible_names in field_mappings.items():
        actual = None
        for name in possible_names:
            if name in df.columns:
                actual = name
                break
        if actual and actual != standard_name:
            rename_dict[actual] = standard_name
        elif actual is None:
            unmapped_found.append(standard_name)

    if rename_dict:
        df = df.rename(columns=rename_dict)

    # 不报错，只记录未映射的字段（某些字段在不同数据源可能不存在）
    if unmapped_found:
        core_missing = [f for f in unmapped_found if f in ['代码', '名称', '最新价', '涨跌幅']]
        if core_missing:
            print(f"  [WARN] 核心字段未找到: {core_missing}，实际列名: {list(df.columns)[:20]}")

    return df


# ============================================================
# 数据清洗
# ============================================================

def load_and_clean(df):
    """
    基础数据清洗：
    1. 去掉 ST、*ST 股票
    2. 去掉北交所股票（第一版只保留沪深主板、创业板、科创板）
    3. 将涨跌幅、成交额、换手率、振幅等字段转换为数值类型
    4. 处理缺失值

    参数：
        df: 原始行情数据（从 AKShare 获取）

    返回：
        pandas.DataFrame: 清洗后的数据
    """
    if df is None or df.empty:
        raise ValueError("原始数据为空，无法进行清洗")

    df = df.copy()

    # ---- 1. 标准化字段名 ----
    df = _normalize_columns(df)

    # ---- 2. 转换数值类型 ----
    numeric_fields = [
        '最新价', '涨跌幅', '涨跌额', '成交量', '成交额',
        '振幅', '最高', '最低', '今开', '昨收',
        '换手率', '市盈率', '市净率', '总市值', '流通市值'
    ]

    for field in numeric_fields:
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors='coerce')

    # ---- 3. 去除 ST、*ST 股票 ----
    if EXCLUDE_ST and '名称' in df.columns:
        before_count = len(df)
        df = df[~df['名称'].str.contains('ST', na=False)]
        after_count = len(df)
        print(f"  [清洗] 去除 ST/*ST 股票: {before_count} -> {after_count}")

    # ---- 4. 去除北交所股票 ----
    if EXCLUDE_BEIJING and '代码' in df.columns:
        before_count = len(df)
        codes = df['代码'].astype(str)
        is_beijing = codes.str.startswith(('8', '9')) | codes.str.lower().str.startswith('bj')
        df = df[~is_beijing]
        after_count = len(df)
        print(f"  [清洗] 去除北交所股票: {before_count} -> {after_count}")

    # ---- 5. 处理缺失值 ----
    key_fields = ['代码', '名称', '最新价', '涨跌幅']
    df = df.dropna(subset=[f for f in key_fields if f in df.columns])

    print(f"  [清洗] 完成，最终有效股票数: {len(df)}")

    return df


# ============================================================
# 强势股筛选
# ============================================================

def build_watchlist(df):
    """
    强势股观察池筛选
    根据 WATCHLIST_RULES 筛选符合条件的股票

    参数：
        df: 清洗后的股票数据

    返回：
        pandas.DataFrame: 符合筛选条件的股票
    """
    if df is None or df.empty:
        return df

    rules = WATCHLIST_RULES

    print(f"\n  强势股筛选规则:")
    print(f"    涨跌幅 >= {rules['涨跌幅_min']}%")
    print(f"    成交额 >= {rules['成交额_min']/1e8:.1f} 亿元")
    print(f"    换手率 >= {rules['换手率_min']}%")
    print(f"    振幅   <= {rules['振幅_max']}%")

    total = len(df)

    conditions = pd.Series([True] * len(df), index=df.index)

    if '涨跌幅' in df.columns:
        conditions &= (df['涨跌幅'] >= rules['涨跌幅_min'])
        print(f"    -> 涨跌幅 >= {rules['涨跌幅_min']}% 后剩余: {conditions.sum()}")

    if '成交额' in df.columns:
        conditions &= (df['成交额'] >= rules['成交额_min'])
        print(f"    -> 成交额 >= {rules['成交额_min']/1e8:.1f}亿 后剩余: {conditions.sum()}")

    if '换手率' in df.columns:
        conditions &= (df['换手率'] >= rules['换手率_min'])
        print(f"    -> 换手率 >= {rules['换手率_min']}% 后剩余: {conditions.sum()}")

    if '振幅' in df.columns:
        conditions &= (df['振幅'] <= rules['振幅_max'])
        print(f"    -> 振幅 <= {rules['振幅_max']}% 后剩余: {conditions.sum()}")

    watchlist = df[conditions].copy()
    watchlist = calculate_score(watchlist)
    watchlist = watchlist.sort_values('score', ascending=False)

    print(f"\n  入选强势股观察池: {len(watchlist)} 只（原始 {total} 只）")

    return watchlist


def calculate_score(df):
    """
    计算股票综合评分
    评分维度：涨跌幅、成交额、换手率、振幅稳定性
    """
    if df is None or df.empty:
        return df

    weights = SCORE_WEIGHTS

    def normalize(series, higher_is_better=True):
        """Min-Max 归一化到 0-100"""
        if series.max() == series.min():
            return pd.Series(50, index=series.index)
        if higher_is_better:
            return (series - series.min()) / (series.max() - series.min()) * 100
        else:
            return (series.max() - series) / (series.max() - series.min()) * 100

    score_components = {}

    if '涨跌幅' in df.columns:
        score_components['rise_score'] = normalize(df['涨跌幅'], higher_is_better=True)

    if '成交额' in df.columns:
        score_components['amount_score'] = normalize(df['成交额'], higher_is_better=True)

    if '换手率' in df.columns:
        score_components['turnover_score'] = normalize(df['换手率'], higher_is_better=True)

    if '振幅' in df.columns:
        score_components['amplitude_score'] = normalize(df['振幅'], higher_is_better=False)

    total_weight = 0
    weighted_sum = pd.Series(0.0, index=df.index)

    for key, weight in [('rise_score', weights['涨跌幅']),
                         ('amount_score', weights['成交额']),
                         ('turnover_score', weights['换手率']),
                         ('amplitude_score', weights['振幅_稳定'])]:
        if key in score_components:
            total_weight += weight
            weighted_sum += score_components[key].fillna(0) * weight

    if total_weight > 0:
        score = weighted_sum / total_weight
    else:
        score = pd.Series(0, index=df.index)

    df = df.copy()
    df['score'] = score.round(2)

    return df


# ============================================================
# 扩展接口实现
# ============================================================

def filter_overnight_candidates(df):
    """
    一夜持股法候选池筛选（14:30 执行）— 增强版

    五重筛选：
    1. 涨幅 3%-5%（有动能不过热）
    2. 量比 >= 1.2（放量确认）
    3. 换手率适中（主板5-15%，创业板8-15%）
    4. 振幅 <= 10%（走势稳健）
    5. 收盘价/最高价 >= 97%（强势收盘）
    """
    if df is None or df.empty:
        return df

    rules = OVERNIGHT_RULES
    df = df.copy()

    print(f"\n  一夜持股法筛选 (14:30 尾盘):")
    print(f"    涨幅: {rules['rise_min']}%~{rules['rise_max']}%")
    print(f"    换手: 主板{rules['turnover_min_main']}%-{rules['turnover_max']}% 创{rules['turnover_min_gem']}%-{rules['turnover_max']}%")
    print(f"    振幅 <= {rules['amplitude_max']}%")
    print(f"    收盘/最高 >= {rules['close_near_high']*100:.0f}%")

    conditions = pd.Series([True] * len(df), index=df.index)

    # ---- 1. 涨幅区间 ----
    if '涨跌幅' in df.columns:
        conditions &= (df['涨跌幅'] >= rules['rise_min'])
        conditions &= (df['涨跌幅'] <= rules['rise_max'])
        print(f"    涨幅 {rules['rise_min']}%-{rules['rise_max']}%: {conditions.sum()}")

    # ---- 2. 量比过滤（数据缺失时跳过） ----
    if '量比' in df.columns and 'volume_ratio_min' in rules:
        valid_qb = df['量比'].notna() & (df['量比'] > 0)
        if valid_qb.sum() > 0:
            conditions &= (~valid_qb) | (df['量比'] >= rules['volume_ratio_min'])
            print(f"    量比 >= {rules['volume_ratio_min']}: {conditions.sum()}")
        else:
            print(f"    量比: 数据全空，跳过")
    else:
        print(f"    量比: 字段不存在，跳过")

    # ---- 3. 换手率 ----
    if '换手率' in df.columns and '代码' in df.columns:
        def turnover_ok(row):
            code = str(row['代码'])
            tr = row['换手率']
            if pd.isna(tr) or tr <= 0:
                return False
            tr_min = rules['turnover_min_gem'] if code.startswith(('300', '688')) else rules['turnover_min_main']
            return tr_min <= tr <= rules['turnover_max']
        conditions &= df.apply(turnover_ok, axis=1)
        print(f"    换手率适中: {conditions.sum()}")

    # ---- 4. 振幅 ----
    if '振幅' in df.columns:
        conditions &= (df['振幅'] <= rules['amplitude_max'])
        print(f"    振幅 <= {rules['amplitude_max']}%: {conditions.sum()}")

    # ---- 5. 收盘强度 ----
    if '最新价' in df.columns and '最高' in df.columns and '今开' in df.columns:
        valid = df['最高'] > 0
        close_ratio = pd.Series(0.9, index=df.index)
        close_ratio[valid] = df['最新价'][valid] / df['最高'][valid]
        conditions &= (close_ratio >= rules['close_near_high'])
        print(f"    收盘/最高 >= {rules['close_near_high']*100:.0f}%: {conditions.sum()}")

        # 收盘强度评分
        df['close_strength'] = ((close_ratio - 0.9) / 0.1 * 100).clip(0, 100).round(1).fillna(0)

        # 日内趋势评分（收盘 vs 开盘）
        trend = pd.Series(50.0, index=df.index)
        valid_open = (df['今开'] > 0) & df['最新价'].notna() & df['今开'].notna()
        if valid_open.sum() > 0:
            trend[valid_open] = ((df['最新价'][valid_open] - df['今开'][valid_open]) / df['今开'][valid_open] * 100).clip(-3, 10).fillna(0)
        df['trend_score'] = trend.round(1).fillna(0)

    # ---- 6. 成交额（watchlist已过滤 >=1亿，跳过） ----
    pass

    candidates = df[conditions].copy()

    # 综合评分：收盘强度(40%) + 趋势(30%) + 涨幅(20%) + 量比(10%)
    score = pd.Series(0.0, index=candidates.index)
    if 'close_strength' in candidates.columns:
        score += candidates['close_strength'].fillna(0) * 0.4
    if 'trend_score' in candidates.columns:
        score += candidates['trend_score'].fillna(0) * 0.3
    if '涨跌幅' in candidates.columns:
        score += (candidates['涨跌幅'].fillna(0) / 5.0 * 100).clip(0, 100) * 0.2
    if '量比' in candidates.columns:
        score += (candidates['量比'].fillna(1.0) / 3.0 * 100).clip(0, 100) * 0.1
    score = score.fillna(0).clip(0, 200)
    candidates['overnight_score'] = score.round(1)
    candidates = candidates.sort_values('overnight_score', ascending=False)

    print(f"  一夜持股候选: {len(candidates)} 只（原始 {len(df)} 只）")
    return candidates


def sector_strength_analysis(df):
    """
    板块强度分析——统计各板块（行业）内入选强势股的数量和平均表现

    返回：
        pandas.DataFrame: 板块强度排名，含入选数、平均涨幅、平均评分等
    """
    if df is None or df.empty:
        return pd.DataFrame()

    min_stocks = SECTOR_STRENGTH_MIN_STOCKS

    # 确定板块字段
    sector_col = None
    for col in ['板块', '行业', 'sector', 'industry']:
        if col in df.columns:
            sector_col = col
            break

    if sector_col is None:
        print("  [WARN] 未找到板块字段，无法进行板块强度分析")
        return pd.DataFrame()

    # 按板块聚合统计
    agg_dict = {'代码': 'count'}
    if '涨跌幅' in df.columns:
        agg_dict['涨跌幅'] = 'mean'
    if 'score' in df.columns:
        agg_dict['score'] = 'mean'
    if '成交额' in df.columns:
        agg_dict['成交额'] = 'mean'

    sector_stats = df.groupby(sector_col).agg(agg_dict).reset_index()
    sector_stats = sector_stats.rename(columns={'代码': '入选数量'})

    if '涨跌幅' in sector_stats.columns:
        sector_stats['涨跌幅'] = sector_stats['涨跌幅'].round(2)
    if 'score' in sector_stats.columns:
        sector_stats['score'] = sector_stats['score'].round(2)
    if '成交额' in sector_stats.columns:
        sector_stats['成交额'] = sector_stats['成交额'] / 1e8  # 转为亿元

    # 只保留至少 N 只股票入选的板块
    sector_stats = sector_stats[sector_stats['入选数量'] >= min_stocks]

    # 按入选数量降序排列
    sector_stats = sector_stats.sort_values('入选数量', ascending=False)

    print(f"  板块强度分析完成: {len(sector_stats)} 个有效板块（>= {min_stocks} 只入选）")
    if len(sector_stats) > 0:
        top3 = sector_stats.head(3)
        for _, row in top3.iterrows():
            print(f"    {row[sector_col]}: {row['入选数量']}只入选, 均涨幅{row.get('涨跌幅', 0):+.2f}%")

    return sector_stats


# ============================================================
# V2 增强评分
# ============================================================

def calculate_score_v2(df):
    """
    增强版综合评分 — 7个维度

    新增维度：
    - 量比：大于1表示放量，放量上涨更健康
    - 趋势强度：(最新价-开盘价)/开盘价，日内持续走强
    - 市值适配：中等市值（50-500亿）得分更高，过小或过大扣分
    """
    if df is None or df.empty:
        return df

    weights = SCORE_WEIGHTS_V2

    def normalize(series, higher_is_better=True):
        if series.max() == series.min():
            return pd.Series(50.0, index=series.index)
        if higher_is_better:
            return (series - series.min()) / (series.max() - series.min()) * 100
        else:
            return (series.max() - series) / (series.max() - series.min()) * 100

    scores = {}

    # 1. 涨跌幅
    if '涨跌幅' in df.columns:
        scores['涨跌幅'] = normalize(df['涨跌幅'], higher_is_better=True)

    # 2. 成交额
    if '成交额' in df.columns:
        scores['成交额'] = normalize(df['成交额'], higher_is_better=True)

    # 3. 换手率
    if '换手率' in df.columns:
        scores['换手率'] = normalize(df['换手率'], higher_is_better=True)

    # 4. 振幅稳定性
    if '振幅' in df.columns:
        scores['振幅_稳定'] = normalize(df['振幅'], higher_is_better=False)

    # 5. 量比（新）
    if '量比' in df.columns:
        qb = df['量比'].fillna(1.0).clip(0.1, 10)
        scores['量比'] = normalize(qb, higher_is_better=True)
    else:
        scores['量比'] = pd.Series(50.0, index=df.index)

    # 6. 趋势强度（新）=(最新-今开)/今开
    if '最新价' in df.columns and '今开' in df.columns:
        trend = ((df['最新价'] - df['今开']) / df['今开'].replace(0, np.nan)).fillna(0) * 100
        trend = trend.clip(-5, 10)
        scores['趋势强度'] = normalize(trend, higher_is_better=True)
    else:
        scores['趋势强度'] = pd.Series(50.0, index=df.index)

    # 7. 市值适配（新）：中等市值加分
    if '总市值' in df.columns:
        mcap = df['总市值'].fillna(0) / 1e8  # 转为亿元
        # 高斯型：50-500亿最优，偏离则扣分
        optimal = 150
        sigma = 300 / np.sqrt(2 * np.log(2))  # 半高宽300亿
        mcap_score = np.exp(-((mcap - optimal) ** 2) / (2 * sigma ** 2)) * 100
        scores['市值适配'] = pd.Series(mcap_score.values if hasattr(mcap_score, 'values') else mcap_score, index=df.index)
    else:
        scores['市值适配'] = pd.Series(50.0, index=df.index)

    # 加权合成
    weighted_sum = pd.Series(0.0, index=df.index)
    total_weight = 0

    for key, weight in weights.items():
        if key in scores and weight > 0:
            total_weight += weight
            weighted_sum += scores[key].fillna(50) * weight

    if total_weight > 0:
        final_score = (weighted_sum / total_weight).round(2)
    else:
        final_score = pd.Series(0.0, index=df.index)

    df = df.copy()
    df['score_v2'] = final_score
    # 与原始评分取均值作为最终评分（平滑过渡）
    if 'score' in df.columns:
        df['score'] = ((df['score'] + df['score_v2']) / 2).round(2)
    else:
        df['score'] = df['score_v2']

    return df


def filter_momentum_stocks(df, consecutive_days=2):
    """
    动量选股：筛选连续多日上涨的股票

    依赖列：'涨跌幅' 必须在 clean 阶段已计算
    由于实时数据只有当日涨跌幅，此函数标记当日强动量股票

    返回：DataFrame with 'momentum_tag' column
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 当日动量判断：涨幅>3% 且 收盘价接近最高价(>97%)
    tags = []
    for idx in df.index:
        chg = float(df.at[idx, '涨跌幅']) if '涨跌幅' in df.columns and pd.notna(df.at[idx, '涨跌幅']) else 0
        close = float(df.at[idx, '最新价']) if '最新价' in df.columns and pd.notna(df.at[idx, '最新价']) else 0
        high = float(df.at[idx, '最高']) if '最高' in df.columns and pd.notna(df.at[idx, '最高']) else 0

        if chg > 3 and high > 0 and close / high > 0.97:
            tags.append('强动量')
        elif chg > 2:
            tags.append('一般动量')
        else:
            tags.append('非动量')

    df['momentum_tag'] = tags
    return df
