"""
数据抓取模块
负责从 AKShare 获取 A 股实时行情数据

实时行情使用 Eastmoney（东方财富）接口
历史数据使用 BaoStock（预留，回测用）
"""

import os
import time
import warnings
import ssl
import requests
from config import DATA_FETCHER_FUNC, PROXY_BYPASS_DOMAINS

warnings.filterwarnings('ignore')
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 解决东方财富等财经网站的弱 SSL 证书问题
# Python 3.10+ 对弱密钥证书的验证更严格
_original_request = requests.Session.request

def _patched_request(self, method, url, *args, **kwargs):
    """为财经类域名降低 SSL 验证级别"""
    verify = kwargs.get('verify', True)
    if verify and isinstance(url, str):
        for domain in PROXY_BYPASS_DOMAINS:
            if domain in url:
                # 为这些域名创建允许弱证书的 SSL 上下文
                kwargs['verify'] = False
                break
    return _original_request(self, method, url, *args, **kwargs)

requests.Session.request = _patched_request


def clear_proxy_env():
    """
    清除代理环境变量
    让 requests 不走系统代理，直接连接
    """
    proxy_keys = [
        'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
        'NO_PROXY', 'no_proxy', 'ALL_PROXY', 'all_proxy'
    ]
    saved = {}
    for key in proxy_keys:
        val = os.environ.pop(key, None)
        if val is not None:
            saved[key] = val
    return saved


def restore_proxy_env(saved):
    """恢复代理环境变量"""
    for key, val in saved.items():
        os.environ[key] = val


def fetch_realtime_quotes():
    """
    从 AKShare 获取 A 股实时行情（全市场）

    返回：
        pandas.DataFrame: 包含全市场股票实时行情
        字段包括：代码、名称、最新价、涨跌幅、涨跌额、成交量、成交额等

    注意：
        - 不接券商交易接口，仅数据展示
        - AKShare 数据源可能有延迟，请知晓
        - 网络问题优先检查代理软件白名单配置
    """
    try:
        import akshare as ak

        print("  正在从 AKShare 抓取实时行情数据...")
        print("  （接口: stock_zh_a_spot_em，数据来自东方财富）")
        print("  （如遇连接失败，请检查代理软件是否将 eastmoney.com 加入直连）")

        # 记录开始时间
        start_time = time.time()

        # 清除代理环境变量，避免 requests 走代理
        saved_env = clear_proxy_env()

        try:
            # 先尝试 stock_zh_a_spot_em（东方财富，数据更完整）
            # 如果失败，尝试 stock_zh_a_spot（Sina，备用）
            # 每次尝试都有指数退避重试
            try:
                df = _retry_with_backoff(
                    lambda: ak.stock_zh_a_spot_em(),
                    max_retries=2,
                    base_delay=1
                )
            except Exception as primary_err:
                print(f"  [WARN] stock_zh_a_spot_em 失败，尝试备用接口: {primary_err}")
                df = _retry_with_backoff(
                    lambda: ak.stock_zh_a_spot(),
                    max_retries=1,
                    base_delay=1
                )
        finally:
            # 恢复代理环境变量
            restore_proxy_env(saved_env)

        elapsed = time.time() - start_time
        print(f"  抓取完成，耗时 {elapsed:.1f} 秒")

        return df

    except ImportError:
        raise RuntimeError(
            "未安装 akshare 库，请运行: pip install akshare"
        )
    except Exception as e:
        error_msg = str(e)
        if 'ProxyError' in error_msg or 'Unable to connect' in error_msg:
            raise RuntimeError(
                f"AKShare 数据抓取失败（代理问题）: {e}\n\n"
                "请在代理软件中将以下域名加入直连/代理例外:\n"
                "  eastmoney.com\n"
                "  push2.eastmoney.com\n"
                "  push2his.eastmoney.com\n"
                "  quote.eastmoney.com\n"
                "  data.eastmoney.com\n"
                "  dfcfw.com\n\n"
                "Clash 配置示例:\n"
                "  DOMAIN-SUFFIX,eastmoney.com,DIRECT\n"
                "  DOMAIN-SUFFIX,dfcfw.com,DIRECT"
            )
        else:
            raise RuntimeError(f"AKShare 数据抓取失败: {e}")


def fetch_history_kline(code, period='daily', start_date=None, end_date=None):
    """
    获取单只股票历史 K 线数据（预留接口，供后续版本使用）

    参数：
        code: 股票代码，如 '000001'
        period: K 线周期，'daily' / 'weekly' / 'monthly'
        start_date: 开始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'

    返回：
        pandas.DataFrame: K 线数据
    """
    try:
        import akshare as ak

        if start_date and end_date:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust='qfq'
            )
        else:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                adjust='qfq'
            )

        return df

    except Exception as e:
        print(f"  [WARN] 获取 {code} 历史数据失败: {e}")
        return None


# ============================================================
# 历史数据模块（使用 BaoStock，仅用于回测/历史分析）
# 注意：盘中实时行情不要用 BaoStock
# ============================================================

def fetch_baostock_history(code, start_date, end_date, fields='code,date,open,high,low,close,volume'):
    """
    使用 BaoStock 获取历史K线数据（回测用）

    BaoStock 优势：本地数据库，无需网络请求，查询速度快
    用途：历史回测、策略验证、板块分析

    参数：
        code: 股票代码，如 'sz000001'（带交易所前缀）
        start_date: 开始日期，格式 'YYYYMMDD'
        end_date: 结束日期，格式 'YYYYMMDD'
        fields: 返回字段，默认为标准 OHLCV 字段

    返回：
        pandas.DataFrame: 历史K线数据
    """
    try:
        import baostock as bs

        # 登录 BaoStock
        lg = bs.login()
        if lg.error_code != '0':
            raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")

        try:
            # 设置代码格式（baostock 需要 sz/sh 前缀）
            if not code.startswith(('sz', 'sh')):
                if code.startswith('6'):
                    code = 'sh.' + code
                else:
                    code = 'sz.' + code

            # 获取日K线数据
            rs = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=start_date,
                end_date=end_date,
                frequency='d',
                adjust='qfq'
            )

            if rs.error_code != '0':
                raise RuntimeError(f"BaoStock 查询失败: {rs.error_msg}")

            # 转换为 DataFrame
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            df = None
            if data_list:
                import pandas as pd
                df = pd.DataFrame(data_list, columns=rs.fields)

            return df

        finally:
            bs.logout()

    except ImportError:
        raise RuntimeError(
            "未安装 baostock 库，请运行: pip install baostock"
        )
    except Exception as e:
        print(f"  [WARN] BaoStock 获取 {code} 历史数据失败: {e}")
        return None


# ============================================================
# 网络重试工具
# ============================================================

def _retry_with_backoff(func, max_retries=3, base_delay=2):
    """
    带指数退避的重试执行

    参数：
        func: 要执行的函数（无参数）
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒），每次重试延迟翻倍
    """
    import random
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"  [RETRY] 第 {attempt + 1} 次失败，{delay:.1f}秒后重试... ({e})")
                time.sleep(delay)
            else:
                raise


# ============================================================
# 扩展接口实现
# ============================================================

def fetch_sector_data():
    """
    获取 A 股行业板块数据

    返回：
        pandas.DataFrame: 包含板块名称、涨跌幅、领涨股等字段
    """
    try:
        import akshare as ak

        print("  正在获取行业板块数据...")

        saved_env = clear_proxy_env()
        try:
            df = _retry_with_backoff(
                lambda: ak.stock_board_industry_name_em(),
                max_retries=2
            )
        finally:
            restore_proxy_env(saved_env)

        print(f"  [OK] 获取到 {len(df)} 个行业板块数据")
        return df

    except ImportError:
        raise RuntimeError("未安装 akshare 库，请运行: pip install akshare")
    except Exception as e:
        print(f"  [WARN] 板块数据获取失败: {e}")
        return None


def fetch_money_flow(code):
    """
    获取单只股票资金流向数据

    参数：
        code: 股票代码，如 '000001'

    返回：
        pandas.DataFrame: 包含主力净流入、超大单净流入、大单净流入等字段
    """
    try:
        import akshare as ak

        saved_env = clear_proxy_env()
        try:
            # 个股资金流向（东方财富）
            df = _retry_with_backoff(
                lambda: ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith('6') else "sz"),
                max_retries=2
            )
        finally:
            restore_proxy_env(saved_env)

        if df is not None and not df.empty:
            # 只返回最近一条记录
            return df.head(1)
        return df

    except ImportError:
        raise RuntimeError("未安装 akshare 库，请运行: pip install akshare")
    except Exception as e:
        print(f"  [WARN] 获取 {code} 资金流向失败: {e}")
        return None


def fetch_realtime_by_codes(codes):
    """
    根据指定股票代码列表获取实时行情
    先拉全市场数据再按代码过滤，保证数据一致性

    参数：
        codes: 股票代码列表，如 ['000001', '600519']

    返回：
        pandas.DataFrame: 指定股票的实时行情
    """
    if not codes:
        print("  [WARN] codes 为空，返回空 DataFrame")
        import pandas as pd
        return pd.DataFrame()

    try:
        import akshare as ak

        print(f"  正在获取 {len(codes)} 只指定股票的实时行情...")

        saved_env = clear_proxy_env()
        try:
            # 拉全市场数据然后过滤，比逐只查询更快更稳定
            df_all = _retry_with_backoff(
                lambda: ak.stock_zh_a_spot_em(),
                max_retries=2
            )
        finally:
            restore_proxy_env(saved_env)

        if df_all is None or df_all.empty:
            return None

        # 标准化字段名（复用 stock_filter 的逻辑）
        from src.stock_filter import _normalize_columns
        df_all = _normalize_columns(df_all)

        # 按代码过滤
        codes_set = set(str(c).strip() for c in codes)
        df_filtered = df_all[df_all['代码'].astype(str).isin(codes_set)].copy()

        print(f"  [OK] 匹配到 {len(df_filtered)}/{len(codes)} 只股票")
        return df_filtered

    except ImportError:
        raise RuntimeError("未安装 akshare 库，请运行: pip install akshare")
    except Exception as e:
        print(f"  [WARN] 指定代码实时行情获取失败: {e}")
        return None