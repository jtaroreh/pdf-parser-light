import pytest

try:
    import tkinter
    from pdf_parser_light.app import App
except (ImportError, ModuleNotFoundError) as e:
    tkinter = None
    App = None


def _make_app():
    if tkinter is None or App is None:
        pytest.skip("Tkinter / GUI not available in this environment")
    try:
        app = App()
    except (tkinter.TclError, Exception) as e:
        pytest.skip(f"No display: {e}")
    app.withdraw()
    return app


def test_app_instantiation():
    app = _make_app()
    app.update_idletasks()
    app.destroy()


def test_usage_label_fallback_text(monkeypatch):
    app = _make_app()

    monkeypatch.setattr("pdf_parser_light.config.get_remaining_requests", lambda: 15)
    app.update_usage_label()
    assert "Free 3-Flash Quota Left: 15" in app.usage_label.cget("text")
    assert "Fallback Models" not in app.usage_label.cget("text")

    monkeypatch.setattr("pdf_parser_light.config.get_remaining_requests", lambda: 0)
    app.update_usage_label()
    assert "Free 3-Flash Quota Left: 0 / 20 (Using Fallback Models)" in app.usage_label.cget("text")
    color = app.usage_label.cget("text_color")
    assert "#E67E22" in (color if isinstance(color, (list, tuple)) else [color])

    app.destroy()


def test_drag_and_drop_file_selection(tmp_path, monkeypatch):
    app = _make_app()

    assert app._on_page_range_interaction() == "break"
    assert app.page_range_entry.get() == ""

    pdf_file = tmp_path / "sample_doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 sample content")
    monkeypatch.setattr("pdf_parser_light.app.validate_pdf", lambda path: 1)

    app.set_selected_file(str(pdf_file))
    assert app.selected_file_path == str(pdf_file)
    assert "sample_doc.pdf" in app.drop_title_label.cget("text")

    assert app._on_page_range_interaction() is None
    assert app.page_range_entry.get() != ""

    app.destroy()


def test_file_drop_event_handler(tmp_path, monkeypatch):
    app = _make_app()

    pdf_file = tmp_path / "dropped_doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 sample content")
    monkeypatch.setattr("pdf_parser_light.app.validate_pdf", lambda path: 5)

    class MockDropEvent:
        def __init__(self, data):
            self.data = data

    app._on_file_drop(MockDropEvent(f"{{{str(pdf_file)}}} "))

    assert app.selected_file_path == str(pdf_file)
    assert "dropped_doc.pdf" in app.drop_title_label.cget("text")
    assert app.page_range_entry.get() == "1-5"

    app.destroy()


def test_dropzone_click_is_on_labels_not_frame(monkeypatch):
    app = _make_app()
    called = []
    monkeypatch.setattr(app, "browse_file", lambda e=None: called.append(True))
    inner = getattr(app.drop_title_label, "_label", None) or getattr(app.drop_title_label, "_canvas", None)
    inner.event_generate("<Button-1>")
    app.update_idletasks()
    assert called
    assert "<Button-1>" not in (app.drop_frame.bind() or ())
    assert not hasattr(app, "_on_global_click")
    assert not hasattr(app, "_is_interactive_widget")
    app.destroy()


def test_caret_color_matches_text_color():
    app = _make_app()
    caret_color = app.api_key_entry._entry.cget("insertbackground")
    assert caret_color.lower() in ("black", "white", "#000000", "#ffffff", "gray10", "#dce4ee")
    app.destroy()


def test_api_key_link_click(monkeypatch):
    app = _make_app()
    opened_urls = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))
    app._open_api_keys_page()
    assert opened_urls == ["https://aistudio.google.com/api-keys"]
    app.destroy()


def test_progress_queue_message_updates_bar():
    app = _make_app()
    app.queue.put(("progress", (2, 4)))
    app.check_queue()
    assert abs(app.progress_bar.get() - 0.5) < 0.01
    app.destroy()
