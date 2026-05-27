"""
测试 stock_filter 模块 — 数据清洗、筛选、评分
"""
import pandas as pd
import numpy as np
import pytest
from src.stock_filter import (
    load_and_clean,
    _normalize_columns,
    build_watchlist,
    calculate_score,
    calculate_score_v2,
    filter_momentum_stocks,
    filter_overnight_candidates,
    sector_strength_analysis,
)


class TestNormalizeColumns:
    """列名标准化测试"""

    def test_remaps_english_to_chinese(self):
        df = pd.DataFrame({'code': ['000001'], 'name': ['测试'], 'close': [10.0]})
        result = _normalize_columns(df)
        assert '代码' in result.columns
        assert '名称' in result.columns
        assert '最新价' in result.columns

    def test_keeps_chinese_columns(self):
        df = pd.DataFrame({'代码': ['000001'], '名称': ['测试'], '最新价': [10.0]})
        result = _normalize_columns(df)
        assert list(result.columns) == ['代码', '名称', '最新价']

    def test_handles_empty_df(self):
        df = pd.DataFrame()
        result = _normalize_columns(df)
        assert result.empty

    def test_handles_none(self):
        result = _normalize_columns(None)
        assert result is None


class TestLoadAndClean:
    """数据清洗测试"""

    def test_excludes_st_stocks(self, sample_raw_df):
        clean = load_and_clean(sample_raw_df)
        st_names = clean[clean['名称'].str.contains('ST', na=False)]
        assert len(st_names) == 0, f"ST stocks not excluded: {st_names['名称'].tolist()}"

    def test_returns_dataframe(self, sample_raw_df):
        clean = load_and_clean(sample_raw_df)
        assert isinstance(clean, pd.DataFrame)
        assert len(clean) > 0

    def test_numeric_conversion(self, sample_raw_df):
        """数值列应为 float/int"""
        clean = load_and_clean(sample_raw_df)
        assert pd.api.types.is_numeric_dtype(clean['最新价'])
        assert pd.api.types.is_numeric_dtype(clean['涨跌幅'])
        assert pd.api.types.is_numeric_dtype(clean['成交额'])

    def test_handles_empty_input(self):
        with pytest.raises(ValueError, match='为空'):
            load_and_clean(None)
        with pytest.raises(ValueError, match='为空'):
            load_and_clean(pd.DataFrame())

    def test_keeps_non_st_normal_stocks(self, sample_raw_df):
        """正常股票应该保留"""
        clean = load_and_clean(sample_raw_df)
        normal = clean[~clean['名称'].str.contains('ST', na=False)]
        assert len(normal) > 0

    def test_null_code_or_price_dropped(self):
        """缺少代码或最新价的股票应被抛弃"""
        df = pd.DataFrame({
            '代码': ['000001', None, '000003'],
            '名称': ['股A', '股B', '股C'],
            '最新价': [10.0, 20.0, None],
        })
        clean = _normalize_columns(df)
        # load_and_clean 会处理缺失值
        result = load_and_clean(df)
        # 代码和最新价都有的才保留
        assert all(result['代码'].notna())
        assert all(result['最新价'].notna())


class TestBuildWatchlist:
    """观察池筛选测试"""

    def test_filters_by_rules(self, sample_clean_df):
        wl = build_watchlist(sample_clean_df)
        # 所有入选股票应该满足 WATCHLIST_RULES
        from config import WATCHLIST_RULES
        assert all(wl['涨跌幅'] >= WATCHLIST_RULES['涨跌幅_min'])
        assert all(wl['成交额'] >= WATCHLIST_RULES['成交额_min'])
        assert all(wl['换手率'] >= WATCHLIST_RULES['换手率_min'])
        assert all(wl['振幅'] <= WATCHLIST_RULES['振幅_max'])

    def test_adds_score_column(self, sample_clean_df):
        wl = build_watchlist(sample_clean_df)
        assert 'score' in wl.columns
        assert all(0 <= s <= 100 for s in wl['score'])

    def test_sorted_by_score_desc(self, sample_clean_df):
        wl = build_watchlist(sample_clean_df)
        if len(wl) > 1:
            scores = wl['score'].values
            assert all(scores[i] >= scores[i+1] for i in range(len(scores)-1))

    def test_empty_input(self):
        result = build_watchlist(pd.DataFrame())
        assert result.empty
        result = build_watchlist(None)
        assert result is None


class TestCalculateScore:
    """V1 评分测试"""

    def test_score_in_range(self, sample_clean_df):
        scored = calculate_score(sample_clean_df)
        assert 'score' in scored.columns
        assert all(0 <= s <= 100 for s in scored['score'])

    def test_higher_rise_higher_score(self):
        """涨幅越高则评分越高"""
        df = pd.DataFrame({
            '代码': ['A', 'B'],
            '名称': ['股A', '股B'],
            '涨跌幅': [8.0, 2.0],
            '成交额': [1e9, 1e9],
            '换手率': [5.0, 5.0],
            '振幅': [5.0, 5.0],
            '最新价': [20.0, 10.0],
        })
        scored = calculate_score(df)
        assert scored.loc[0, 'score'] > scored.loc[1, 'score']

    def test_empty_input(self):
        result = calculate_score(pd.DataFrame())
        assert result.empty
        result = calculate_score(None)
        assert result is None


class TestCalculateScoreV2:
    """V2 增强评分测试"""

    def test_adds_score_v2_column(self, sample_watchlist):
        if sample_watchlist.empty:
            pytest.skip("观察池为空")
        v2 = calculate_score_v2(sample_watchlist)
        assert 'score_v2' in v2.columns

    def test_score_v2_in_range(self, sample_watchlist):
        if sample_watchlist.empty:
            pytest.skip("观察池为空")
        v2 = calculate_score_v2(sample_watchlist)
        assert all(0 <= s <= 100 for s in v2['score_v2'])

    def test_handles_missing_liangbi(self):
        """量比缺失时不应崩溃"""
        df = pd.DataFrame({
            '代码': ['000001', '000002'],
            '名称': ['A', 'B'],
            '最新价': [15.0, 20.0],
            '今开': [14.5, 19.5],
            '涨跌幅': [4.0, 3.0],
            '成交额': [1e9, 2e9],
            '换手率': [5.0, 4.0],
            '振幅': [6.0, 5.0],
            '总市值': [5e10, 8e10],
        })
        result = calculate_score_v2(df)
        assert 'score_v2' in result.columns

    def test_handles_empty_input(self):
        result = calculate_score_v2(pd.DataFrame())
        assert result.empty
        result = calculate_score_v2(None)
        assert result is None


class TestFilterMomentumStocks:
    """动量选股测试"""

    def test_adds_momentum_tag(self, sample_watchlist):
        if sample_watchlist.empty:
            pytest.skip("观察池为空")
        result = filter_momentum_stocks(sample_watchlist)
        assert 'momentum_tag' in result.columns
        assert all(t in ['强动量', '一般动量', '非动量'] for t in result['momentum_tag'])

    def test_high_rise_strong_close_tags_qiang(self):
        """涨幅>3% 且 收盘/最高>97% → 强动量"""
        df = pd.DataFrame({
            '代码': ['000001'],
            '名称': ['强动量股'],
            '涨跌幅': [5.0],
            '最新价': [20.0],
            '最高': [20.3],
        })
        result = filter_momentum_stocks(df)
        # 20.0/20.3 = 0.985 > 0.97 → 强动量
        assert result.loc[0, 'momentum_tag'] == '强动量'

    def test_low_rise_tags_non_momentum(self):
        """涨幅<=2% → 非动量"""
        df = pd.DataFrame({
            '代码': ['000001'],
            '名称': ['弱股'],
            '涨跌幅': [1.5],
            '最新价': [10.0],
            '最高': [10.1],
        })
        result = filter_momentum_stocks(df)
        assert result.loc[0, 'momentum_tag'] == '非动量'


class TestFilterOvernight:
    """一夜持股法筛选测试"""

    def test_returns_dataframe(self, sample_watchlist):
        result = filter_overnight_candidates(sample_watchlist)
        assert isinstance(result, pd.DataFrame)

    def test_adds_overnight_score(self, sample_watchlist):
        result = filter_overnight_candidates(sample_watchlist)
        if not result.empty:
            assert 'overnight_score' in result.columns

    def test_empty_input(self):
        result = filter_overnight_candidates(pd.DataFrame())
        assert result.empty if isinstance(result, pd.DataFrame) else result is None


class TestSectorAnalysis:
    """板块强度分析测试"""

    def test_returns_dataframe(self, sample_watchlist):
        result = sector_strength_analysis(sample_watchlist)
        assert isinstance(result, pd.DataFrame)

    def test_empty_input(self):
        result = sector_strength_analysis(pd.DataFrame())
        assert result.empty
