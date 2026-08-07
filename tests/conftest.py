import pytest


@pytest.fixture(autouse=True)
def _clear_active_uploads():
    """Isolate module-level upload registry between tests."""
    import pdf_parser_light.parse as parse

    with parse._active_uploads_lock:
        parse._active_uploads.clear()
    yield
    with parse._active_uploads_lock:
        parse._active_uploads.clear()
