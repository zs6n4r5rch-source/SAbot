import ast
from pathlib import Path


def test_unified_shell_has_real_states_and_back_navigation():
    source = Path('app/webapp/static/index.html').read_text(encoding='utf-8')
    assert 'Загрузка' in source
    assert 'Раздел недоступен' in source
    assert 'state.stack' in source
    assert 'previousShift' in source


def test_root_does_not_use_page_composer():
    source = Path('app/webapp/app.py').read_text(encoding='utf-8')
    assert 'page_composer' not in source
    assert 'STATIC_DIR / "index.html"' in source


def test_permissions_are_centralized():
    source = Path('app/permissions/core.py').read_text(encoding='utf-8')
    ast.parse(source)
    assert 'ROLE_PERMISSIONS' in source
    assert '"guest"' in source
    assert '"smm"' in source


def test_shared_export_and_timezone_services_parse():
    for path in ('app/services/export.py', 'app/services/timezone_policy.py'):
        ast.parse(Path(path).read_text(encoding='utf-8'))
