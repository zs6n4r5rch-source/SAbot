from app.services.export import ExportService


def test_build_xlsx_creates_unique_filename_and_metadata(tmp_path, monkeypatch):
    service = ExportService()
    monkeypatch.setattr("app.services.export.Path", lambda *parts: tmp_path)

    first = service.build_xlsx(
        "statistics/report",
        ["name", "amount"],
        [{"name": "A", "amount": 10}],
        filters={"days": 30},
        totals={"rows": 1},
        timezone_name="Europe/Moscow",
    )
    second = service.build_xlsx(
        "statistics/report",
        ["name"],
        [{"name": "B"}],
        timezone_name="Europe/Moscow",
    )

    assert first != second
    assert first.suffix == ".xlsx"
    assert first.exists() and second.exists()
