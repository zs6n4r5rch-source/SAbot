from pathlib import Path


CLIENT = Path(__file__).parents[1] / "app" / "services" / "langame.py"
CONFIG = Path(__file__).parents[1] / "app" / "config.py"


def test_langame_client_has_no_generic_write_methods():
    source = CLIENT.read_text()
    assert "async def _put(" not in source
    assert "async def _patch(" not in source
    assert "async def _delete(" not in source
    assert "async def _post(" not in source


def test_langame_request_gate_allows_only_reads_and_guest_search():
    source = CLIENT.read_text()
    assert 'if normalized_method == "GET":' in source
    assert 'normalized_method == "POST" and normalized_path in self.READ_ONLY_POST_PATHS' in source
    assert "raise LangameReadOnlyViolation" in source
    assert 'READ_ONLY_POST_PATHS = frozenset({"/guests/search"})' in source


def test_read_only_mode_is_mandatory():
    source = CONFIG.read_text()
    assert "if not settings.langame_read_only:" in source
    assert "LANGAME_READ_ONLY must be true" in source
