"""src 包初始化文件"""

# 快速抓取模块优先
from .fast_fetcher import fetch_realtime_quotes as _fast_fetch_realtime

# 传统 AKShare 抓取
from .data_fetcher import (
    fetch_history_kline,
    fetch_baostock_history,
    fetch_sector_data,
    fetch_money_flow,
    fetch_realtime_by_codes,
)

# fetch_realtime_quotes 优先使用快速版本
fetch_realtime_quotes = _fast_fetch_realtime
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
    # data_fetcher
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
