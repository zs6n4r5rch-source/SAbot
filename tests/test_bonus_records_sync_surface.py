from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bonus_sync_is_registered_and_keyed_by_salary_period_and_adjustment():
    service = (ROOT / "app/services/bonus_records.py").read_text()
    router = (ROOT / "app/bot/bonus_records.py").read_text()
    main = (ROOT / "app/main.py").read_text()

    assert 'source = "salary_adjustment"' in service
    assert 'source_id = f"{period.id}:{adjustment.id}"' in service
    assert "/sync_bonus_records" in router
    assert "bonus_records_router" in main
