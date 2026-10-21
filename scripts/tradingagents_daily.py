"""Independent official TradingAgents analysis and SMTP delivery.

This entry point deliberately does not import DSA's analysis pipeline. Run it
inside the separate TradingAgents virtual environment configured by the workflow.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
import json
import math
import os
from pathlib import Path
import smtplib
import ssl
import time
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo('Asia/Shanghai')


def delivery_target(now):
    local = now.astimezone(SHANGHAI)
    if local.weekday() >= 5:
        raise ValueError('Delivery is configured for a Shanghai weekday only')
    return local.replace(hour=7, minute=0, second=0, microsecond=0)


def latest_session(exchange, now):
    import exchange_calendars as xcals
    import pandas as pd

    today = now.astimezone(timezone.utc).date()
    calendar = xcals.get_calendar(
        exchange, start=str(today - timedelta(days=45)),
        end=str(today + timedelta(days=3)),
    )
    schedule = calendar.schedule
    finished = schedule[schedule['close'] <= pd.Timestamp(now)]
    if finished.empty:
        raise ValueError('No completed exchange session in the calendar window')
    return finished.index[-1].date()


def validate_quote(expected_session, actual_session, close, previous_close):
    if str(expected_session) != str(actual_session):
        raise ValueError('Latest quote does not match the completed session')
    if any(not math.isfinite(float(p)) or float(p) <= 0 for p in (close, previous_close)):
        raise ValueError('Missing or invalid price')
    return round((float(close) / float(previous_close) - 1) * 100, 4)


def quote_for_session(ticker, session):
    import yfinance as yf

    prices = yf.Ticker(ticker).history(
        start=str(session - timedelta(days=20)),
        end=str(session + timedelta(days=1)),
        auto_adjust=False, timeout=30,
    )
    if len(prices) < 2:
        raise ValueError('Not enough quote history')
    close = float(prices['Close'].iloc[-1])
    previous = float(prices['Close'].iloc[-2])
    actual = prices.index[-1].date()
    change = validate_quote(session, actual, close, previous)
    return close, change


def framework_config(ticker, output):
    from tradingagents.default_config import build_default_config

    model = os.environ.get('TA_MODEL') or os.environ.get('OPENAI_MODEL')
    endpoint = os.environ.get('OPENAI_BASE_URL')
    if not model or not endpoint or not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('Missing model configuration')
    os.environ['OPENAI_COMPATIBLE_API_KEY'] = os.environ['OPENAI_API_KEY']
    config = deepcopy(build_default_config())
    config.update({
        'llm_provider': 'openai_compatible', 'backend_url': endpoint,
        'quick_think_llm': model, 'deep_think_llm': model,
        'quick_think_provider': None, 'deep_think_provider': None,
        'quick_think_backend_url': None, 'deep_think_backend_url': None,
        'output_language': '简体中文',
        'max_debate_rounds': 1, 'max_risk_discuss_rounds': 1,
        'max_tool_rounds': 4, 'max_recur_limit': 80,
        'max_tokens': 4096, 'llm_max_retries': 1,
        'results_dir': str(output / ticker / 'framework'),
        'data_cache_dir': str(output / ticker / 'cache'),
        'memory_log_path': str(output / ticker / 'memory.md'),
        'checkpoint_enabled': False,
    })
    # Explicit, keyless data sources: no fallback to unconfigured paid vendors.
    config['data_vendors'].update({
        'core_stock_apis': 'yfinance', 'technical_indicators': 'yfinance',
        'fundamental_data': 'sec_edgar,yfinance', 'news_data': 'yfinance',
    })
    return config


def analyze(ticker, output):
    now = datetime.now(timezone.utc)
    result = {'ticker': ticker, 'status': 'error', 'generated_at': now.isoformat()}
    stage = 'framework_import'
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        stage = 'exchange_calendar'
        session = latest_session('XKRX' if ticker.endswith('.KS') else 'XNYS', now)
        stage = 'quote_validation'
        close, change = quote_for_session(ticker, session)
        stage = 'model_configuration'
        config = framework_config(ticker, output)
        stage = 'independent_analysis'
        graph = TradingAgentsGraph(
            selected_analysts=('market', 'news', 'fundamentals'), config=config,
        )
        state, decision = graph.propagate(ticker, str(session))
        final = state.get('final_trade_decision')
        if not isinstance(final, str) or not final.strip():
            raise ValueError('TradingAgents produced no final analysis')
        sections = [final]
        for key, label in (
            ('market_report', '技术分析'), ('news_report', '新闻分析'),
            ('fundamentals_report', '基本面分析'), ('investment_plan', '多空论证'),
        ):
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                sections.append(f'### {label}\n\n{value}')
        result.update({
            'status': 'ok', 'session': str(session), 'close': close,
            'change_pct': change, 'currency': 'KRW' if ticker.endswith('.KS') else 'USD',
            'decision': str(decision), 'report': '\n\n'.join(sections),
            'model': config['quick_think_llm'],
        })
    except Exception as exc:
        # Provider exceptions can include request URLs/credentials. Keep them out
        # of mail and artifacts; GitHub logs only receive the safe error class.
        result['error_type'] = type(exc).__name__
        result['failed_stage'] = stage
    output.mkdir(parents=True, exist_ok=True)
    (output / f'{ticker}.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(f'{ticker}: {result["status"]} {result.get("error_type", "")}')
    return 0 if result['status'] == 'ok' else 1


def render_report(results, generated):
    local = generated.astimezone(SHANGHAI)
    lines = [f'# TradingAgents 独立日报 · {local:%Y-%m-%d}',
             f'生成时间：{local:%Y-%m-%d %H:%M:%S %Z}。行情采用各市场最近已完成交易日，币种见每节。',
             '本报告由官方 TradingAgents 独立运行，未读取 Daily Stock Analysis 的分析结论。',
             '两套系统可能使用同一模型及行情源；结论一致不足以证明正确。未提供持仓成本与投资期限，以下为条件性参考。',
             '仅分析，不执行交易。模型报告中的价格和事实需核对；行情表使用 Yahoo 原始收盘价计算涨跌幅。',
             '分析日期采用标注的交易日；新闻/基本面存在数据源和历史可用性限制，不能视为截至发信时的完整实时信息。',
             '周一及休市日仍发报告，明确展示上一有效交易日期；不会虚构当日交易。', '']
    for item in results:
        lines.append(f'## {item["ticker"]}')
        if item['status'] != 'ok':
            lines.append(f'分析失败／无有效结果：{item.get("error_type", "MissingResult")} '
                         f'({item.get("failed_stage", "result_collection")})。不生成买卖建议。\n')
            continue
        lines.extend([
            f'交易日期：{item["session"]} | 收盘：{item["close"]:.2f} {item["currency"]} | 涨跌：{item["change_pct"]:+.2f}%',
            f'框架评级：{item["decision"]} | 模型：{item.get("model", "未记录")}',
            item['report'], '',
        ])
    return '\n\n'.join(lines)


def send_email(subject, body):
    required = ('EMAIL_PASSWORD', 'EMAIL_SENDER', 'EMAIL_RECEIVERS', 'TA_SMTP_HOST')
    for key in required:
        if not os.environ.get(key, '').strip():
            raise ValueError(f'Missing {key}')
    receivers = [v.strip() for v in os.environ['EMAIL_RECEIVERS'].split(',') if v.strip()]
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr(('TradingAgents 独立分析', os.environ['EMAIL_SENDER']))
    msg['To'] = ', '.join(receivers)
    msg['Date'] = formatdate(localtime=False)
    msg['Message-ID'] = make_msgid()
    msg.set_content(body)
    # All external/model text is escaped; no model-supplied HTML/scripts/images.
    from html import escape
    msg.add_alternative(
        '<html><body><pre style="white-space:pre-wrap;font:15px/1.6 sans-serif">'
        + escape(body) + '</pre></body></html>', subtype='html',
    )
    context = ssl.create_default_context()
    port = int(os.environ.get('TA_SMTP_PORT', '465'))
    with smtplib.SMTP_SSL(os.environ['TA_SMTP_HOST'], port, timeout=40, context=context) as server:
        server.login(os.environ['EMAIL_SENDER'], os.environ['EMAIL_PASSWORD'])
        refused = server.send_message(msg, to_addrs=receivers)
        if refused:
            raise RuntimeError('SMTP refused at least one recipient')


def mail(output, tickers, wait):
    generated = datetime.now(timezone.utc)
    target = delivery_target(generated) if wait else generated
    results = []
    for ticker in tickers:
        path = output / f'{ticker}.json'
        if path.exists():
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                if item['ticker'] != ticker or item.get('status') not in ('ok', 'error'):
                    raise ValueError('Invalid artifact')
                results.append(item)
                continue
            except (ValueError, KeyError):
                pass
        results.append({'ticker': ticker, 'status': 'error', 'error_type': 'MissingResult'})
    body = render_report(results, generated)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'TradingAgents-report.md').write_text(body, encoding='utf-8')
    while wait and datetime.now(timezone.utc) < target:
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        time.sleep(min(remaining, 30))
    sent_at = datetime.now(timezone.utc)
    late = wait and sent_at > target + timedelta(minutes=5)
    subject = f'[TradingAgents] {sent_at.astimezone(SHANGHAI):%Y-%m-%d} 独立股票分析'
    if late:
        subject += '（延迟发送）'
    send_email(subject, body)
    print('TradingAgents report accepted by SMTP; inbox delivery must be verified separately.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    analysis = sub.add_parser('analyze')
    analysis.add_argument('--ticker', required=True)
    analysis.add_argument('--output', type=Path, required=True)
    sender = sub.add_parser('mail')
    sender.add_argument('--output', type=Path, required=True)
    sender.add_argument('--tickers', required=True)
    sender.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    if args.command == 'analyze':
        return analyze(args.ticker, args.output)
    return mail(args.output, args.tickers.split(','), args.wait)


if __name__ == '__main__':
    raise SystemExit(main())
