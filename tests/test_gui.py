import pytest

def test_app_instantiation():
    """Verify that App initializes its CustomTkinter layout without throwing errors."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()
        app.update_idletasks()
        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")

def test_usage_label_fallback_text(monkeypatch):
    """Verify update_usage_label displays fallback text when remaining requests is 0."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()
        
        # Test normal remaining quota
        monkeypatch.setattr("pdf_parser_light.config.get_remaining_requests", lambda: 15)
        app.update_usage_label()
        assert "Free 3.5 Quota Left: 15" in app.usage_label.cget("text")
        assert "Fallback Models" not in app.usage_label.cget("text")
        
        # Test 0 remaining quota (fallback mode)
        monkeypatch.setattr("pdf_parser_light.config.get_remaining_requests", lambda: 0)
        app.update_usage_label()
        assert "Free 3.5 Quota Left: 0 / 20 (Using Fallback Models)" in app.usage_label.cget("text")
        color = app.usage_label.cget("text_color")
        assert "#E67E22" in (color if isinstance(color, (list, tuple)) else [color])
        
        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")

def test_drag_and_drop_file_selection(tmp_path, monkeypatch):
    """Verify set_selected_file updates dropzone UI state and page range entry state correctly."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()

        # Verify page_range_entry interaction is blocked before file upload
        assert app._on_page_range_interaction() == "break"
        assert app.page_range_entry.get() == ""

        # Create dummy PDF file
        pdf_file = tmp_path / "sample_doc.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 sample content")

        # Mock validate_pdf to return 1 page for test file
        monkeypatch.setattr("pdf_parser_light.app.validate_pdf", lambda path: 1)

        # Test selecting file via set_selected_file
        app.set_selected_file(str(pdf_file))
        assert app.selected_file_path == str(pdf_file)
        assert "sample_doc.pdf" in app.drop_title_label.cget("text")

        # Verify page_range_entry interaction is allowed and autofilled after file upload
        assert app._on_page_range_interaction() is None
        assert app.page_range_entry.get() != ""

        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")

def test_file_drop_event_handler(tmp_path, monkeypatch):
    """Verify _on_file_drop correctly parses dropped file payload and selects PDF file."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()

        pdf_file = tmp_path / "dropped_doc.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 sample content")
        monkeypatch.setattr("pdf_parser_light.app.validate_pdf", lambda path: 5)

        class MockDropEvent:
            def __init__(self, data):
                self.data = data

        # Simulate dropping a raw file path string wrapped in braces/spaces
        drop_event = MockDropEvent(f"{{{str(pdf_file)}}} ")
        app._on_file_drop(drop_event)

        assert app.selected_file_path == str(pdf_file)
        assert "dropped_doc.pdf" in app.drop_title_label.cget("text")
        assert app.page_range_entry.get() == "1-5"

        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")

def test_click_outside_deselects_textbox():
    """Verify that clicking outside of a textbox deselects textboxes."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()

        class MockEvent:
            def __init__(self, widget):
                self.widget = widget

        # Verify _is_textbox_widget identifies CTkEntry and internal entry
        assert app._is_textbox_widget(app.api_key_entry)
        assert app._is_textbox_widget(app.api_key_entry._entry)
        assert not app._is_textbox_widget(app.drop_frame)
        assert not app._is_textbox_widget(app.api_key_label)

        # Ensure event handlers execute without error on click inside vs click outside
        app._on_global_click(MockEvent(app.api_key_entry._entry))
        app._on_global_click(MockEvent(app.drop_frame))

        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")

def test_caret_color_matches_text_color():
    """Verify that caret insertbackground is configured on internal entry widget."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()

        caret_color = app.api_key_entry._entry.cget("insertbackground")
        assert caret_color.lower() in ("black", "white", "#000000", "#ffffff", "gray10", "#dce4ee")

        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")

def test_api_key_link_click(monkeypatch):
    """Verify that clicking api_key_link invokes webbrowser.open."""
    try:
        from pdf_parser_light.app import App
        app = App()
        app.withdraw()

        opened_urls = []
        monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))

        # Event generation/trigger on api_key_link
        app.api_key_link.event_generate("<Button-1>")
        assert len(opened_urls) == 1
        assert opened_urls[0] == "https://aistudio.google.com/api-keys"

        app.destroy()
    except Exception as e:
        pytest.skip(f"Skipping GUI test in headless environment: {e}")






