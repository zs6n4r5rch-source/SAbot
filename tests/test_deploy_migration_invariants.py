from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_uses_alembic_upgrade_instead_of_create_all_or_stamp():
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "alembic upgrade head" in entrypoint
    assert "alembic stamp head" not in entrypoint
    assert "Base.metadata.create_all" not in entrypoint
    assert "Base.metadata.create_all" not in main
    assert "def init_database" not in main
