"""No-network contracts for paid report scheduling."""
import importlib.util
from datetime import datetime
from pathlib import Path
import pytest

@pytest.mark.parametrize(('day','expected'), [
    ('2026-11-02',()),('2026-11-03',('dsa',)),
    ('2026-11-07',('dsa','ta')),('2026-09-08',()),
    ('2026-07-03',('dsa','ta')),('2026-07-04',()),
    ('2026-04-03',('dsa','ta')),('2026-04-04',()),
    ('2026-11-28',('dsa','ta')),
])
def test_only_due_reports_use_paid_generation(day,expected):
    path=Path(__file__).resolve().parents[1]/'scripts/report_cadence.py'
    spec=importlib.util.spec_from_file_location('cadence',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert mod.expected_reports(datetime.fromisoformat(day+'T07:30:00+08:00'))==expected
