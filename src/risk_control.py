"""
风控模块 - 评估股票风险等级
不是删除股票，而是给每只股票打上风险标签
方便人工判断哪些可以关注，哪些需要谨慎
"""

import pandas as pd
from config import RISK_RULES


def assess_risks(df):
    """
    对入选强势股的股票进行风险评估
    为每只股票标记 risk_level 和具体风险原因

    风险等级：
    - 低风险：符合基础条件，风险较低
    - 中风险：需要关注，有个别风险点
    - 高风险：风险较高，需谨慎

    参数：
        df: 入选强势股的 DataFrame

    返回：
        DataFrame: 新增 risk_level, risk_detail 列
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    rules = RISK_RULES

    # 初始化风险相关列
    df['risk_level'] = '低风险'
    df['risk_detail'] = ''

    # 安全获取列值的辅助函数
    def safe_get(df, idx, col, default=0):
        """安全获取 DataFrame 单元格值，列不存在时返回默认值"""
        if col not in df.columns:
            return default
        val = df.at[idx, col]
        return val if pd.notna(val) else default

    # 风险条件逐个检查
    for idx in df.index:
        risk_points = []
        risk_level = '低风险'

        rise = safe_get(df, idx, '涨跌幅', 0)
        amplitude = safe_get(df, idx, '振幅', 0)
        turnover = safe_get(df, idx, '换手率', 0)
        amount = safe_get(df, idx, '成交额', 0)
        code = str(safe_get(df, idx, '代码', ''))

        # ---- 风险点 1：涨幅过高 ----
        if rise > rules['rise_high_threshold']:
            risk_level = '中风险'
            risk_points.append(f"涨幅偏高({rise:.1f}%)")

        # ---- 风险点 2：创业板/科创板涨幅过高 ----
        # 创业板代码以 '300' 开头，科创板以 '688' 开头
        if code.startswith(('300', '688')):
            if rise > rules['rise_chi_next_threshold']:
                risk_level = '高风险'
                risk_points.append(f"双创涨幅过大({rise:.1f}%)")

        # ---- 风险点 3：振幅过大 ----
        if amplitude > rules['amplitude_high_threshold']:
            risk_level = '高风险'
            risk_points.append(f"振幅过大({amplitude:.1f}%)")

        # ---- 风险点 4：换手率过高 ----
        if turnover > rules['turnover_high_threshold']:
            risk_level = '高风险'
            risk_points.append(f"换手率过高({turnover:.1f}%)")

        # ---- 风险点 5：流动性不足 ----
        if amount < rules['amount_low_threshold']:
            risk_points.append(f"流动性不足")

        # ---- 风险点 6：疑似冲高 ----
        # 涨幅很高但成交额不足，疑似拉高出货
        if rise > rules['pump_rise_threshold'] and amount < rules['pump_amount_threshold']:
            risk_points.append(f"疑似冲高风险")

        # 更新风险等级（如果发现更高风险级别）
        if risk_points:
            if '高风险' in risk_points or risk_level == '高风险':
                df.at[idx, 'risk_level'] = '高风险'
            elif risk_level == '中风险':
                df.at[idx, 'risk_level'] = '中风险'
            else:
                df.at[idx, 'risk_level'] = '中风险'

        # 合并风险详情
        if risk_points:
            df.at[idx, 'risk_detail'] = '；'.join(risk_points)
        else:
            df.at[idx, 'risk_detail'] = '无明显风险'

    # 统计风险分布
    risk_counts = df['risk_level'].value_counts()
    print(f"  风险分布: ", end='')
    for level, count in risk_counts.items():
        print(f"{level} {count}只 ", end='')
    print()

    return df


def get_risk_report(df):
    """
    生成风险提示报告（供 Excel 输出使用）

    返回：
        pandas.DataFrame: 只包含中高风险的股票
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 筛选高风险和中风险股票
    risk_stocks = df[df['risk_level'].isin(['高风险', '中风险'])].copy()

    # 按风险等级排序（高风险在前）
    risk_stocks = risk_stocks.sort_values('risk_level', ascending=True)

    return risk_stocks


# ============================================================
# 扩展接口实现
# ============================================================

def check_limit_up_risk(df):
    """
    涨停板风险评估
    - 检查是否接近涨停（主板 ±10%，科创板/创业板 ±20%）
    - 接近涨停的股票次日容易高开低走，追高风险大

    返回：
        DataFrame: 新增 limit_up_risk 字段
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 判断每只股票的涨停幅度阈值
    def get_limit_threshold(code):
        code_str = str(code)
        if code_str.startswith(('300', '688')):
            return 20.0  # 创业板/科创板
        return 10.0  # 主板

    risk_tags = []
    for idx in df.index:
        code = str(df.at[idx, '代码']) if '代码' in df.columns else ''
        rise = df.at[idx, '涨跌幅'] if '涨跌幅' in df.columns else 0
        limit = get_limit_threshold(code)

        if pd.notna(rise):
            if rise >= limit * 0.95:
                risk_tags.append('已涨停/近涨停')
            elif rise >= limit * 0.85:
                risk_tags.append('接近涨停高风险')
            elif rise <= -limit * 0.9:
                risk_tags.append('接近跌停')
            else:
                risk_tags.append('正常')
        else:
            risk_tags.append('未知')

    df['limit_up_risk'] = risk_tags

    high_risk_count = sum(1 for t in risk_tags if '涨停' in t)
    print(f"  涨停板风险评估完成: {high_risk_count} 只接近涨停")
    return df


def check_volume_anomaly(df):
    """
    量能异常检测
    - 成交量突然放大但价格涨幅不匹配 → 疑似主力出货
    - 成交量极度萎缩但价格波动异常 → 流动性风险

    检测维度：
    1. 量价背离：成交额排名靠前但涨幅靠后
    2. 异常放量：成交额超过同板块均值的 3 倍

    返回：
        DataFrame: 新增 volume_anomaly 字段
    """
    if df is None or df.empty or len(df) < 5:
        return df

    df = df.copy()

    anomaly_tags = []

    # 维度1：量价背离检测
    if '成交额' in df.columns and '涨跌幅' in df.columns:
        amount_rank = df['成交额'].rank(ascending=False, pct=True)
        rise_rank = df['涨跌幅'].rank(ascending=False, pct=True)
        # 成交额排名靠前(top 20%)但涨幅排名靠后(bottom 50%) = 量价背离
        divergence = (amount_rank < 0.2) & (rise_rank > 0.5)
    else:
        divergence = pd.Series(False, index=df.index)

    # 维度2：异常放量（成交额超过全市场均值的5倍）
    if '成交额' in df.columns:
        mean_amount = df['成交额'].mean()
        if mean_amount > 0:
            abnormal_volume = df['成交额'] > (mean_amount * 5)
        else:
            abnormal_volume = pd.Series(False, index=df.index)
    else:
        abnormal_volume = pd.Series(False, index=df.index)

    # 维度3：板块内异常放量
    sector_col = None
    for col in ['板块', '行业', 'sector']:
        if col in df.columns:
            sector_col = col
            break

    sector_abnormal = pd.Series(False, index=df.index)
    if sector_col and '成交额' in df.columns:
        for sector, group in df.groupby(sector_col):
            if len(group) >= 2:
                group_mean = group['成交额'].mean()
                if group_mean > 0:
                    sector_abnormal[group.index] = group['成交额'] > (group_mean * 3)

    # 汇总异常标签
    for idx in df.index:
        tags = []
        if divergence.get(idx, False):
            tags.append('量价背离')
        if abnormal_volume.get(idx, False):
            tags.append('异常放量')
        if sector_abnormal.get(idx, False):
            tags.append('板块内异常放量')
        anomaly_tags.append('；'.join(tags) if tags else '正常')

    df['volume_anomaly'] = anomaly_tags

    anomaly_count = sum(1 for t in anomaly_tags if t != '正常')
    print(f"  量能异常检测完成: {anomaly_count} 只异常")
    return df