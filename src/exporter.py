"""
导出模块 - 将结果输出为 Excel 文件
"""

import os
import datetime
import pandas as pd
from config import (
    OUTPUT_DIR,
    EXCEL_SHEET_NAME_WATCHLIST,
    EXCEL_SHEET_NAME_RISK,
    EXCEL_SHEET_NAME_ALL
)


def export_to_excel(watchlist, all_stocks):
    """
    将选股结果导出为 Excel 文件

    参数：
        watchlist: 强势股观察池 DataFrame
        all_stocks: 全市场股票 DataFrame

    返回：
        str: Excel 文件路径
    """
    # 生成文件名：A股强势股观察池_YYYYMMDD_HHMMSS.xlsx
    now = datetime.datetime.now()
    filename = now.strftime('A股强势股观察池_%Y%m%d_%H%M%S.xlsx')
    filepath = os.path.join(OUTPUT_DIR, filename)

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 定义需要显示的列（强势股观察池）
    watchlist_columns = [
        '代码', '名称', '最新价', '涨跌幅', '涨跌额',
        '成交额', '换手率', '振幅', '最高', '最低',
        '今开', '昨收', 'score', 'risk_level', 'risk_detail', 'reason'
    ]

    # 只保留存在的列
    watchlist_cols_final = [c for c in watchlist_columns if c in watchlist.columns]

    # 风险提示：只取中高风险的股票
    risk_df = watchlist[watchlist['risk_level'].isin(['高风险', '中风险'])].copy()
    if 'reason' in risk_df.columns:
        risk_df['风险说明'] = risk_df['reason']

    risk_cols = ['代码', '名称', '最新价', '涨跌幅', '成交额', '换手率', 'risk_level', 'risk_detail']

    # 全市场股票（只取关键字段，避免文件过大）
    all_cols = ['代码', '名称', '最新价', '涨跌幅', '涨跌额', '成交额', '换手率', '振幅', '最高', '最低']
    all_cols_final = [c for c in all_cols if c in all_stocks.columns]

    # 写入 Excel（使用 openpyxl 引擎）
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        # Sheet 1：强势股观察池
        if len(watchlist) > 0:
            watchlist[watchlist_cols_final].to_excel(
                writer, sheet_name=EXCEL_SHEET_NAME_WATCHLIST, index=False
            )

        # Sheet 2：风险提示
        if len(risk_df) > 0:
            risk_df[[c for c in risk_cols if c in risk_df.columns]].to_excel(
                writer, sheet_name=EXCEL_SHEET_NAME_RISK, index=False
            )
        else:
            # 无风险股票时创建空 sheet 并提示
            pd.DataFrame({'提示': ['本轮筛选暂无中高风险股票']}).to_excel(
                writer, sheet_name=EXCEL_SHEET_NAME_RISK, index=False
            )

        # Sheet 3：全市场股票（可选，方便查看全市场情况）
        if len(all_stocks) > 0:
            all_stocks[all_cols_final].to_excel(
                writer, sheet_name=EXCEL_SHEET_NAME_ALL, index=False
            )

    return filepath


# ============================================================
# 扩展接口实现
# ============================================================

def export_sector_report(sector_data):
    """
    导出板块强度报告为 Excel

    参数：
        sector_data: sector_strength_analysis() 返回的 DataFrame

    返回：
        str: Excel 文件路径
    """
    if sector_data is None or sector_data.empty:
        print("  [WARN] 板块数据为空，跳过报告导出")
        return None

    now = datetime.datetime.now()
    filename = now.strftime('板块强度报告_%Y%m%d_%H%M%S.xlsx')
    filepath = os.path.join(OUTPUT_DIR, filename)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        sector_data.to_excel(
            writer, sheet_name='板块强度排名', index=False
        )

    print(f"  [OK] 板块强度报告已生成: {filepath}")
    return filepath


def export_backtest_result(result):
    """
    导出回测结果为 Excel

    参数：
        result: dict，包含以下键：
            - trades: DataFrame, 每笔交易记录
            - summary: dict, 绩效概要（总收益率、胜率、最大回撤等）
            - equity_curve: DataFrame, 资金曲线

    返回：
        str: Excel 文件路径
    """
    if result is None:
        print("  [WARN] 回测结果为空，跳过报告导出")
        return None

    now = datetime.datetime.now()
    filename = now.strftime('回测结果_%Y%m%d_%H%M%S.xlsx')
    filepath = os.path.join(OUTPUT_DIR, filename)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        # Sheet 1：绩效概要
        if 'summary' in result and result['summary']:
            summary_df = pd.DataFrame([result['summary']])
            summary_df.to_excel(writer, sheet_name='绩效概要', index=False)

        # Sheet 2：交易记录
        if 'trades' in result and result['trades'] is not None:
            trades_df = result['trades']
            if not trades_df.empty:
                trades_df.to_excel(writer, sheet_name='交易记录', index=False)

        # Sheet 3：资金曲线
        if 'equity_curve' in result and result['equity_curve'] is not None:
            curve_df = result['equity_curve']
            if not curve_df.empty:
                curve_df.to_excel(writer, sheet_name='资金曲线', index=False)

    print(f"  [OK] 回测结果已生成: {filepath}")
    return filepath