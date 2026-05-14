"""
网络诊断脚本 - 检测到东方财富API的连接状态
用于排查代理环境下数据接口无法连接的问题

使用方法：
    python src/network_diag.py
"""

import os
import sys


def clear_proxy_env():
    """清除所有代理相关环境变量"""
    proxy_keys = [
        'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
        'NO_PROXY', 'no_proxy',
        'HTTP_PROXY_USER', 'HTTPS_PROXY_USER',
        'ALL_PROXY', 'all_proxy'
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


def test_connection(url, description):
    """测试单个 URL 的连接"""
    import requests

    session = requests.Session()
    session.trust_env = False  # 不使用系统代理

    try:
        r = session.get(url, timeout=15)
        print(f"  [OK] {description}")
        print(f"       状态码: {r.status_code}, 响应大小: {len(r.text)} bytes")
        return True
    except Exception as e:
        print(f"  [FAIL] {description}")
        print(f"        错误: {e}")
        return False


def run_diagnostic():
    """运行网络诊断"""
    print("=" * 60)
    print("  网络连接诊断")
    print("=" * 60)

    # 保存原有代理设置
    saved = clear_proxy_env()

    print("\n[1] 清除代理环境变量")
    if saved:
        print(f"    已清除: {list(saved.keys())}")
    else:
        print("    无代理环境变量需要清除")

    print("\n[2] 测试东方财富 API 域名")
    print("-" * 50)

    test_urls = [
        ("https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1&fltt=2&invt=2&fid=f12&fs=m%3A0+t%3A6&fields=f12,f14&_=1",
         "push2.eastmoney.com (实时行情)"),
        ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58&klt=101&fqt=1&beg=20250501&end=20250513&smplmt=10&lmt=10",
         "push2his.eastmoney.com (历史K线)"),
        ("https://quote.eastmoney.com/600519.html",
         "quote.eastmoney.com (行情报价)"),
        ("https://data.eastmoney.com",
         "data.eastmoney.com (数据中心)"),
    ]

    results = {}
    for url, desc in test_urls:
        results[desc] = test_connection(url, desc)
        print()

    print("-" * 50)
    print("\n[3] 测试参考网站（验证网络是否正常）")
    print("-" * 50)
    test_connection("https://www.baidu.com", "百度（参考网络）")
    print()

    print("=" * 60)
    print("  诊断结果汇总")
    print("=" * 60)

    eastmoney_ok = any(results.values())
    if eastmoney_ok:
        print("  东方财富: 部分域名可访问，接口应可正常工作")
    else:
        print("  东方财富: 所有域名均无法访问")
        print("  可能原因:")
        print("    1. 代理软件未将 eastmoney.com 加入直连")
        print("    2. 防火墙或安全软件拦截")
        print("    3. 网络运营商限制")
        print("  解决方法:")
        print("    - 在代理软件中将以下域名加入直连/代理例外:")
        print("      eastmoney.com, push2.eastmoney.com, push2his.eastmoney.com")
        print("      quote.eastmoney.com, data.eastmoney.com, dfcfw.com")

    # 恢复代理环境
    restore_proxy_env(saved)

    return eastmoney_ok


if __name__ == '__main__':
    ok = run_diagnostic()
    sys.exit(0 if ok else 1)