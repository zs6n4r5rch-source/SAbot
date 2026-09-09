from app.services.langame_sync_scheduler import _count_records


def test_count_records_accepts_common_langame_wrappers():
    assert _count_records([{"id": 1}, {"id": 2}]) == 2
    assert _count_records({"items": [{"id": 1}]}) == 1
    assert _count_records({"data": {"results": [{"id": 1}, {"id": 2}, {"id": 3}]}}) == 3
    assert _count_records({"id": 1}) == 1
    assert _count_records({}) == 0


def test_sync_scheduler_declares_all_required_read_only_contours():
    source = __import__("inspect").getsource(__import__("app.services.langame_sync_scheduler", fromlist=["langame_verification_sync_once"]).langame_verification_sync_once)
    for contour in ("clubs", "users", "shifts", "products", "balances", "guest_groups", "guest_sessions", "transactions", "operations_log", "product_sales", "product_arrivals"):
        assert f'"{contour}"' in source
