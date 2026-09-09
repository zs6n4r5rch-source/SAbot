import ast
from pathlib import Path


def test_scheduled_mailing_module_is_valid_python():
    path = Path(__file__).parents[1] / "app" / "bot" / "scheduled_mailing.py"
    ast.parse(path.read_text(encoding="utf-8"))


def test_marketing_scheduler_is_valid_python():
    path = Path(__file__).parents[1] / "app" / "services" / "marketing_scheduler.py"
    ast.parse(path.read_text(encoding="utf-8"))


def test_langame_sync_scheduler_is_valid_python():
    path = Path(__file__).parents[1] / "app" / "services" / "langame_sync_scheduler.py"
    ast.parse(path.read_text(encoding="utf-8"))
