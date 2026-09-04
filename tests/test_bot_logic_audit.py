from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def test_no_duplicate_exact_router_message_decorators():
    seen = {}
    for p in (ROOT / 'app').rglob('*.py'):
        tree = ast.parse(p.read_text())
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    text = ast.unparse(d)
                    if text.startswith('router.message('):
                        seen.setdefault(text, []).append((str(p), n.name))
    dupes = {k:v for k,v in seen.items() if len(v)>1}
    assert not dupes, dupes


def test_salary_ideal_close_checks_cleaning_only_when_scheduled():
    salary = (ROOT / 'app' / 'bot' / 'salary.py').read_text()
    assert 'scheduled_cleaning_ids' in salary
    assert 'r.shift_id not in scheduled_cleaning_ids' in salary


def test_salary_period_uses_moscow_calendar_bounds():
    salary = (ROOT / 'app' / 'bot' / 'salary.py').read_text()
    assert 'tzinfo=MOSCOW_TZ).astimezone(timezone.utc)' in salary
