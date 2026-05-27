"""
迅股股 v7.0 — 刘迅的量化选股系统
三大策略面板 | 午间分析 | 多策略图像识别
"""
import sys, os, json, time, base64, re
sys.path.insert(0, '/opt/quant')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from datetime import datetime

app = FastAPI(title="迅股股", version="7.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CACHE = {}

import math
def _safe_json(obj):
    """递归清理NaN/Infinity为JSON兼容值"""
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    return obj


def _run_pipeline():
    from src import fetch_realtime_quotes
    from src.stock_filter import load_and_clean, build_watchlist, calculate_score_v2, filter_momentum_stocks
    from src.risk_control import assess_risks
    df = fetch_realtime_quotes()
    df = load_and_clean(df)
    wl = build_watchlist(df)
    wl = calculate_score_v2(wl)
    wl = assess_risks(wl)
    wl = filter_momentum_stocks(wl)
    return wl, df


def _get_positions():
    path = '/opt/quant/data/trades.json'
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _analyze_positions(positions, quotes_df):
    from src.strategy import generate_sell_signals
    signals = generate_sell_signals(positions, quotes_df)
    quote_map = {}
    for _, row in quotes_df.iterrows():
        code = str(row.get('代码', '')).replace('sz', '').replace('sh', '').replace('bj', '')
        quote_map[code] = row

    results = []
    for p in positions:
        if p.get('status') != 'open': continue
        code = p['code']
        row = quote_map.get(code)
        now_price = float(row.get('最新价', p['price'])) if row is not None else p['price']
        pnl_pct = (now_price - p['price']) / p['price'] * 100
        chg_today = float(row.get('涨跌幅', 0)) if row is not None else 0
        turnover = float(row.get('换手率', 0)) if row is not None else 0
        amount = float(row.get('成交额', 0)) / 1e8 if row is not None else 0
        signal = next((s for s in signals if s['code'] == code), None)

        if signal and signal['urgency'] in ('critical', 'urgent'):
            action, color = '卖出', 'sell'
            detail = signal['reason']
        elif pnl_pct < -5:
            action, color = '止损', 'sell'
            detail = f'亏损{pnl_pct:.1f}%，建议止损卖出'
        elif pnl_pct > 7:
            action, color = '止盈', 'sell'
            detail = f'盈利{pnl_pct:.1f}%，分批止盈锁利'
        elif pnl_pct > 3:
            action, color = '持有', 'hold'
            detail = f'盈利{pnl_pct:+.1f}%，趋势向好继续持有'
        elif pnl_pct < -2:
            action, color = '警戒', 'warn'
            detail = f'亏损{pnl_pct:.1f}%，接近止损线-5%，密切关注'
        elif abs(pnl_pct) < 0.5 and abs(chg_today) < 0.3:
            action, color = '观望', 'warn'
            detail = '横盘无方向，暂时持有观望'
        else:
            action, color = '持有', 'hold'
            detail = f'盈亏{pnl_pct:+.1f}%，暂无明确信号'

        results.append({
            'code': code, 'name': p.get('name', ''), 'shares': p['shares'],
            'cost': round(p['price'], 2), 'now': round(now_price, 2),
            'pnl_pct': round(pnl_pct, 2), 'today_chg': round(chg_today, 2),
            'turnover': round(turnover, 1), 'amount': round(amount, 1),
            'action': action, 'action_color': color, 'action_detail': detail,
        })
    order = {'sell': 0, 'warn': 1, 'hold': 2}
    results.sort(key=lambda x: order.get(x['action_color'], 9))
    return results


def _midday_analysis(wl, df, pos_analysis):
    """午间分析：上午回顾 + 下午展望"""
    from src.stock_filter import sector_strength_analysis
    sectors = sector_strength_analysis(wl)

    # 上午涨幅最强的板块
    hot = []
    if len(sectors) > 0:
        for _, r in sectors.head(5).iterrows():
            hot.append(f"{str(r.iloc[0])}(+{r.get('涨跌幅',0):.1f}%)")

    # 持仓状况总结
    sell_count = sum(1 for p in pos_analysis if p['action_color'] == 'sell')
    hold_count = sum(1 for p in pos_analysis if p['action_color'] == 'hold')
    total_pnl = sum(p['pnl_pct'] * float(p.get('shares', 0)) * float(p.get('cost', 0)) / sum(
        float(pp.get('shares', 0)) * float(pp.get('cost', 0)) for pp in pos_analysis
    ) for p in pos_analysis) if pos_analysis else 0

    summary = f"上午强势板块：{'、'.join(hot[:3]) or '无明显热点'}。"
    summary += f"持仓：{len(pos_analysis)}只，{sell_count}只需卖出，{hold_count}只持有。"
    if total_pnl > 0:
        summary += f"整体盈利{total_pnl:+.1f}%。"
    elif total_pnl < -1:
        summary += f"整体亏损{total_pnl:.1f}%，下午注意风险。"
    else:
        summary += "整体持平。"

    # 下午建议
    if sell_count >= 2:
        advice = "下午建议优先处理卖出信号，减仓后观望。"
    elif sell_count == 1:
        advice = "下午关注1只卖出信号，其余持有。可轻仓寻找尾盘一夜持股机会。"
    else:
        advice = "持仓状况良好。下午可关注尾盘一夜持股机会，14:30后筛选。"

    return {
        'summary': summary,
        'advice': advice,
        'hot_sectors': hot,
        'sell_count': sell_count,
        'total_pnl': round(total_pnl, 2),
        'afternoon_suggestion': advice,
    }


# ============================================================
# API
# ============================================================

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "7.0", "time": datetime.now().strftime("%H:%M:%S")}


@app.post("/api/morning")
def morning_scan():
    """早盘扫描：强势股推荐"""
    global CACHE
    try:
        from src.strategy import generate_morning_recommendation
        from src.stock_filter import sector_strength_analysis

        wl, df = _run_pipeline()
        recs = generate_morning_recommendation(wl)
        sectors = sector_strength_analysis(wl)
        positions = _get_positions()
        open_pos = [p for p in positions if p.get('status') == 'open']
        pos_analysis = _analyze_positions(open_pos, df)

        hot_sectors = []
        if len(sectors) > 0:
            for _, row in sectors.head(5).iterrows():
                hot_sectors.append({
                    'name': str(row.iloc[0]), 'count': int(row.get('入选数量', 0)),
                    'avg_chg': round(float(row.get('涨跌幅', 0)), 2),
                })

        CACHE['morning'] = {
            'time': datetime.now().strftime('%H:%M:%S'), 'type': 'morning',
            'title': '早盘强势股推荐', 'desc': '集合竞价后精选，排除涨停板',
            'recommendations': recs, 'positions': pos_analysis, 'sectors': hot_sectors,
            'market_strong': len(wl), 'market_total': len(df),
        }
        return {"status": "ok", **_safe_json(CACHE['morning'])}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e)}


@app.post("/api/midday")
def midday_scan():
    """午间分析：上午复盘 + 下午策略"""
    global CACHE
    try:
        wl, df = _run_pipeline()
        positions = _get_positions()
        open_pos = [p for p in positions if p.get('status') == 'open']
        pos_analysis = _analyze_positions(open_pos, df)
        midday = _midday_analysis(wl, df, pos_analysis)

        # 午间也提供备选标的（涨幅适中、量能健康的）
        from src.stock_filter import sector_strength_analysis
        sectors = sector_strength_analysis(wl)
        hot_sectors = []
        if len(sectors) > 0:
            for _, row in sectors.head(5).iterrows():
                hot_sectors.append({
                    'name': str(row.iloc[0]), 'count': int(row.get('入选数量', 0)),
                    'avg_chg': round(float(row.get('涨跌幅', 0)), 2),
                })

        CACHE['midday'] = {
            'time': datetime.now().strftime('%H:%M:%S'), 'type': 'midday',
            'title': '午间持仓分析', 'desc': '上午复盘 · 下午策略',
            'summary': midday['summary'], 'advice': midday['advice'],
            'hot_sectors': hot_sectors,
            'positions': pos_analysis,
            'sell_count': midday['sell_count'], 'total_pnl': midday['total_pnl'],
        }
        return {"status": "ok", **CACHE['midday']}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e)}


@app.post("/api/overnight")
def overnight_scan():
    """尾盘扫描：一夜持股法"""
    global CACHE
    try:
        from src.strategy import generate_overnight_recommendation
        from src.stock_filter import sector_strength_analysis

        wl, df = _run_pipeline()
        recs = generate_overnight_recommendation(wl)
        sectors = sector_strength_analysis(wl)
        positions = _get_positions()
        open_pos = [p for p in positions if p.get('status') == 'open']
        pos_analysis = _analyze_positions(open_pos, df)

        hot_sectors = []
        if len(sectors) > 0:
            for _, row in sectors.head(5).iterrows():
                hot_sectors.append({
                    'name': str(row.iloc[0]), 'count': int(row.get('入选数量', 0)),
                    'avg_chg': round(float(row.get('涨跌幅', 0)), 2),
                })

        CACHE['overnight'] = {
            'time': datetime.now().strftime('%H:%M:%S'), 'type': 'overnight',
            'title': '一夜持股法 · 尾盘精选', 'desc': '14:30启动 · 五重筛选 · 明早卖出',
            'recommendations': recs, 'positions': pos_analysis, 'sectors': hot_sectors,
            'market_strong': len(wl), 'market_total': len(df),
        }
        return _safe_json({"status": "ok", **CACHE['overnight']})
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e)}


@app.get("/api/result/{mode}")
def get_result(mode: str = 'morning'):
    if mode in CACHE and CACHE[mode]:
        return {"status": "ok", **CACHE[mode]}
    return {"status": "not_run"}


@app.post("/api/positions/update")
async def update_positions(data: dict):
    """手动更新持仓（JSON格式）"""
    try:
        positions = data.get('positions', [])
        if not positions:
            return {"status": "error", "message": "请提供positions数组"}
        path = '/opt/quant/data/trades.json'
        trades = []
        for i, p in enumerate(positions):
            trades.append({
                'id': i + 1, 'code': str(p['code']), 'name': str(p.get('name', p['code'])),
                'direction': 'buy', 'price': float(p['cost']), 'shares': int(p['shares']),
                'cost': round(float(p['cost']) * int(p['shares']), 2),
                'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'reason': '手动更新', 'status': 'open',
            })
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)
        return {"status": "ok", "count": len(trades)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/upload-positions")
async def upload_positions(file: UploadFile = File(...)):
    """多策略图像识别"""
    try:
        contents = await file.read()
        img_b64 = base64.b64encode(contents).decode()

        # 策略1: 千问 VL（最优先）
        parsed, method = _parse_qwen(img_b64)

        # 策略2: Tesseract 原始
        if not parsed:
            parsed, method = _parse_ocr(contents, preprocess='original')

        # 策略3: Tesseract 增强对比度
        if not parsed:
            parsed, method = _parse_ocr(contents, preprocess='enhanced')

        # 策略4: 宽松正则匹配
        if not parsed:
            parsed, method = _parse_ocr_fuzzy(contents)

        if parsed and len(parsed) > 0:
            # === 数据校验：过滤明显错误 ===
            validated = []
            for p in parsed:
                code = str(p.get('code', ''))
                cost = float(p.get('cost', 0))
                shares = int(p.get('shares', 0))
                # 代码必须是6位数字且以00/30/60/68开头
                if not re.match(r'^(00|30|60|68)\d{4}$', code):
                    continue
                # 成本价合理范围：0.5-5000元
                if cost < 0.5 or cost > 5000:
                    continue
                # 股数合理范围：100-10000000
                if shares < 100 or shares > 10000000:
                    continue
                validated.append(p)

            if not validated:
                return {
                    "status": "error",
                    "message": f"识别到{len(parsed)}条但全部未通过校验。请确认截图清晰，或手动编辑持仓",
                    "raw": parsed, "method": method,
                }

            path = '/opt/quant/data/trades.json'
            trades = []
            for i, p in enumerate(validated):
                trades.append({
                    'id': i + 1, 'code': p['code'], 'name': p.get('name', p['code']),
                    'direction': 'buy', 'price': p['cost'], 'shares': p['shares'],
                    'cost': round(p['cost'] * p['shares'], 2),
                    'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'reason': f'截图导入({method})', 'status': 'open',
                })
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(trades, f, ensure_ascii=False, indent=2)

            _, df = _run_pipeline()
            pos_analysis = _analyze_positions(trades, df)
            return {
                "status": "ok", "positions": pos_analysis, "count": len(validated),
                "filtered": len(parsed) - len(validated),
                "method": method, "raw": validated,
            }
        return {
            "status": "error",
            "message": "4种识别策略均失败。请确认截图清晰",
            "methods_tried": ["qwen-vl", "ocr-original", "ocr-enhanced", "ocr-fuzzy"]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================
# 识别策略
# ============================================================

def _parse_qwen(img_b64):
    """策略1：千问VL视觉识别（增强prompt）"""
    try:
        from config import QWEN_API_KEY, QWEN_API_URL, QWEN_MODEL
        if 'sk-your' in QWEN_API_KEY:
            return None, 'qwen-skip'
        import urllib.request

        prompt = (
            "这张图片是一个股票持仓界面截图。"
            "请仔细观察图片中的每一行持仓数据，提取："
            "1. 股票代码（6位数字，如600330、002342、301308、300394）"
            "2. 股票名称（中文，如天通股份、巨力索具、江波龙、天孚通信）"
            "3. 持仓股数（整数）"
            "4. 成本价（元，可能是小数）"
            "注意：成本价在\"成本\"列下，不是\"现价\"列。"
            "请严格按照图片中的数字提取，不要猜测。"
            "返回JSON数组：[{\"code\":\"600330\",\"name\":\"天通股份\",\"shares\":6000,\"cost\":34.38}]"
            "只返回JSON，不要其他内容。"
        )

        payload = json.dumps({
            "model": QWEN_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 800, "temperature": 0
        })
        req = urllib.request.Request(
            f"{QWEN_API_URL}/chat/completions", data=payload.encode(),
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {QWEN_API_KEY}'}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = json.loads(resp.read().decode())['choices'][0]['message']['content']
            m = re.search(r'\[[\s\S]*\]', text)
            if m:
                return json.loads(m.group()), 'qwen-vl'
        return None, 'qwen-parse-fail'
    except Exception as e:
        print(f"Qwen: {e}")
        return None, f'qwen-error-{str(e)[:30]}'


def _parse_ocr(img_bytes, preprocess='original'):
    """策略2/3：Tesseract OCR（原始/增强）"""
    try:
        from PIL import Image, ImageEnhance, ImageFilter
        import pytesseract, io
        img = Image.open(io.BytesIO(img_bytes))

        if preprocess == 'enhanced':
            # 增强对比度 + 锐化
            img = img.convert('L')  # 灰度
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = ImageEnhance.Sharpness(img).enhance(1.5)
            img = img.filter(ImageFilter.SHARPEN)

        text = pytesseract.image_to_string(img, lang='chi_sim+eng')
        return _extract_positions_from_text(text), f'ocr-{preprocess}'
    except Exception as e:
        return None, f'ocr-error-{str(e)[:20]}'


def _parse_ocr_fuzzy(img_bytes):
    """策略4：宽松OCR + 模糊匹配"""
    try:
        from PIL import Image
        import pytesseract, io
        img = Image.open(io.BytesIO(img_bytes))

        # 尝试多个PSM模式
        configs = ['--psm 6', '--psm 4', '--psm 3']
        all_text = ''
        for cfg in configs:
            try:
                all_text += pytesseract.image_to_string(img, lang='chi_sim+eng', config=cfg) + '\n'
            except:
                pass

        return _extract_positions_from_text(all_text), 'ocr-fuzzy'
    except Exception as e:
        return None, f'ocr-fuzzy-error-{str(e)[:20]}'


def _extract_positions_from_text(text):
    """从OCR文本中提取持仓信息"""
    positions = []
    seen_codes = set()

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 找6位数字代码
        for code_match in re.finditer(r'(\d{6})', line):
            code = code_match.group(1)
            if code in seen_codes:
                continue
            if not (code.startswith(('00', '30', '60', '68'))):
                continue

            # 提取数字
            nums = re.findall(r'(\d+\.?\d*)', line)
            nums = [float(n) for n in nums if abs(float(n) - int(code)) > 1]

            shares, cost = None, None
            # 找股数（整数，100-10000000）
            for n in nums:
                if n == int(n) and 100 <= n <= 10000000:
                    if shares is None or (n > 1000 and n < 1000000):
                        shares = int(n)
            # 找成本价（小数或小整数，0.5-5000）
            for n in nums:
                if 0.5 <= n <= 5000:
                    if cost is None:
                        cost = n
                    elif not (cost == int(cost) and n != int(n)):
                        # 优先带小数的
                        if n != int(n) and cost == int(cost):
                            cost = n

            if shares and cost:
                positions.append({'code': code, 'name': code, 'shares': shares, 'cost': round(cost, 2)})
                seen_codes.add(code)
                break  # 每行最多匹配一个代码

    return positions if positions else None


# ============================================================
# 三大扩展策略
# ============================================================

@app.post("/api/strategy/high-turnover")
def high_turnover():
    """策略：高换手猎手"""
    global CACHE
    try:
        wl, df = _run_pipeline()
        pool = wl[(wl['换手率'] >= 5) & (wl['换手率'] <= 15) & (wl['涨跌幅'] >= 2) & (wl['涨跌幅'] <= 5)].copy()
        pool = pool.sort_values('换手率', ascending=False).head(10)
        recs = []
        for _, r in pool.iterrows():
            code = str(r['代码']).replace('sz','').replace('sh','').replace('bj','')
            recs.append({'code': code, 'name': str(r['名称']), 'price': round(float(r['最新价']),2),
                'chg': round(float(r['涨跌幅']),2), 'turnover': round(float(r['换手率']),1),
                'amount': round(float(r['成交额'])/1e8,1), 'risk': str(r.get('risk_level',''))})
        positions = _get_positions()
        open_pos = [p for p in positions if p.get('status') == 'open']
        CACHE['high_turnover'] = {'time': datetime.now().strftime('%H:%M:%S'), 'type': 'high_turnover',
            'title': '高换手猎手', 'desc': '换手5-15% · 涨幅2-5% · 资金活跃 · 短线爆发',
            'recommendations': recs, 'positions': _analyze_positions(open_pos, df)}
        return _safe_json({"status": "ok", **CACHE['high_turnover']})
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/strategy/oversold-bounce")
def oversold_bounce():
    """策略：低吸抄底"""
    global CACHE
    try:
        wl, df = _run_pipeline()
        pool = wl[(wl['涨跌幅'] <= -2) & (wl['涨跌幅'] >= -7) & (wl['换手率'] >= 2) & (wl['振幅'] <= 8)].copy()
        pool = pool.sort_values('涨跌幅', ascending=True).head(10)
        recs = []
        for _, r in pool.iterrows():
            code = str(r['代码']).replace('sz','').replace('sh','').replace('bj','')
            recs.append({'code': code, 'name': str(r['名称']), 'price': round(float(r['最新价']),2),
                'chg': round(float(r['涨跌幅']),2), 'turnover': round(float(r['换手率']),1),
                'amount': round(float(r['成交额'])/1e8,1), 'risk': str(r.get('risk_level','')),
                'hint': '缩量下跌企稳，次日反弹概率大'})
        positions = _get_positions()
        open_pos = [p for p in positions if p.get('status') == 'open']
        CACHE['oversold'] = {'time': datetime.now().strftime('%H:%M:%S'), 'type': 'oversold',
            'title': '低吸抄底', 'desc': '缩量下跌 · 止跌企稳 · 博次日反弹',
            'recommendations': recs, 'positions': _analyze_positions(open_pos, df)}
        return _safe_json({"status": "ok", **CACHE['oversold']})
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/strategy/breakout")
def breakout():
    """策略：突破追涨"""
    global CACHE
    try:
        wl, df = _run_pipeline()
        pool = wl[(wl['涨跌幅'] >= 4) & (wl['涨跌幅'] <= 8) & (wl['换手率'] >= 8) & (wl['振幅'] <= 12)].copy()
        if '最高' in pool.columns and '最新价' in pool.columns:
            pool['brk'] = (pool['最新价'] / pool['最高'] * 100).clip(0,100).fillna(0)
            pool = pool[pool['brk'] >= 95]
        pool = pool.sort_values('涨跌幅', ascending=False).head(10)
        recs = []
        for _, r in pool.iterrows():
            code = str(r['代码']).replace('sz','').replace('sh','').replace('bj','')
            recs.append({'code': code, 'name': str(r['名称']), 'price': round(float(r['最新价']),2),
                'chg': round(float(r['涨跌幅']),2), 'turnover': round(float(r['换手率']),1),
                'amount': round(float(r['成交额'])/1e8,1), 'risk': str(r.get('risk_level','')),
                'close_pct': round(float(r.get('brk', 0)),1), 'hint': '放量突破+强势收盘，次日惯性冲高'})
        positions = _get_positions()
        open_pos = [p for p in positions if p.get('status') == 'open']
        CACHE['breakout'] = {'time': datetime.now().strftime('%H:%M:%S'), 'type': 'breakout',
            'title': '突破追涨', 'desc': '放量上攻 · 强势收盘 · 次日惯性冲高',
            'recommendations': recs, 'positions': _analyze_positions(open_pos, df)}
        return _safe_json({"status": "ok", **CACHE['breakout']})
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ============================================================
# HTML — 六策略面板
# ============================================================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="description" content="迅股股 - 刘迅的A股量化选股系统">
<title>迅股股 · 量化选股</title>
<style>
:root{
  --bg:#090d13;--card:#11161d;--border:#1a2029;--text:#b0b8c4;--muted:#545d6b;
  --blue:#58a6ff;--green:#3fb950;--red:#f85149;--gold:#d29922;
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--text);padding:14px;max-width:520px;margin:0 auto;
  -webkit-font-smoothing:antialiased;
}
/* Brand */
.brand{text-align:center;padding:8px 0 6px}
.brand h1{font-size:20px;font-weight:800;color:#e6edf3;letter-spacing:2px}
.brand h1 span{color:var(--blue)}
.brand .by{font-size:10px;color:var(--muted)}
.brand .by em{color:var(--gold);font-style:normal}
/* Panel tabs */
.panel{
  display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin:10px 0 14px;
}
.panel-btn{
  padding:10px 6px;border:1px solid var(--border);border-radius:8px;
  background:var(--card);color:var(--muted);font-size:12px;font-weight:600;
  cursor:pointer;text-align:center;transition:all 0.15s;
}
.panel-btn .icon{font-size:16px;display:block;margin-bottom:2px}
.panel-btn.active{border-color:var(--blue);color:var(--blue);background:rgba(88,166,255,.06)}
.panel-btn.scanned{border-color:var(--green);color:var(--green)}
/* Content */
.content{margin-bottom:14px}
/* Describe text */
.desc{font-size:11px;color:var(--muted);text-align:center;margin:6px 0 10px}
/* Section */
.sec{margin-bottom:16px}
.sec-hd{font-size:12px;font-weight:700;color:var(--muted);letter-spacing:2px;margin-bottom:8px}
/* Summary card for midday */
.summary-card{
  background:rgba(210,153,34,.06);border:1px solid rgba(210,153,34,.15);
  border-radius:10px;padding:14px;margin-bottom:10px;font-size:13px;line-height:1.6;
}
.summary-card .s{color:var(--gold);font-weight:700}
.advice-card{
  background:rgba(88,166,255,.06);border:1px solid rgba(88,166,255,.15);
  border-radius:8px;padding:10px 14px;font-size:12px;color:var(--blue);margin-bottom:10px;
}
/* Rec card */
.rec-card{
  background:var(--card);border:1px solid var(--border);border-radius:8px;
  padding:12px;margin-bottom:6px;display:flex;gap:10px;align-items:center;
}
.rec-rank{font-size:16px;font-weight:800;color:var(--blue);min-width:20px;text-align:center}
.rec-body{flex:1;min-width:0}
.rec-name{font-size:13px;font-weight:700;color:#e6edf3}
.rec-meta{font-size:10px;color:var(--muted);margin-top:2px}
.rec-price{text-align:right}
.rec-price .p{font-size:14px;font-weight:700}
/* Overnight card */
.over-card{
  background:linear-gradient(135deg,#0c1810,#111d14);border:1px solid rgba(63,185,80,.2);
  border-radius:8px;padding:12px;margin-bottom:6px;
}
.sell-plan{font-size:10px;color:var(--gold);margin-top:5px;padding:5px 8px;background:rgba(210,153,34,.06);border-radius:4px}
/* Position card */
.pos-card{
  background:var(--card);border-radius:8px;padding:12px;margin-bottom:6px;
  border-left:3px solid var(--border);
}
.pos-card.sell{border-left-color:var(--red);background:rgba(248,81,73,.03)}
.pos-card.warn{border-left-color:var(--gold);background:rgba(210,153,34,.02)}
.pos-card.hold{border-left-color:var(--green);background:rgba(63,185,80,.02)}
.pos-row{display:flex;justify-content:space-between;align-items:center}
.pos-name{font-size:13px;font-weight:700;color:#e6edf3}
.pos-pnl{font-size:16px;font-weight:800}
.pos-meta{font-size:10px;color:var(--muted);margin:3px 0}
.pos-act{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;margin-right:5px}
.a-sell{background:rgba(248,81,73,.15);color:var(--red)}
.a-warn{background:rgba(210,153,34,.15);color:var(--gold)}
.a-hold{background:rgba(63,185,80,.15);color:var(--green)}
/* Sectors */
.sectors{display:flex;flex-wrap:wrap;gap:4px}
.s-tag{background:var(--card);border:1px solid var(--border);border-radius:4px;padding:3px 7px;font-size:10px;color:var(--muted)}
.s-tag b{color:var(--text)}
/* Upload */
.up-zone{
  border:1px dashed var(--border);border-radius:8px;padding:16px;text-align:center;
  color:var(--muted);cursor:pointer;transition:all 0.2s;
}
.up-zone:hover{border-color:#30363d}
.up-zone input{display:none}
.recog-info{font-size:10px;color:#21262d;text-align:center;margin-top:8px;line-height:1.5}
/* Empty */
.empty{text-align:center;padding:16px;color:#2a303c;font-size:12px}
/* Toast */
.toast{
  position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:99;
  padding:8px 20px;border-radius:6px;font-size:12px;font-weight:600;
  background:#21262d;color:#e6edf3;display:none;
}
.ft{text-align:center;font-size:9px;color:#1a2029;padding:16px 0 8px}
</style>
</head>
<body>

<div class="brand">
  <h1>迅<span>股</span>股</h1>
  <div class="by">by <em>刘迅</em></div>
</div>

<div class="toast" id="toast"></div>

<!-- 三策略面板 -->
<div class="panel">
  <button class="panel-btn active" id="btn-morning" onclick="runMode('morning')">
    <span class="icon">☼</span>早盘推荐
  </button>
  <button class="panel-btn" id="btn-midday" onclick="runMode('midday')">
    <span class="icon">☀</span>午间分析
  </button>
  <button class="panel-btn" id="btn-overnight" onclick="runMode('overnight')">
    <span class="icon">☽</span>一夜持股
  </button>
</div>

<div class="content" id="content"><div class="empty">点击上方按钮开始</div></div>

<!-- 持仓导入 -->
<div class="sec">
  <div class="sec-hd">导入持仓</div>
  <div class="up-zone" onclick="document.getElementById('fu').click()">
    <div style="font-size:20px;margin-bottom:2px">+</div>
    <div style="font-size:11px">上传东方财富持仓截图</div>
    <input type="file" id="fu" accept="image/*" onchange="doUpload(this)">
  </div>
  <div id="upStatus" style="font-size:10px;margin-top:4px;text-align:center"></div>
  <div class="recog-info">
    识别策略：千问VL → OCR原始 → OCR增强 → OCR模糊匹配（4层回退）
  </div>
</div>

<div class="ft">迅股股 v7.0 · 仅供学习研究</div>

<script>
var active='morning';

function T(m){var d=document.getElementById('toast');d.textContent=m;d.style.display='block';setTimeout(function(){d.style.display='none'},2500)}

function setActive(m){
  active=m;
  ['morning','midday','overnight'].forEach(function(x){
    var b=document.getElementById('btn-'+x);
    b.className='panel-btn'+(x===m?' active':'');
  });
}

function render(d){
  if(!d)return;
  var h='<div class="desc">'+d.desc+' · '+d.time+'</div>';

  // 午间特殊处理
  if(d.type==='midday'){
    if(d.summary){
      h+='<div class="summary-card"><span class="s">上午复盘：</span>'+d.summary+'</div>';
      h+='<div class="advice-card">下午建议：'+d.advice+'</div>';
    }
  }

  // 推荐列表
  if(d.recommendations && d.recommendations.length>0){
    var isOver=d.type==='overnight';
    h+='<div class="sec"><div class="sec-hd">'+(isOver?'一夜持股精选':'推荐标的')+'</div>';
    d.recommendations.forEach(function(r,i){
      var cls=r.chg>0?'color:#f85149':'color:#3fb950';
      var rc=r.risk==='低风险'?' <span style=\"color:#3fb950;font-size:9px\">低风险</span>':'';
      var card=isOver?'over-card':'rec-card';

      h+='<div class=\"'+card+'\">'+
        '<div class=\"rec-rank\">'+(i+1)+'</div>'+
        '<div class=\"rec-body\">'+
          '<div class=\"rec-name\">'+r.code+' '+r.name+rc+'</div>'+
          '<div class=\"rec-meta\">'+
            (isOver?'夜盘评分 '+r.score+' · 量比 '+r.volume_ratio+' · 收盘强度 '+r.close_ratio+'%':'评分 '+r.score+' · 成交 '+r.amount+'亿 · 换手 '+r.turnover+'%')+
          '</div>'+
        '</div>'+
        '<div class=\"rec-price\"><div class=\"p\">'+r.price+'</div><div class=\"chg\" style=\"'+cls+';font-size:12px;font-weight:600\">'+(r.chg>0?'+':'')+r.chg+'%</div></div>'+
      '</div>';
      if(isOver){
        h+='<div class=\"sell-plan\">→ 次日：'+r.sell_plan+'</div>';
      }
    });
    h+='</div>';
  }else if(d.type!=='midday'){
    h+='<div class="sec"><div class="sec-hd">推荐标的</div><div class="empty">暂无合适标的<br><span style="font-size:10px;color:#1a2029">已过滤涨停/涨幅>8%/高风险</span></div></div>';
  }

  // 持仓
  if(d.positions && d.positions.length>0){
    h+='<div class="sec"><div class="sec-hd">持仓分析</div>';
    d.positions.forEach(function(p){
      var cls=p.pnl_pct>=0?'color:#f85149':'color:#3fb950';
      h+='<div class=\"pos-card '+p.action_color+'\">'+
        '<div class=\"pos-row\"><div class=\"pos-name\">'+p.code+' '+p.name+'</div><div class=\"pos-pnl\" style=\"'+cls+'\">'+(p.pnl_pct>=0?'+':'')+p.pnl_pct+'%</div></div>'+
        '<div class=\"pos-meta\">成本'+p.cost+' 现价'+p.now+' '+p.shares+'股 今日'+(p.today_chg>=0?'+':'')+p.today_chg+'%'+(p.turnover?' 换手'+p.turnover+'%':'')+'</div>'+
        '<span class=\"pos-act a-'+p.action_color+'\">'+p.action+'</span>'+
        '<span style=\"font-size:10px;color:#768390\">'+p.action_detail+'</span>'+
      '</div>';
    });
    h+='</div>';
  }

  // 板块
  if(d.sectors && d.sectors.length>0){
    h+='<div class="sec"><div class="sec-hd">板块热度</div><div class="sectors">';
    d.sectors.forEach(function(s){
      var cls=s.avg_chg>0?'color:#f85149':'color:#3fb950';
      h+='<span class=\"s-tag\"><b>'+s.name+'</b> '+s.count+'只 <span style=\"'+cls+'\">'+(s.avg_chg>0?'+':'')+s.avg_chg+'%</span></span>';
    });
    h+='</div></div>';
  }

  document.getElementById('content').innerHTML=h||'<div class="empty">暂无数据</div>';
}

async function runMode(mode){
  setActive(mode);
  document.getElementById('content').innerHTML='<div class="empty">分析中...</div>';
  try{
    var r=await fetch('/api/'+mode,{method:'POST'});
    var d=await r.json();
    if(d.status==='error'){T(d.message);return}
    render(d);
    document.getElementById('btn-'+mode).classList.add('scanned');
    T({morning:'早盘推荐',midday:'午间分析',overnight:'一夜持股'}[mode]+'完成');
  }catch(e){document.getElementById('content').innerHTML='<div class="empty">网络错误</div>'}
}

async function doUpload(inp){
  var f=inp.files[0];if(!f)return;
  document.getElementById('upStatus').innerHTML='<span style=\"color:#545d6b\">识别中（4策略并行）...</span>';
  var fd=new FormData();fd.append('file',f);
  try{
    var r=await fetch('/api/upload-positions',{method:'POST',body:fd});
    var d=await r.json();
    if(d.status==='ok'){
      document.getElementById('upStatus').innerHTML='<span style=\"color:#3fb950\">导入成功 '+d.count+'只（'+d.method+'）</span>';
      T('识别成功 · '+d.method);
      render({positions:d.positions,type:'midday'});
      setTimeout(function(){runMode('midday')},1500);
    }else{
      document.getElementById('upStatus').innerHTML='<span style=\"color:#f85149\">'+d.message+'</span>';
    }
  }catch(e){document.getElementById('upStatus').innerHTML='<span style=\"color:#f85149\">网络错误</span>'}
}

// Init
runMode('morning');
</script>
</body>
</html>"""
