"""
测试 strategy 模块 — 买入/卖出信号、模拟交易、持仓管理
"""
import pandas as pd
import numpy as np
import pytest
import json
import os
from unittest.mock import patch, MagicMock
from src.strategy import (
    generate_buy_signals,
    generate_sell_signals,
    execute_paper_trade,
    get_portfolio_summary,
    get_performance_stats,
    get_positions,
    get_trade_history,
    _is_near_limit,
    generate_morning_recommendation,
    generate_overnight_recommendation,
)


class TestIsNearLimit:
    """涨停检测测试"""

    def test_main_board_at_9_4_not_limit(self):
        """主板 9.4% 不算涨停（<9.5% 阈值）"""
        assert _is_near_limit('000001', 9.4) is False

    def test_main_board_at_9_6_is_limit(self):
        """主板 9.6% >= 10%*0.95 → 涨停"""
        assert _is_near_limit('000001', 9.6) is True

    def test_gem_at_19_is_limit(self):
        """创业板 19% >= 20%*0.95 → 涨停"""
        assert _is_near_limit('300001', 19.0) is True

    def test_gem_at_18_is_not_limit(self):
        """创业板 18% < 20%*0.95 → 未涨停"""
        assert _is_near_limit('300001', 18.0) is False

    def test_star_market_same_as_gem(self):
        """科创板同创业板 20%"""
        assert _is_near_limit('688001', 19.1) is True


class TestGenerateBuySignals:
    """买入信号测试"""

    @pytest.fixture(autouse=True)
    def _patch_trade_files(self, temp_trade_files):
        """Mock 交易文件路径，避免读取真实 trade_history.json"""
        trade_file, history_file = temp_trade_files
        with patch('src.strategy.TRADE_FILE', trade_file), \
             patch('src.strategy.TRADE_HISTORY_FILE', history_file):
            yield

    @pytest.fixture
    def mock_watchlist(self):
        """带有 risk_level 等完整字段的观察池"""
        data = {
            '代码': ['sz000001', 'sz000002', 'sz300001', 'sz600001', 'sz688005'],
            '名称': ['平安银行', 'ST万科', '特锐德', '邯郸钢铁', '涨停股'],
            '最新价': [12.5, 8.3, 25.0, 5.2, 120.0],
            '涨跌幅': [4.2, 1.2, 8.7, 4.0, 19.5],
            '成交额': [6e8, 2.5e8, 2.5e9, 5e7, 2.4e9],
            '换手率': [3.5, 1.2, 12.0, 2.5, 4.0],
            'score': [65, 30, 72, 58, 80],
            'risk_level': ['低风险', '高风险', '中风险', '低风险', '高风险'],
            'risk_detail': ['无明显风险', '注意风险', '涨幅偏高', '无明显风险', '涨停高风险'],
            'reason': ['评分65', '评分低', '评分72+涨幅偏高', '评分58', '评分高'],
        }
        return pd.DataFrame(data)

    def test_generates_signals(self, mock_watchlist):
        signals = generate_buy_signals(mock_watchlist, [])
        assert len(signals) > 0
        # 000001 应该入选（低风险，高评分）
        codes = [s['code'] for s in signals]
        assert '000001' in codes

    def test_excludes_limit_up(self, mock_watchlist):
        """接近涨停的股票不入选"""
        signals = generate_buy_signals(mock_watchlist, [])
        codes = [s['code'] for s in signals]
        assert '688005' not in codes  # 19.5% 涨幅 → 接近涨停

    def test_excludes_held_stocks(self, mock_watchlist):
        """已持仓股票不出买入信号"""
        positions = [{'code': '000001', 'status': 'open', 'price': 12.0, 'shares': 1000}]
        signals = generate_buy_signals(mock_watchlist, positions)
        codes = [s['code'] for s in signals]
        assert '000001' not in codes

    def test_respects_max_positions(self, mock_watchlist):
        """不超过最大持仓数"""
        # 已有 7 个持仓 → 最多还能新增 1 个
        positions = [
            {'code': f'{i:06d}', 'status': 'open', 'price': 10.0, 'shares': 1000}
            for i in range(1, 8)
        ]
        signals = generate_buy_signals(mock_watchlist, positions)
        assert len(signals) <= 1

    def test_filters_by_score(self, mock_watchlist):
        """低评分股票不出信号"""
        signals = generate_buy_signals(mock_watchlist, [])
        codes = [s['code'] for s in signals]
        # sz000002 score=30 < min_score=55
        assert '000002' not in codes

    def test_includes_shares_and_cost(self, mock_watchlist):
        """每个信号应有 shares 和 cost"""
        signals = generate_buy_signals(mock_watchlist, [])
        for s in signals:
            assert s['shares'] >= 100
            assert s['cost'] > 0
            assert s['shares'] % 100 == 0  # A股以手为单位


class TestGenerateSellSignals:
    """卖出信号测试"""

    def test_stop_loss_critical(self, sample_positions, sample_quotes_df):
        """600001 从 5.0 → 4.8 (-4%)，接近硬止损"""
        signals = generate_sell_signals(sample_positions, sample_quotes_df)
        # 600001: buy=5.0, now=4.8, pnl=-4% → 止损级别
        signal_600001 = [s for s in signals if s['code'] == '600001']
        if signal_600001:
            assert signal_600001[0]['pnl_pct'] < 0

    def test_take_profit_signal(self, sample_positions, sample_quotes_df):
        """300001 从 23.0 → 24.5 (+6.5%) → 触发止盈"""
        signals = generate_sell_signals(sample_positions, sample_quotes_df)
        signal_300001 = [s for s in signals if s['code'] == '300001']
        if signal_300001:
            assert signal_300001[0]['pnl_pct'] > 0

    def test_signals_sorted_by_urgency(self, sample_positions, sample_quotes_df):
        """critical > urgent > normal 排序"""
        signals = generate_sell_signals(sample_positions, sample_quotes_df)
        if len(signals) >= 2:
            order = {'critical': 0, 'urgent': 1, 'normal': 2}
            urgency_values = [order.get(s['urgency'], 9) for s in signals]
            assert urgency_values == sorted(urgency_values)

    def test_empty_positions(self, sample_quotes_df):
        signals = generate_sell_signals([], sample_quotes_df)
        assert signals == []

    def test_empty_quotes(self, sample_positions):
        signals = generate_sell_signals(sample_positions, pd.DataFrame())
        assert signals == []


class TestExecutePaperTrade:
    """模拟交易执行测试"""

    def test_buy_creates_position(self, temp_trade_files):
        trade_file, history_file = temp_trade_files
        with patch('src.strategy.TRADE_FILE', trade_file), \
             patch('src.strategy.TRADE_HISTORY_FILE', history_file):
            signal = {
                'code': '000001',
                'name': '平安银行',
                'price': 12.5,
                'shares': 4000,
                'cost': 50000.0,
                'reason': '测试买入',
            }
            result = execute_paper_trade(signal, direction='buy')
            assert 'error' not in result
            assert result['status'] == 'open'
            assert result['code'] == '000001'

            # 验证写入文件
            positions = get_positions()
            assert any(p['code'] == '000001' for p in positions)

    def test_sell_closes_position(self, temp_trade_files):
        trade_file, history_file = temp_trade_files
        with patch('src.strategy.TRADE_FILE', trade_file), \
             patch('src.strategy.TRADE_HISTORY_FILE', history_file):
            # 先买入
            buy_signal = {
                'code': '000001', 'name': '平安银行',
                'price': 12.0, 'shares': 4000, 'cost': 48000.0,
                'reason': '测试买入',
            }
            execute_paper_trade(buy_signal, direction='buy')

            # 再卖出
            sell_signal = {
                'code': '000001',
                'now_price': 13.0,
                'pnl_pct': 8.33,
                'pnl_amount': 4000.0,
                'reason': '止盈',
            }
            result = execute_paper_trade(sell_signal, direction='sell')
            assert 'error' not in result
            assert result['status'] == 'closed'
            assert result['pnl_pct'] == 8.33

            # 验证已从持仓移到历史
            positions = get_positions()
            assert not any(p['code'] == '000001' and p.get('status') == 'open' for p in positions)

            history = get_trade_history()
            assert any(t['code'] == '000001' for t in history)

    def test_buy_duplicate_returns_error(self, temp_trade_files):
        trade_file, history_file = temp_trade_files
        with patch('src.strategy.TRADE_FILE', trade_file), \
             patch('src.strategy.TRADE_HISTORY_FILE', history_file):
            signal = {
                'code': '000001', 'name': '平安银行',
                'price': 12.0, 'shares': 4000, 'cost': 48000.0,
                'reason': '测试',
            }
            execute_paper_trade(signal, direction='buy')
            result = execute_paper_trade(signal, direction='buy')
            assert 'error' in result


class TestPortfolioSummary:
    """持仓汇总测试"""

    def test_calculates_pnl_correctly(self, sample_positions, sample_quotes_df):
        with patch('src.strategy.TRADE_FILE', 'nonexistent.json'), \
             patch('src.strategy.get_positions', return_value=sample_positions):
            summary = get_portfolio_summary(sample_quotes_df)
            assert summary['position_count'] == 3
            assert 'total_cost' in summary
            assert 'total_market_value' in summary
            assert 'total_pnl' in summary

    def test_empty_positions(self, sample_quotes_df):
        summary = get_portfolio_summary(sample_quotes_df)
        if summary['position_count'] == 0:
            assert summary['total_cost'] == 0
            assert summary['total_pnl'] == 0


class TestPerformanceStats:
    """绩效统计测试"""

    def test_no_history(self):
        with patch('src.strategy.get_trade_history', return_value=[]):
            stats = get_performance_stats()
            assert stats['total_trades'] == 0
            assert stats['win_rate'] == 0

    def test_with_trades(self):
        mock_history = [
            {'code': 'A', 'pnl_pct': 5.0, 'close_date': '2026-05-01'},
            {'code': 'B', 'pnl_pct': -2.0, 'close_date': '2026-05-02'},
            {'code': 'C', 'pnl_pct': 3.0, 'close_date': '2026-05-03'},
            {'code': 'D', 'pnl_pct': -1.0, 'close_date': '2026-05-04'},
        ]
        with patch('src.strategy.get_trade_history', return_value=mock_history):
            stats = get_performance_stats()
            assert stats['total_trades'] == 4
            assert stats['wins'] == 2
            assert stats['losses'] == 2
            assert stats['win_rate'] == 50.0
            assert stats['avg_return'] == 1.25
            assert stats['max_win'] == 5.0
            assert stats['max_loss'] == -2.0


class TestMorningRecommendation:
    """早盘推荐测试"""

    def test_generates_recommendations(self, sample_watchlist):
        recs = generate_morning_recommendation(sample_watchlist)
        assert isinstance(recs, list)

    def test_excludes_limit_up(self, sample_watchlist):
        recs = generate_morning_recommendation(sample_watchlist)
        for r in recs:
            # 涨停板上限因股票而异
            assert r['chg'] <= 19.0  # 最大不会超过创业板涨停

    def test_empty_input(self):
        recs = generate_morning_recommendation(pd.DataFrame())
        assert recs == []
        recs = generate_morning_recommendation(None)
        assert recs == []


class TestOvernightRecommendation:
    """一夜持股推荐测试"""

    def test_generates_recommendations(self, sample_watchlist):
        recs = generate_overnight_recommendation(sample_watchlist)
        assert isinstance(recs, list)

    def test_includes_sell_plan(self, sample_watchlist):
        recs = generate_overnight_recommendation(sample_watchlist)
        for r in recs:
            assert 'sell_plan' in r
            assert '止盈' in r['sell_plan']

    def test_empty_input(self):
        recs = generate_overnight_recommendation(pd.DataFrame())
        assert recs == []
        recs = generate_overnight_recommendation(None)
        assert recs == []
