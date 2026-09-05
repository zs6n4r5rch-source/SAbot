from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_inventory_sync_preserves_local_control_adjustments():
    text = (ROOT / "app" / "bot" / "inventory.py").read_text()
    assert "_apply_langame_delta" in text
    assert "new_langame - previous_langame" in text
    assert 'balance.quantity = max(Decimal("0"), _apply_langame_delta(' in text


def test_owner_menu_has_single_admin_control_entry():
    text = (ROOT / "app" / "bot" / "keyboards.py").read_text()
    assert text.count('KeyboardButton(text="🔎 Контроль администраторов")') == 1
    assert 'Индекс риска администраторов' not in text


def test_langame_risk_baseline_does_not_fetch_each_historical_shift():
    text = (ROOT / "app" / "bot" / "integrity.py").read_text()
    assert 'for ps in prior:' in text
    assert 'await sales_rows(ps.started_at' not in text


def test_shift_close_shortages_require_comments_and_store_them():
    model = (ROOT / "app" / "models" / "salary.py").read_text()
    flow = (ROOT / "app" / "bot" / "shift_closing.py").read_text()
    assert 'cash_comment: Mapped[str | None]' in model
    assert 'comment: Mapped[str | None] = mapped_column(Text)' in model
    assert 'waiting_cash_comment = State()' in flow
    assert 'waiting_stock_comment = State()' in flow
    assert 'if report.cash_difference < 0:' in flow
    assert 'if item.difference < 0:' in flow
    assert 'report.cash_comment = comment[:4000]' in flow
    assert 'item.comment = comment[:4000]' in flow
    assert 'f"📝 Комментарий по кассе: {report.cash_comment or \'—\'}\\n"' in flow


def test_shift_close_comments_migration_exists():
    migration = (ROOT / "alembic" / "versions" / "0012_shift_close_comments.py").read_text()
    assert 'down_revision = "0011_shift_close_reports"' in migration
    assert '"cash_comment"' in migration
    assert '"comment"' in migration


def test_shift_close_shortage_reasons_are_structured():
    model = (ROOT / "app" / "models" / "salary.py").read_text()
    flow = (ROOT / "app" / "bot" / "shift_closing.py").read_text()
    migration = (ROOT / "alembic" / "versions" / "0013_shift_shortage_reasons.py").read_text()
    assert 'cash_shortage_reason: Mapped[str | None]' in model
    assert 'shortage_reason: Mapped[str | None]' in model
    assert 'SHORTAGE_REASONS' in flow
    assert 'Бой / порча' in flow
    assert 'Списание не оформлено' in flow
    assert 'Ошибка пересчёта' in flow
    assert 'Выдача администратору за отзывы гостей' in flow
    assert '"review_reward"' in flow
    assert 'shift_shortage:' in flow
    assert 'down_revision = "0012_shift_close_comments"' in migration


def test_inventory_does_not_auto_promote_unknown_users():
    text = (ROOT / "app" / "bot" / "inventory.py").read_text()
    assert "ensure_bootstrap_owner" not in text
    assert "return await get_access(message)" in text


def test_manual_penalty_is_committed_after_audit():
    text = (ROOT / "app" / "bot" / "penalties.py").read_text()
    block = text[text.index("async def create_manual_penalty"):text.index("async def auto_penalty_late_report")]
    assert "await write_audit(" in block
    assert block.rfind("await session.commit()") > block.rfind("await write_audit(")


def test_staff_binding_audit_is_committed():
    text = (ROOT / "app" / "bot" / "staff_binding.py").read_text()
    start = text.index('@router.callback_query(F.data.startswith("bind:approve:"))')
    end = text.index('@router.callback_query(F.data.startswith("bind:reject:"))')
    block = text[start:end]
    assert "await write_audit(" in block
    assert block.rfind("await session.commit()") > block.rfind("await write_audit(")
