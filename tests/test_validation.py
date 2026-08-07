import os
import pytest
from unittest.mock import MagicMock, patch

from pdf_parser_light.parse import validate_pdf

def test_validate_pdf_file_not_found():
    with pytest.raises(FileNotFoundError):
        validate_pdf("/non/existent/path/doc.pdf")

def test_validate_pdf_not_a_file(tmp_path):
    dir_path = str(tmp_path / "somedir")
    os.makedirs(dir_path, exist_ok=True)
    with pytest.raises(ValueError, match="Path is not a regular file"):
        validate_pdf(dir_path)

def test_validate_pdf_wrong_extension(tmp_path):
    file_path = str(tmp_path / "document.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("hello")
    with pytest.raises(ValueError, match="must have a .pdf extension"):
        validate_pdf(file_path)

def test_validate_pdf_empty_file(tmp_path):
    file_path = str(tmp_path / "empty.pdf")
    with open(file_path, "wb"):
        pass
    with pytest.raises(ValueError, match="PDF file is empty"):
        validate_pdf(file_path)

def test_validate_pdf_invalid_header(tmp_path):
    file_path = str(tmp_path / "invalid.pdf")
    with open(file_path, "wb") as f:
        f.write(b"NOT A PDF HEADER")
    with pytest.raises(ValueError, match="not a valid PDF document"):
        validate_pdf(file_path)

def test_validate_pdf_exceeds_max_size(tmp_path):
    file_path = str(tmp_path / "large.pdf")
    with open(file_path, "wb") as f:
        f.write(b"%PDF" + b"0" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        validate_pdf(file_path, max_size_mb=1)

def test_validate_pdf_encrypted(tmp_path):
    file_path = str(tmp_path / "encrypted.pdf")
    with open(file_path, "wb") as f:
        f.write(b"%PDF-1.4 header contents...")

    mock_reader = MagicMock()
    mock_reader.is_encrypted = True

    with patch("pypdf.PdfReader", return_value=mock_reader):
        with pytest.raises(ValueError, match="encrypted/password-protected"):
            validate_pdf(file_path)

def test_validate_pdf_exceeds_max_pages(tmp_path):
    file_path = str(tmp_path / "many_pages.pdf")
    with open(file_path, "wb") as f:
        f.write(b"%PDF-1.4 header contents...")

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [MagicMock()] * 10

    with patch("pypdf.PdfReader", return_value=mock_reader):
        with pytest.raises(ValueError, match="exceeds the maximum allowed limit"):
            validate_pdf(file_path, max_pages=5)

def test_validate_pdf_success(tmp_path):
    file_path = str(tmp_path / "valid.pdf")
    with open(file_path, "wb") as f:
        f.write(b"%PDF-1.4 header contents...")

    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [MagicMock()] * 3

    with patch("pypdf.PdfReader", return_value=mock_reader):
        pages = validate_pdf(file_path)
        assert pages == 3

def test_cleanup_active_uploads():
    from pdf_parser_light.parse import _active_uploads, _register_upload, cleanup_active_uploads
    assert not _active_uploads
    mock_file = MagicMock()
    mock_file.name = "files/test_upload_123"
    _register_upload(mock_file)

    mock_client = MagicMock()
    cleanup_active_uploads(client=mock_client)
    mock_client.files.delete.assert_called_once_with(name="files/test_upload_123")

def test_cleanup_active_uploads_with_api_key():
    from pdf_parser_light.parse import _active_uploads, _register_upload, cleanup_active_uploads
    assert not _active_uploads
    mock_file = MagicMock()
    mock_file.name = "files/test_upload_456"
    _register_upload(mock_file)

    mock_client = MagicMock()
    with patch("google.genai.Client", return_value=mock_client) as mock_genai_client:
        cleanup_active_uploads(client=None, api_key="dummy_key")
        mock_genai_client.assert_called_once_with(api_key="dummy_key")
        mock_client.files.delete.assert_called_once_with(name="files/test_upload_456")

