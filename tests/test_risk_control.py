"""
测试 risk_control 模块 — 风险评估、涨停检测、量能异常
"""
import pandas as pd
import numpy as np
import pytest
from src.risk_control import (
    assess_risks,
    get_risk_report,
    check_limit_up_risk,
    check_volume_anomaly,
)


class TestAssessRisks:
    """风险评估测试"""

    @pytest.fixture
    def risk_test_df(self):
        """包含各种风险情况的测试数据"""
        data = {
            '代码': ['000001', '300001', '688001', '000002', '000003', '000004'],
            '名称': ['主低风险', '创高风险', '科高风险', '中风险', '高振幅', '低流动性'],
            '最新价': [15.0, 35.0, 100.0, 20.0, 10.0, 5.0],
             '涨跌幅': [3.0, 13.0, 14.0, 9.0, 4.0, 2.0],
             '成交额': [5e8, 3e9, 2e9, 8e8, 3e8, 2e7],  # 低流动性 2000万 < 5000万
             '换手率': [4.0, 15.0, 18.0, 8.0, 25.0, 1.5],
             '振幅': [5.0, 10.0, 11.0, 9.0, 15.0, 6.0],
        }
        return pd.DataFrame(data)

    def test_adds_risk_columns(self, risk_test_df):
        result = assess_risks(risk_test_df)
        assert 'risk_level' in result.columns
        assert 'risk_detail' in result.columns

    def test_low_risk_normal_stock(self, risk_test_df):
        """普通主板 3% 涨幅 → 低风险"""
        result = assess_risks(risk_test_df)
        row = result[result['代码'] == '000001'].iloc[0]
        assert row['risk_level'] == '低风险'
        assert row['risk_detail'] == '无明显风险'

    def test_high_risk_gem_high_rise(self, risk_test_df):
        """创业板 >12% 涨幅 → 高风险"""
        result = assess_risks(risk_test_df)
        row = result[result['代码'] == '300001'].iloc[0]
        assert row['risk_level'] == '高风险'

    def test_high_risk_amplitude(self, risk_test_df):
        """振幅 >12% → 高风险（000003 振幅 15%）"""
        result = assess_risks(risk_test_df)
        row = result[result['代码'] == '000003'].iloc[0]
        assert row['risk_level'] == '高风险'

    def test_high_risk_turnover(self, risk_test_df):
        """换手率 >20% → 高风险（000003 换手 25%）"""
        result = assess_risks(risk_test_df)
        row = result[result['代码'] == '000003'].iloc[0]
        # 该股票有高换手(25%)和高振幅(15%) → 高风险
        assert row['risk_level'] == '高风险'

    def test_medium_risk_high_rise_main(self, risk_test_df):
        """主板 >8% 涨幅 → 中风险（000002 涨幅 9%）"""
        result = assess_risks(risk_test_df)
        row = result[result['代码'] == '000002'].iloc[0]
        assert row['risk_level'] == '中风险'

    def test_empty_input(self):
        result = assess_risks(pd.DataFrame())
        assert result.empty
        result = assess_risks(None)
        assert result is None

    def test_all_stocks_have_risk_level(self, risk_test_df):
        result = assess_risks(risk_test_df)
        assert all(result['risk_level'].notna())
        assert set(result['risk_level'].unique()).issubset({'低风险', '中风险', '高风险'})


class TestRiskReport:
    """风险报告测试"""

    def test_only_medium_and_high(self, sample_watchlist):
        # 需要先评估风险再生成报告
        from src.risk_control import assess_risks
        assessed = assess_risks(sample_watchlist)
        report = get_risk_report(assessed)
        if not report.empty:
            assert all(report['risk_level'].isin(['中风险', '高风险']))

    def test_empty_input(self):
        result = get_risk_report(pd.DataFrame())
        assert result.empty


class TestCheckLimitUpRisk:
    """涨停风险检测测试"""

    def test_near_limit_main_board(self):
        """主板 9.8% → 接近涨停高风险"""
        df = pd.DataFrame({
            '代码': ['000001'],
            '涨跌幅': [9.8],
        })
        result = check_limit_up_risk(df)
        assert 'limit_up_risk' in result.columns
        # 9.8 >= 10*0.95 → 接近涨停
        assert '涨停' in result.loc[0, 'limit_up_risk']

    def test_normal_stock(self):
        """3% 涨幅 → 正常"""
        df = pd.DataFrame({
            '代码': ['000001'],
            '涨跌幅': [3.0],
        })
        result = check_limit_up_risk(df)
        assert result.loc[0, 'limit_up_risk'] == '正常'

    def test_gem_at_19(self):
        """创业板 19% 接近 20% 涨停"""
        df = pd.DataFrame({
            '代码': ['300001'],
            '涨跌幅': [19.0],
        })
        result = check_limit_up_risk(df)
        assert '涨停' in result.loc[0, 'limit_up_risk']

    def test_empty_input(self):
        result = check_limit_up_risk(pd.DataFrame())
        assert result.empty
        result = check_limit_up_risk(None)
        assert result is None


class TestCheckVolumeAnomaly:
    """量能异常检测测试"""

    def test_adds_anomaly_column(self, sample_watchlist):
        result = check_volume_anomaly(sample_watchlist)
        if not result.empty:
            assert 'volume_anomaly' in result.columns

    def test_normal_volume(self):
        """成交量在正常范围 → 正常"""
        df = pd.DataFrame({
            '代码': ['000001', '000002', '000003', '000004', '000005'],
            '涨跌幅': [3.0, 2.5, 4.0, 3.5, 2.0],
            '成交额': [5e8, 4e8, 6e8, 3e8, 7e8],
            '换手率': [4.0, 3.0, 5.0, 2.5, 6.0],
        })
        result = check_volume_anomaly(df)
        assert all(t == '正常' for t in result['volume_anomaly'])

    def test_small_input(self):
        """小于 5 只股票时不报错"""
        df = pd.DataFrame({
            '代码': ['000001'],
            '涨跌幅': [3.0],
            '成交额': [5e8],
        })
        result = check_volume_anomaly(df)
        assert isinstance(result, pd.DataFrame)

    def test_empty_input(self):
        result = check_volume_anomaly(pd.DataFrame())
        assert result.empty
