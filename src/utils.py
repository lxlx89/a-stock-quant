"""
工具模块 - 通用辅助函数
"""

import os
import datetime


def print_section(title):
    """打印分节标题"""
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('=' * 50)


def save_log(message, log_dir=None, log_file='run.log'):
    """
    保存运行日志

    参数：
        message: 日志内容
        log_dir: 日志目录，默认使用 config.LOG_DIR
        log_file: 日志文件名
    """
    if log_dir is None:
        from config import LOG_DIR
        log_dir = LOG_DIR

    os.makedirs(log_dir, exist_ok=True)

    filepath = os.path.join(log_dir, log_file)
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")


def format_amount(amount):
    """
    格式化成交额显示（单位转换）
    将元转换为亿元/万元

    参数：
        amount: 成交额（元）

    返回：
        str: 格式化后的字符串
    """
    if amount >= 1e8:
        return f"{amount / 1e8:.2f}亿"
    elif amount >= 1e4:
        return f"{amount / 1e4:.2f}万"
    else:
        return f"{amount:.0f}元"


def is_trading_time():
    """
    判断当前是否为交易时间
    预留自动定时运行使用

    返回：
        bool: True=交易时间，False=非交易时间
    """
    now = datetime.datetime.now()
    weekday = now.weekday()  # 0=周一，5=周六，6=周日

    # 周末不交易
    if weekday >= 5:
        return False

    # 工作日 9:30 - 11:30，13:00 - 15:00
    current_time = now.time()
    morning_start = datetime.time(9, 30)
    morning_end = datetime.time(11, 30)
    afternoon_start = datetime.time(13, 0)
    afternoon_end = datetime.time(15, 0)

    if morning_start <= current_time <= morning_end:
        return True
    if afternoon_start <= current_time <= afternoon_end:
        return True

    return False


def get_trading_date():
    """
    获取当前交易日期（预留）
    格式 YYYYMMDD
    """
    now = datetime.datetime.now()
    return now.strftime('%Y%m%d')


# ============================================================
# 预留扩展接口（后续版本使用）
# ============================================================

def parse_stock_code(code_str):
    """
    解析股票代码（预留）
    - 判断是沪市还是深市
    - 判断板块（主板/创业板/科创板）

    返回：
        dict: 包含 code, market, board 等信息
    """
    code = str(code_str).strip()

    if code.startswith('6'):
        market = '上交所'
        board = '主板' if not code.startswith('688') else '科创板'
    elif code.startswith('000') or code.startswith('001'):
        market = '深交所'
        board = '主板'
    elif code.startswith('300'):
        market = '深交所'
        board = '创业板'
    elif code.startswith('688'):
        market = '上交所'
        board = '科创板'
    else:
        market = '未知'
        board = '未知'

    return {'code': code, 'market': market, 'board': board}