import os
import sys
import pytest
from unittest.mock import patch

from pdf_parser_light.cli import main

def test_cli_usage_flag(capsys):
    test_args = ["pdf-parser-light", "--usage"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Free Requests Left Today:" in captured.out

def test_cli_missing_api_key(capsys, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    test_args = ["pdf-parser-light", "some_file.pdf"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: No Gemini API Key provided." in captured.err

def test_cli_non_existent_input(capsys):
    test_args = ["pdf-parser-light", "--api-key", "test_key", "/non/existent/path/file.pdf"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Input path not found:" in captured.err

def test_app_launcher_usage_flag(capsys):
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    import app_launcher
    test_args = ["app_launcher", "--usage"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            app_launcher.main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Free Requests Left Today:" in captured.out



