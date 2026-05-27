"""
市场状态识别模块 — 基于上证指数 SMA 判断牛/熊/震荡
用于动态调整评分权重
"""
import numpy as np
from config import REGIME_LOOKBACK_DAYS


def detect_regime(index_df=None):
    """
    检测当前市场状态

    基于 SMA5/10/20 三线排列和 5 日线性回归斜率判断：
    - bull (牛市): SMA5 > SMA10 > SMA20 且斜率 > 0.1%/天
    - bear (熊市): SMA5 < SMA10 < SMA20 且斜率 < -0.1%/天
    - range (震荡): 其它情况

    参数：
        index_df: 包含 '收盘'/'close' 列的指数日线 DataFrame
                  为 None 时尝试从 akshare 获取

    返回：
        (str, float, dict): (regime, confidence, metrics)
    """
    if index_df is None:
        index_df = _fetch_index_data()

    if index_df is None or len(index_df) < REGIME_LOOKBACK_DAYS:
        return 'range', 0.0, {'reason': '指数数据不足，默认震荡市'}

    # 获取收盘价序列
    if '收盘' in index_df.columns:
        closes = index_df['收盘'].values[-REGIME_LOOKBACK_DAYS:]
    elif 'close' in index_df.columns:
        closes = index_df['close'].values[-REGIME_LOOKBACK_DAYS:]
    else:
        return 'range', 0.0, {'reason': '未找到收盘价字段'}

    closes = np.array(closes, dtype=float)

    # 计算 SMA
    sma_5 = np.mean(closes[-5:])
    sma_10 = np.mean(closes[-10:])
    sma_20 = np.mean(closes[-20:]) if len(closes) >= 20 else sma_10

    # 5 日线性回归斜率（%/天）
    x = np.arange(min(5, len(closes)))
    y = closes[-len(x):]
    if len(x) >= 2:
        slope, _ = np.polyfit(x, y, 1)
        slope_pct = slope / closes[-1] * 100
    else:
        slope_pct = 0.0

    # 市场状态分类
    if sma_5 > sma_10 > sma_20 and slope_pct > 0.1:
        regime = 'bull'
        confidence = min(1.0, slope_pct * 5)
    elif sma_5 < sma_10 < sma_20 and slope_pct < -0.1:
        regime = 'bear'
        confidence = min(1.0, abs(slope_pct) * 5)
    else:
        regime = 'range'
        confidence = 0.5

    metrics = {
        'sma_5': round(float(sma_5), 2),
        'sma_10': round(float(sma_10), 2),
        'sma_20': round(float(sma_20), 2),
        'slope_pct': round(float(slope_pct), 3),
        'reason': f'SMA5={sma_5:.0f} SMA10={sma_10:.0f} SMA20={sma_20:.0f} slope={slope_pct:+.3f}%/day',
    }
    return regime, round(float(confidence), 2), metrics


def get_regime_weights():
    """
    获取当前市场状态下调整后的评分权重

    返回：
        (dict, str, float, dict): (adjusted_weights, regime, confidence, metrics)
    """
    from config import SCORE_WEIGHTS_V2, REGIME_WEIGHT_ADJUSTMENTS

    regime, confidence, metrics = detect_regime()
    adj = REGIME_WEIGHT_ADJUSTMENTS.get(regime, {})

    weights = dict(SCORE_WEIGHTS_V2)
    for key, delta in adj.items():
        if key in weights:
            # 按置信度缩放调整幅度
            weights[key] += int(delta * confidence)
            weights[key] = max(0, min(50, weights[key]))  # 限制 0-50

    return weights, regime, confidence, metrics


def _fetch_index_data():
    """尝试获取上证指数历史日线数据"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        return df.tail(REGIME_LOOKBACK_DAYS + 5)
    except Exception:
        return None
