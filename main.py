"""
A 股半量化选股系统 v3.0 — 模拟交易辅助工具
新增：策略引擎、V2评分、买卖信号、闭环跟踪
"""
import sys
import datetime
from config import *

# === 数据抓取 ===
try:
    from src.fast_fetcher import fetch_realtime_quotes
except ImportError:
    from src.data_fetcher import fetch_realtime_quotes

# === 选股 ===
from src.stock_filter import build_watchlist, calculate_score_v2, filter_momentum_stocks

# === 风控 ===
from src.risk_control import assess_risks

# === 策略 ===
from src.strategy import (
    generate_buy_signals, generate_sell_signals,
    generate_morning_recommendation, get_positions,
    get_portfolio_summary, get_performance_stats,
)

# === 导出 ===
from src.exporter import export_to_excel

# === 工具 ===
from src.utils import print_section, save_log


def run():
    """主流程 v3.0"""
    print("\n" + "=" * 60)
    print("  A 股 半量化选股系统  v3.0")
    print("  模拟交易辅助 | T+1策略 | V2评分")
    print("=" * 60)

    now = datetime.datetime.now()
    print(f"\n运行时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # --- 第一步：数据抓取 ---
    print_section("第一步：抓取 A 股实时行情")
    try:
        df = fetch_realtime_quotes()
        print(f"  [OK] 获取 {len(df)} 只股票")
    except Exception as e:
        print(f"  [ERROR] 数据抓取失败: {e}")
        save_log(f"数据抓取失败: {e}")
        sys.exit(1)

    # --- 第二步：基础清洗 ---
    print_section("第二步：数据清洗")
    from src.stock_filter import load_and_clean
    try:
        df_clean = load_and_clean(df)
        print(f"  [OK] 清洗后 {len(df_clean)} 只")
    except Exception as e:
        print(f"  [ERROR] 清洗失败: {e}")
        save_log(f"清洗失败: {e}")
        sys.exit(1)

    # --- 第三步：强势股筛选 + V2评分 ---
    print_section("第三步：强势股筛选 + V2增强评分")
    try:
        watchlist = build_watchlist(df_clean)
        watchlist = calculate_score_v2(watchlist)
        watchlist = filter_momentum_stocks(watchlist)
        print(f"  [OK] 入选 {len(watchlist)} 只")
    except Exception as e:
        print(f"  [ERROR] 筛选失败: {e}")
        save_log(f"筛选失败: {e}")
        watchlist = df_clean.iloc[:0]

    # --- 第四步：风险评估 ---
    print_section("第四步：风险评估")
    try:
        watchlist = assess_risks(watchlist)
        print(f"  [OK] 风险评估完成")
    except Exception as e:
        print(f"  [ERROR] 风险评估失败: {e}")
        save_log(f"风险评估失败: {e}")

    # --- 第五步：生成 Reason ---
    print_section("第五步：生成入选理由")
    watchlist = generate_reason(watchlist)

    # --- 第六步：策略信号 ---
    print_section("第六步：策略信号生成")
    try:
        positions = get_positions()
        buy_signals = generate_buy_signals(watchlist, positions)
        sell_signals = generate_sell_signals(positions, df_clean)
        morning_recs = generate_morning_recommendation(watchlist)

        open_pos = [p for p in positions if p.get('status') == 'open']
        print(f"  当前持仓: {len(open_pos)} 只")
        print(f"  买入信号: {len(buy_signals)} 只")
        print(f"  卖出信号: {len(sell_signals)} 只")
        print(f"  早盘推荐: {len(morning_recs)} 只")
    except Exception as e:
        print(f"  [WARN] 策略信号生成: {e}")
        buy_signals, sell_signals, morning_recs = [], [], []

    # --- 第七步：输出 Excel ---
    print_section("第七步：导出 Excel")
    try:
        excel_path = export_to_excel(watchlist, df_clean)
        print(f"  [OK] {excel_path}")
    except Exception as e:
        print(f"  [ERROR] Excel导出失败: {e}")
        excel_path = None

    # --- 汇总 ---
    print_section("运行结果汇总")
    print(f"  全市场     : {len(df)} 只")
    print(f"  清洗后     : {len(df_clean)} 只")
    print(f"  强势股     : {len(watchlist)} 只")
    print(f"  早盘推荐   : {len(morning_recs)} 只")
    print(f"  买入信号   : {len(buy_signals)} 只")
    print(f"  卖出信号   : {len(sell_signals)} 只")

    # 买入信号明细
    if buy_signals:
        print(f"\n  --- 买入信号 ---")
        for s in buy_signals[:8]:
            print(f"  {s['code']} {s['name']} ¥{s['price']} sc:{s['score']} {s['risk']} {s['shares']}股 ~{s['cost']/1e4:.1f}万 | {s['reason']}")

    # 卖出信号明细
    if sell_signals:
        print(f"\n  --- 卖出信号 ---")
        for s in sell_signals[:8]:
            print(f"  {s['code']} {s['name']} 成本{s['buy_price']} 现价{s['now_price']} {s['pnl_pct']:+.2f}% [{s['urgency']}] {s['reason']}")

    # 早盘推荐
    if morning_recs:
        print(f"\n  --- 早盘精选推荐 ---")
        for i, r in enumerate(morning_recs):
            print(f"  #{i+1} {r['code']} {r['name']} ¥{r['price']} {r['chg']:+.2f}% sc:{r['score']} {r['risk']}")

    # 绩效概览
    perf = get_performance_stats()
    if perf['total_trades'] > 0:
        print(f"\n  --- 历史绩效 ---")
        print(f"  总交易: {perf['total_trades']} | 胜率: {perf['win_rate']}% | 均收益: {perf['avg_return']:+.2f}% | 累计: {perf['total_return']:+.2f}%")

    if excel_path:
        print(f"\n  Excel: {excel_path}")

    print("\n  === 仅供学习研究，不构成投资建议 ===\n")
    save_log(f"v3.0 completed: {len(watchlist)} strong, {len(buy_signals)} buy, {len(sell_signals)} sell")
    return watchlist, df_clean


def generate_reason(df):
    """
    为每只股票生成中文入选理由（reason 字段）
    方便人工参考为什么要关注这只股票
    """
    if df.empty:
        return df

    reasons = []
    for _, row in df.iterrows():
        parts = []
        rise = row.get('涨跌幅', 0)
        turnover = row.get('换手率', 0)
        amount = row.get('成交额', 0)
        amplitude = row.get('振幅', 0)
        risk = row.get('risk_level', '')

        # 分析入选原因
        if rise >= 3:
            parts.append("涨幅较强")
        elif rise >= 2:
            parts.append("温和上涨")

        if amount >= 5e8:
            parts.append("成交额充裕")
        elif amount >= 1e8:
            parts.append("成交额充足")

        if turnover >= 5:
            parts.append("换手非常活跃")
        elif turnover >= 2:
            parts.append("换手活跃")

        if amplitude <= 8:
            parts.append("波动稳定")
        elif amplitude <= 12:
            parts.append("波动适中")

        # 风险相关提示
        if risk == '高风险':
            if rise > 8:
                parts.append("高位追涨风险")
            elif amplitude > 12:
                parts.append("振幅过大风险")
            elif turnover > 20:
                parts.append("换手率过高风险")
            else:
                parts.append("注意风险")
        elif risk == '中风险':
            parts.append("谨慎关注")

        if not parts:
            parts.append("符合基础条件")

        reasons.append("；".join(parts))

    df = df.copy()
    df['reason'] = reasons
    return df


if __name__ == '__main__':
    run()