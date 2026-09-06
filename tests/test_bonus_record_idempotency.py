from app.models import BonusRecord


def test_bonus_record_has_idempotency_source_key():
    table = BonusRecord.__table__
    assert "source" in table.c
    assert "source_id" in table.c
    index = next(i for i in table.indexes if i.name == "ix_bonus_records_source")
    assert index.unique is True
    assert [column.name for column in index.columns] == ["source", "source_id"]
