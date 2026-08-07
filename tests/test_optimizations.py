import pytest
from unittest.mock import MagicMock, patch

from pdf_parser_light.parse import (
    _parse_page_range,
    _calculate_backoff,
    _read_completed_chunks_from_file,
    _generate_transcription,
    _build_chunk_groups,
    _count_chunk_requests,
    _strip_overlapping_page,
    _strip_first_page_section,
    _stitch_chunk_results,
    _is_daily_quota_error,
    _build_chunk_model_chain,
    _FREE_TIER_TRACKED_MODEL,
    _process_single_file
)
from pdf_parser_light.cli import main

def test_build_chunk_groups_with_overlap():
    groups = _build_chunk_groups(list(range(45)), chunk_size=20, overlap=1)
    assert groups[0] == list(range(0, 20))
    assert groups[1][0] == 19  # 1-page overlap
    assert groups[1][-1] == 38
    assert groups[-1][-1] == 44
    assert _count_chunk_requests(120, chunk_size=20, overlap=1) == len(
        _build_chunk_groups(list(range(120)), chunk_size=20, overlap=1)
    )

def test_build_chunk_groups_no_overlap():
    groups = _build_chunk_groups(list(range(45)), chunk_size=20, overlap=0)
    assert groups[0] == list(range(0, 20))
    assert groups[1] == list(range(20, 40))
    assert groups[2] == list(range(40, 45))



def test_strip_overlapping_page_and_stitch():
    chunk2 = "## Page 20\noverlap twenty should drop.\n\n## Page 21\nstart of twenty-one."
    stripped, ok = _strip_overlapping_page(chunk2, 20)
    assert ok
    assert stripped.startswith("## Page 21")
    stitched = _stitch_chunk_results(
        ["## Page 19\na\n\n## Page 20\nb", "## Page 20\nb-dup\n\n## Page 21\nc"],
        [[18, 19], [19, 20]],
    )
    assert "## Page 20\nb-dup" not in stitched
    assert "## Page 20\nb" in stitched
    assert "## Page 21\nc" in stitched


def test_stitch_fallback_when_overlap_header_missing():
    """If absolute overlap page header is missing, strip the first ## Page section."""
    # Chunk 2 wrongly restarts at 66 instead of overlap page 80, but also has in-range 81.
    # Extract drops 66/67; overlap 80 absent → keep 81 (do not strip the real continuation).
    chunk1 = "## Page 79\nx\n\n## Page 80\nend of eighty."
    chunk2 = (
        "## Page 66\nchapter 5 dup should drop\n\n"
        "## Page 67\nmore dup\n\n"
        "## Page 81\nreal continuation"
    )
    stitched = _stitch_chunk_results([chunk1, chunk2], [[78, 79], [79, 80]])
    assert "## Page 66" not in stitched
    assert "## Page 80\nend of eighty." in stitched
    assert "## Page 81\nreal continuation" in stitched

    # Pure wrong-start with no in-range headers: extract returns original; fallback strips first section
    bad_only = "## Page 66\ndup\n\n## Page 67\ncont"
    _, ok = _strip_overlapping_page(bad_only, 80)
    assert not ok
    fallback, fb_ok = _strip_first_page_section(bad_only)
    assert fb_ok
    assert fallback.startswith("## Page 67")

    # Unfiltered wrong restart through stitch (no pages in expected range survive extract's
    # empty→original behavior): first header 66 <= overlap 80 → fallback strips page 66.
    stitched_bad = _stitch_chunk_results(
        ["## Page 80\nkeep", bad_only],
        [[79], [79, 80]],
    )
    assert "## Page 66" not in stitched_bad
    assert "## Page 67\ncont" in stitched_bad
    assert "## Page 80\nkeep" in stitched_bad





def test_build_chunk_model_chain_skips_when_remaining_zero():
    assert _FREE_TIER_TRACKED_MODEL in _build_chunk_model_chain(3)
    chain = _build_chunk_model_chain(0)
    assert _FREE_TIER_TRACKED_MODEL not in chain
    assert chain[0] == "gemini-3.5-flash-lite"


def test_is_daily_quota_error_patterns():
    assert _is_daily_quota_error(
        "429 RESOURCE_EXHAUSTED Quota exceeded for metric GenerateRequestsPerDayPerProjectPerModel free_tier"
    )
    assert _is_daily_quota_error("You exceeded your current quota ... generativelanguage.googleapis.com/generate_content_free_tier_requests")
    assert _is_daily_quota_error("limit: 20 per day")
    assert not _is_daily_quota_error("429 RESOURCE_EXHAUSTED rate limit exceeded for rpm")






def test_parse_page_range_defaults():
    assert _parse_page_range(None, 100) == (0, 100)
    assert _parse_page_range("", 100) == (0, 100)
    assert _parse_page_range("   ", 100) == (0, 100)

def test_parse_page_range_valid_ranges():
    assert _parse_page_range("40-120", 200) == (39, 120)
    assert _parse_page_range("1-50", 100) == (0, 50)
    assert _parse_page_range("5", 100) == (4, 5)
    assert _parse_page_range("10-", 50) == (9, 50)
    assert _parse_page_range("-30", 50) == (0, 30)

def test_parse_page_range_clamping():
    assert _parse_page_range("1-500", 50) == (0, 50)
    assert _parse_page_range("0-10", 50) == (0, 10)

def test_parse_page_range_invalid():
    with pytest.raises(ValueError, match="cannot be greater than end page"):
        _parse_page_range("50-10", 100)

    with pytest.raises(ValueError, match="Invalid page range format"):
        _parse_page_range("abc", 100)

def test_calculate_backoff():
    delay1 = _calculate_backoff(0, is_429=False)
    assert 2.0 <= delay1 <= 5.0

    delay_429 = _calculate_backoff(0, is_429=True)
    assert 15.0 <= delay_429 <= 18.0

def test_read_completed_chunks_from_file(tmp_path):
    out_file = tmp_path / "output.md"
    
    # Non-existent file
    assert _read_completed_chunks_from_file(str(out_file)) == []

    # File with 2 completed chunks and a warning footer
    content = (
        "Chunk 1 text\n\n---\n\nChunk 2 text"
        "\n\n---\n\n> **[WARNING] Processing failed on chunk 3/5: Quota limit hit.**"
    )
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(content)

    chunks = _read_completed_chunks_from_file(str(out_file))
    assert len(chunks) == 2
    assert chunks[0] == "Chunk 1 text"
    assert chunks[1] == "Chunk 2 text"

def test_skip_count_tokens():
    mock_client = MagicMock()
    mock_pdf = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Transcribed text"
    mock_client.models.generate_content.return_value = mock_response

    log_msgs = []
    text, used_m = _generate_transcription(
        client=mock_client,
        pdf_file=mock_pdf,
        log=lambda msg: log_msgs.append(msg),
        model="gemini-3.5-flash",
        count_tokens=False
    )

    assert text == "Transcribed text"
    assert used_m == "gemini-3.5-flash"
    mock_client.models.count_tokens.assert_not_called()
    mock_client.models.generate_content.assert_called_once()

def test_cli_page_range_and_resume_args(capsys):
    import sys
    test_args = ["pdf-parser-light", "--usage", "-p", "10-20", "--resume"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

def test_model_fallback_chain():
    """503 / high-demand should fall back to the next model immediately (no same-model retries)."""
    mock_client = MagicMock()
    mock_pdf = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Fallback success text"

    mock_client.models.generate_content.side_effect = [
        Exception("503 Service Unavailable"),
        mock_response,
    ]

    log_msgs = []
    with patch("pdf_parser_light.parse.time.sleep") as mock_sleep:
        text, used_m = _generate_transcription(
            client=mock_client,
            pdf_file=mock_pdf,
            log=lambda msg: log_msgs.append(msg),
            model_chain=["gemini-3.6-flash", "gemini-3.5-flash"],
            count_tokens=False,
        )

    assert text == "Fallback success text"
    assert used_m == "gemini-3.5-flash"
    assert any("Automatically switching to fallback model: gemini-3.5-flash" in m for m in log_msgs)
    mock_sleep.assert_not_called()
    assert mock_client.models.generate_content.call_count == 2
    assert mock_client.models.generate_content.call_args_list[0].kwargs["model"] == "gemini-3.6-flash"
    assert mock_client.models.generate_content.call_args_list[1].kwargs["model"] == "gemini-3.5-flash"


def test_model_fallback_after_429_retries():
    """429 should retry the same model, then fall back after retries are exhausted."""
    mock_client = MagicMock()
    mock_pdf = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Fallback after retries"

    mock_client.models.generate_content.side_effect = [
        Exception("429 RESOURCE_EXHAUSTED"),
        Exception("429 RESOURCE_EXHAUSTED"),
        Exception("429 RESOURCE_EXHAUSTED"),
        mock_response,
    ]

    log_msgs = []
    with patch("pdf_parser_light.parse.time.sleep") as mock_sleep:
        text, used_m = _generate_transcription(
            client=mock_client,
            pdf_file=mock_pdf,
            log=lambda msg: log_msgs.append(msg),
            model_chain=["gemini-3.6-flash", "gemini-3.5-flash"],
            count_tokens=False,
        )

    assert text == "Fallback after retries"
    assert used_m == "gemini-3.5-flash"
    assert mock_sleep.call_count == 2
    assert any("Rate limit hit (429)" in m for m in log_msgs)
    assert any("Automatically switching to fallback model: gemini-3.5-flash" in m for m in log_msgs)
    assert mock_client.models.generate_content.call_count == 4
    models_called = [c.kwargs["model"] for c in mock_client.models.generate_content.call_args_list]
    assert models_called == [
        "gemini-3.6-flash",
        "gemini-3.6-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]


def test_daily_quota_falls_back_immediately_without_sleep():
    """Daily/free-tier 429 must skip same-model retries and fall back immediately."""
    mock_client = MagicMock()
    mock_pdf = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Lite success"

    daily_err = Exception(
        "429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
        "'GenerateRequestsPerDayPerProjectPerModel' and limit 'GenerateRequestsPerDayPerProjectPerModel-FreeTier' "
        "of service 'generativelanguage.googleapis.com' for consumer 'projects/123'."
    )
    mock_client.models.generate_content.side_effect = [daily_err, mock_response]

    log_msgs = []
    with patch("pdf_parser_light.parse.time.sleep") as mock_sleep:
        with patch("pdf_parser_light.config.increment_usage"):
            with patch("pdf_parser_light.config.get_usage", return_value=20):
                with patch("pdf_parser_light.config.MAX_FREE_REQUESTS", 20):
                    text, used_m = _generate_transcription(
                        client=mock_client,
                        pdf_file=mock_pdf,
                        log=lambda msg: log_msgs.append(msg),
                        model_chain=["gemini-3.5-flash", "gemini-3.1-flash-lite"],
                        count_tokens=False,
                    )

    assert text == "Lite success"
    assert used_m == "gemini-3.1-flash-lite"
    mock_sleep.assert_not_called()
    assert mock_client.models.generate_content.call_count == 2
    assert any("daily/free-tier quota exhausted" in m for m in log_msgs)
    models_called = [c.kwargs["model"] for c in mock_client.models.generate_content.call_args_list]
    assert models_called == ["gemini-3.5-flash", "gemini-3.1-flash-lite"]


def test_model_fallback_chain_exhausted():
    """When every model fails, raise the last error."""
    mock_client = MagicMock()
    mock_pdf = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("503 Service Unavailable")

    log_msgs = []
    with patch("pdf_parser_light.parse.time.sleep"):
        with pytest.raises(Exception, match="503 Service Unavailable"):
            _generate_transcription(
                client=mock_client,
                pdf_file=mock_pdf,
                log=lambda msg: log_msgs.append(msg),
                model_chain=["gemini-3.6-flash", "gemini-3.5-flash"],
                count_tokens=False,
            )

    assert any("Automatically switching to fallback model: gemini-3.5-flash" in m for m in log_msgs)
    assert mock_client.models.generate_content.call_count == 4
    models_called = [c.kwargs["model"] for c in mock_client.models.generate_content.call_args_list]
    assert models_called == [
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash",
    ]


def test_single_file_fallback_when_quota_zero(monkeypatch):
    """When remaining quota is 0, _process_single_file filters out gemini-3.5-flash and logs fallback warning."""
    mock_client = MagicMock()
    uploaded = MagicMock()
    uploaded.name = "files/uploaded_pdf"
    mock_client.files.upload.return_value = uploaded

    log_msgs = []
    monkeypatch.setattr("pdf_parser_light.config.get_remaining_requests", lambda: 0)

    with patch("pdf_parser_light.parse._generate_transcription") as mock_gen, \
         patch("shutil.rmtree"), \
         patch("shutil.copy2"):
        mock_gen.return_value = ("Parsed content", "gemini-3.5-flash-lite")
        res = _process_single_file(
            client=mock_client,
            file_path="dummy.pdf",
            log=lambda m: log_msgs.append(m)
        )
        assert res == "Parsed content"
        passed_chain = mock_gen.call_args.kwargs["model_chain"]
        assert "gemini-3.5-flash" not in passed_chain
        assert any("Using fallback models" in msg for msg in log_msgs)

def test_acquire_instance_lock_returns_none_on_os_error(monkeypatch):
    """Verify _acquire_instance_lock returns None when fcntl.flock raises OSError."""
    import sys
    from pdf_parser_light.app import _acquire_instance_lock
    mock_fcntl = MagicMock()
    mock_fcntl.flock.side_effect = OSError("Already locked")
    monkeypatch.setitem(sys.modules, "fcntl", mock_fcntl)
    monkeypatch.setattr("sys.platform", "darwin")
    with patch("builtins.open", MagicMock()):
        assert _acquire_instance_lock() is None

def test_reset_usage(tmp_path, monkeypatch):
    """Verify reset_usage clears tracked daily requests back to 0."""
    test_usage_file = tmp_path / "usage.json"
    monkeypatch.setattr("pdf_parser_light.config.USAGE_FILE", str(test_usage_file))
    monkeypatch.setattr("pdf_parser_light.config.CONFIG_DIR", str(tmp_path))
    
    from pdf_parser_light.config import increment_usage, get_usage, reset_usage, get_remaining_requests
    increment_usage(10)
    assert get_usage() == 10
    
    reset_usage()
    assert get_usage() == 0
    assert get_remaining_requests() == 20

def test_cli_reset_quota_arg(capsys):
    import sys
    test_args = ["pdf-parser-light", "--reset-quota"]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Daily free quota tracker reset!" in captured.out




