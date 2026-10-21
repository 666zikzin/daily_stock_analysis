"""Offline contracts for the separate TradingAgents reporting pipeline."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/tradingagents_daily.py'


def module():
    assert SCRIPT.exists(), 'TradingAgents runner is not implemented'
    spec = importlib.util.spec_from_file_location('ta_daily', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(('exchange', 'asof', 'expected'), [
    ('XNYS', '2026-10-18T23:00:00+00:00', '2026-10-16'),
    ('XNYS', '2026-07-06T23:00:00+00:00', '2026-07-06'),
    ('XNYS', '2026-07-05T23:00:00+00:00', '2026-07-02'),
    ('XNYS', '2026-11-03T00:00:00+00:00', '2026-11-02'),
    ('XKRX', '2026-10-18T23:00:00+00:00', '2026-10-16'),
    ('XKRX', '2026-10-19T06:00:00+00:00', '2026-10-16'),
    ('XKRX', '2026-10-19T07:00:00+00:00', '2026-10-19'),
])
def test_selects_completed_exchange_session(exchange, asof, expected):
    assert str(module().latest_session(exchange, datetime.fromisoformat(asof))) == expected


def test_weekday_delivery_target_is_seven_shanghai():
    target = module().delivery_target(datetime(2026, 10, 18, 22, tzinfo=timezone.utc))
    assert target.isoformat() == '2026-10-19T07:00:00+08:00'


def test_weekend_delivery_rejected():
    with pytest.raises(ValueError, match='weekday'):
        module().delivery_target(datetime(2026, 10, 17, 0, tzinfo=timezone.utc))


def test_stale_quote_is_rejected():
    with pytest.raises(ValueError, match='session'):
        module().validate_quote('2026-10-16', '2026-10-15', 100.0, 99.0)


def test_invalid_quote_is_rejected():
    for value in (0, -5, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='price'):
            module().validate_quote('2026-10-16', '2026-10-16', value, 99.0)


def test_change_calculation_uses_matching_raw_closes():
    assert module().validate_quote('2026-10-16', '2026-10-16', 99.0, 100.0) == -1.0


def test_report_preserves_failures_without_recommendations():
    result = module().render_report([
        {'ticker': 'VOO', 'status': 'ok', 'session': '2026-10-16',
         'currency': 'USD', 'close': 100, 'change_pct': 1,
         'report': '独立分析', 'decision': 'HOLD'},
        {'ticker': '000660.KS', 'status': 'error', 'error_type': 'TimeoutError'},
    ], datetime(2026, 10, 19, 7, tzinfo=timezone.utc))
    assert 'TradingAgents' in result and '2026-10-16' in result
    assert '000660.KS' in result and '分析失败' in result
    assert '同一模型' in result and '不足' in result


def test_mail_refuses_missing_credentials(monkeypatch):
    monkeypatch.delenv('EMAIL_PASSWORD', raising=False)
    with pytest.raises(ValueError, match='EMAIL_PASSWORD'):
        module().send_email('test', 'body')


def test_real_framework_initializes_with_shared_endpoint_without_calling_it(monkeypatch, tmp_path):
    pytest.importorskip('tradingagents', reason='Only installed in the separate TradingAgents environment')
    mod = module()
    monkeypatch.setenv('OPENAI_MODEL', 'test-tool-capable-model')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://example.invalid/v1')
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-key')
    monkeypatch.delenv('TA_MODEL', raising=False)
    config = mod.framework_config('VOO', tmp_path)
    assert config['backend_url'] == 'https://example.invalid/v1'
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    graph = TradingAgentsGraph(selected_analysts=('market', 'news', 'fundamentals'), config=config)
    assert graph.config['output_language'] == '简体中文'
    assert graph.config['quick_think_llm'] == 'test-tool-capable-model'


def test_mail_collects_success_and_missing_result_in_one_message(monkeypatch, tmp_path):
    mod = module()
    import json
    (tmp_path / 'VOO.json').write_text(json.dumps({
        'ticker': 'VOO', 'status': 'ok', 'session': '2026-10-16',
        'currency': 'USD', 'close': 100, 'change_pct': 1,
        'report': 'Test analysis <script>not executable</script>', 'decision': 'HOLD',
    }), encoding='utf-8')
    for key, value in {'EMAIL_PASSWORD': 'fake', 'EMAIL_SENDER': 'sender@example.com',
                       'EMAIL_RECEIVERS': 'to@example.com', 'TA_SMTP_HOST': 'smtp.example.com'}.items():
        monkeypatch.setenv(key, value)
    messages = []
    class SMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def send_message(self, msg, **kw): messages.append(msg); return {}
    monkeypatch.setattr(mod.smtplib, 'SMTP_SSL', SMTP)
    assert mod.mail(tmp_path, ['VOO', '000660.KS'], wait=False) == 0
    plain = messages[0].get_body(preferencelist=('plain',)).get_content()
    html = messages[0].get_body(preferencelist=('html',)).get_content()
    assert '2026-10-16' in plain and '000660.KS' in plain and 'MissingResult' in plain
    assert '<script>' not in html and '&lt;script&gt;' in html


def test_workflow_is_separate_and_uses_exact_symbols():
    path = ROOT / '.github/workflows/tradingagents-daily.yml'
    assert path.exists(), 'Separate workflow is not implemented'
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    triggers = data.get('on', data.get(True))
    assert triggers['schedule'][0]['cron'] == '30 21 * * 0-4'
    matrix = data['jobs']['analyze']['strategy']['matrix']['ticker']
    assert matrix == ['VOO', 'QQQ', 'RKLB', '000660.KS', 'CHWY', 'GLXY', 'GOOGL']
    assert data['jobs']['analyze']['strategy']['fail-fast'] is False
    assert data['concurrency']['group'] != 'stock-analysis'
    assert data['jobs']['mail']['if'] == '${{ always() && !cancelled() }}'


def test_mail_rejects_partial_smtp_refusal(monkeypatch):
    mod = module()
    monkeypatch.setenv('EMAIL_PASSWORD', 'test-password')
    monkeypatch.setenv('EMAIL_SENDER', 'sender@example.com')
    monkeypatch.setenv('EMAIL_RECEIVERS', 'to@example.com')
    monkeypatch.setenv('TA_SMTP_HOST', 'smtp.example.com')
    class SMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): pass
        def send_message(self, *args, **kwargs): return {'to@example.com': (550, b'refused')}
    monkeypatch.setattr(mod.smtplib, 'SMTP_SSL', SMTP)
    with pytest.raises(RuntimeError, match='refused'):
        mod.send_email('test', 'body')
