"""src 包初始化文件"""

# 数据源内部函数
from .fast_fetcher import fetch_realtime_quotes_sina, fetch_realtime_quotes_tencent, fetch_realtime_quotes_cache
from .data_fetcher import (
    fetch_realtime_quotes_eastmoney,
    fetch_history_kline,
    fetch_baostock_history,
    fetch_sector_data,
    fetch_money_flow,
    fetch_realtime_by_codes,
)


def fetch_realtime_quotes():
    """
    多数据源 Fallback 获取 A 股全市场实时行情

    Fallback 链：Sina（快，~5s）→ AKShare/Eastmoney（慢，~30s）→ 缓存

    返回：
        pandas.DataFrame: 全市场股票实时行情
    """
    import os
    from config import DATA_SOURCE_ORDER, DATA_CACHE_FILE

    sources = {
        'sina': fetch_realtime_quotes_sina,
        'tencent': fetch_realtime_quotes_tencent,
        'eastmoney': fetch_realtime_quotes_eastmoney,
        'cache': fetch_realtime_quotes_cache,
    }

    for source_name in DATA_SOURCE_ORDER:
        if source_name not in sources:
            continue
        print(f"  尝试数据源: {source_name}...")
        try:
            df, err = sources[source_name]()
            if df is not None and not df.empty:
                print(f"  [OK] 数据源 {source_name} 成功，获取 {len(df)} 只股票")
                # 在线数据源成功后缓存
                if source_name != 'cache':
                    try:
                        os.makedirs(os.path.dirname(DATA_CACHE_FILE), exist_ok=True)
                        df.to_parquet(DATA_CACHE_FILE, index=False)
                    except Exception:
                        pass  # 缓存失败不阻断
                return df
            else:
                print(f"  [WARN] 数据源 {source_name} 失败: {err}")
        except Exception as e:
            print(f"  [WARN] 数据源 {source_name} 异常: {e}")

    raise RuntimeError("所有数据源均失败，无法获取行情数据")


from .stock_filter import (
    load_and_clean,
    build_watchlist,
    calculate_score,
    calculate_score_v2,
    filter_overnight_candidates,
    filter_momentum_stocks,
    sector_strength_analysis,
    _normalize_columns,
)
from .risk_control import (
    assess_risks,
    get_risk_report,
    check_limit_up_risk,
    check_volume_anomaly,
)
from .exporter import (
    export_to_excel,
    export_sector_report,
    export_backtest_result,
)
from .utils import print_section, save_log, format_amount, is_trading_time
from .strategy import (
    generate_buy_signals,
    generate_sell_signals,
    generate_morning_recommendation,
    execute_paper_trade,
    get_positions,
    get_trade_history,
    get_portfolio_summary,
    get_performance_stats,
)

__all__ = [
    # data_fetcher / unified
    'fetch_realtime_quotes',
    'fetch_history_kline',
    'fetch_baostock_history',
    'fetch_sector_data',
    'fetch_money_flow',
    'fetch_realtime_by_codes',
    # stock_filter
    'load_and_clean',
    'build_watchlist',
    'calculate_score',
    'calculate_score_v2',
    'filter_overnight_candidates',
    'filter_momentum_stocks',
    'sector_strength_analysis',
    '_normalize_columns',
    # risk_control
    'assess_risks',
    'get_risk_report',
    'check_limit_up_risk',
    'check_volume_anomaly',
    # exporter
    'export_to_excel',
    'export_sector_report',
    'export_backtest_result',
    # utils
    'print_section',
    'save_log',
    'format_amount',
    'is_trading_time',
    # strategy
    'generate_buy_signals',
    'generate_sell_signals',
    'generate_morning_recommendation',
    'execute_paper_trade',
    'get_positions',
    'get_trade_history',
    'get_portfolio_summary',
    'get_performance_stats',
]
