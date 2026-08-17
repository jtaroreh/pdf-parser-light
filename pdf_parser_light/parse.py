from google import genai
import os
import re
import threading
import time
import random
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor
from . import config

_CHUNK_MODEL_CHAIN = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
_FREE_TIER_TRACKED_MODEL = "gemini-3.5-flash"

CHUNK_SIZE = 20
CHUNK_OVERLAP = 0

def _is_daily_quota_error(err_str):
    """True when an API error indicates daily/free-tier quota exhaustion (not transient RPM)."""
    err = (err_str or "").lower()
    if not err:
        return False
    return (
        "per day" in err
        or "daily" in err
        or "generaterequestsperday" in err
        or "free_tier" in err
        or "free tier" in err
        or ("quotaid" in err and "day" in err)
    )

def _build_chunk_model_chain(remaining_free=None):
    """Model chain for multi-chunk runs; skip free-tier tracked model when local remaining is 0."""
    chain = list(_CHUNK_MODEL_CHAIN)
    if remaining_free is not None and remaining_free <= 0:
        chain = [m for m in chain if m != _FREE_TIER_TRACKED_MODEL]
    return chain



def _build_chunk_groups(page_indices, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Split page indices into overlapping groups (overlap helps continuity across chunk boundaries)."""
    n = len(page_indices)
    if n == 0:
        return []
    if n <= chunk_size:
        return [list(page_indices)]
    stride = max(1, chunk_size - max(0, overlap))
    groups = []
    start = 0
    while start < n:
        end = min(start + chunk_size, n)
        groups.append(list(page_indices[start:end]))
        if end >= n:
            break
        start += stride
    return groups

def _count_chunk_requests(page_count, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if page_count <= 0:
        return 0
    if page_count <= chunk_size:
        return 1
    return len(_build_chunk_groups(list(range(page_count)), chunk_size=chunk_size, overlap=overlap))

def _strip_overlapping_page(chunk_text, page_num):
    """Remove the ## Page N section used for overlap (kept from previous chunk).

    Returns (stripped_text, did_strip).
    """
    if not chunk_text:
        return chunk_text, False
    pattern = re.compile(
        rf"(?ms)^## Page\s+{re.escape(str(page_num))}\s*\n.*?(?=^## Page\s+|\Z)"
    )
    stripped, n = pattern.subn("", chunk_text, count=1)
    if n == 0:
        return chunk_text, False
    return stripped.lstrip("\n"), True

_FIRST_PAGE_SECTION_RE = re.compile(r"(?ms)^## Page\s+\S+\s*\n.*?(?=^## Page\s+|\Z)")

def _strip_first_page_section(chunk_text):
    """Remove the first ## Page section regardless of page number (overlap fallback)."""
    if not chunk_text:
        return chunk_text, False
    stripped, n = _FIRST_PAGE_SECTION_RE.subn("", chunk_text, count=1)
    if n == 0:
        return chunk_text, False
    return stripped.lstrip("\n"), True

def _stitch_chunk_results(results, chunk_groups):
    """Join chunk texts, dropping overlapping first-page sections from chunks after the first."""
    if not results:
        return ""
    cleaned = []
    for i, text in enumerate(results):
        if i > 0 and i < len(chunk_groups) and chunk_groups[i] and chunk_groups[i - 1]:
            prev_last = chunk_groups[i - 1][-1]
            cur_first = chunk_groups[i][0]
            if prev_last == cur_first:
                expected_page = cur_first + 1
                text, stripped = _strip_overlapping_page(text, expected_page)
                if not stripped:
                    text, _ = _strip_first_page_section(text)
        cleaned.append(text)
    return "\n\n---\n\n".join(cleaned)

class PartialParseError(Exception):
    """Raised when parsing fails mid-chunk, carrying partial transcription results."""
    def __init__(self, partial_text, original_error):
        super().__init__(str(original_error))
        self.partial_text = partial_text
        self.original_error = original_error

class QuotaExceededError(Exception):
    """Raised when required chunk requests exceed remaining local daily quota."""
    pass

class CancellationError(Exception):
    """Raised when operation is cancelled by the user."""
    pass

_active_uploads = set()
_active_uploads_lock = threading.Lock()

def _register_upload(file_obj):
    with _active_uploads_lock:
        if file_obj and hasattr(file_obj, "name"):
            _active_uploads.add(file_obj.name)

def _unregister_upload(file_obj):
    with _active_uploads_lock:
        if file_obj and hasattr(file_obj, "name"):
            _active_uploads.discard(file_obj.name)

def cleanup_active_uploads(client=None, api_key=None):
    """Clean up active uploaded files from Gemini storage."""
    with _active_uploads_lock:
        names = list(_active_uploads)
        _active_uploads.clear()
    if not names:
        return
    if client is None and api_key:
        try:
            client = genai.Client(api_key=api_key)
        except Exception:
            client = None
    if client is None:
        return
    for name in names:
        try:
            client.files.delete(name=name)
        except Exception:
            pass

def _check_cancelled(cancel_event):
    if cancel_event and cancel_event.is_set():
        raise CancellationError("Operation cancelled by user.")

def _calculate_backoff(attempt, is_429=False, base=2, max_delay=60):
    """Calculates exponential backoff delay with random full jitter."""
    if is_429:
        base_delay = min(max_delay, 15 * (1.5 ** attempt))
    else:
        base_delay = min(max_delay, base ** (attempt + 1))
    jitter = random.uniform(0.5, 2.0)
    return base_delay + jitter

def _upload_file_with_retry(client, file_path, log_msg, log, cancel_event, max_retries=3):
    """Uploads a file to Gemini File API with automatic retries and exponential backoff on 429 errors."""
    for attempt in range(max_retries):
        _check_cancelled(cancel_event)
        try:
            log(log_msg)
            pdf_file = client.files.upload(file=file_path)
            _register_upload(pdf_file)
            return pdf_file
        except Exception as upload_err:
            if attempt == max_retries - 1:
                raise upload_err
            err_str = str(upload_err).lower()
            is_429 = "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str
            backoff = _calculate_backoff(attempt, is_429=is_429)
            if is_429:
                log(f"Rate limit hit (429) during upload. Waiting {backoff:.1f}s before retrying (Attempt {attempt + 2}/{max_retries})...")
            else:
                log(f"Upload failed: {upload_err}. Retrying in {backoff:.1f}s (Attempt {attempt + 2}/{max_retries})...")
            time.sleep(backoff)

def _cleanup_pending_future(pending_f, client):
    """Safely cancels and cleans up temporary resources from a pending chunk upload future."""
    if pending_f is None:
        return
    try:
        if not pending_f.cancelled():
            res = pending_f.result(timeout=10)
            if res:
                t_dir, p_file = res
                shutil.rmtree(t_dir, ignore_errors=True)
                if p_file:
                    _unregister_upload(p_file)
                    try:
                        client.files.delete(name=p_file.name)
                    except Exception:
                        pass
    except Exception:
        pass

def _parse_page_range(page_range_str, total_pages):
    """
    Parses a page range string like '40-120', '10-', '-50', or '5' into zero-based (start_idx, end_idx) range (end_idx exclusive).
    Returns (start_idx, end_idx).
    """
    if not page_range_str or not str(page_range_str).strip():
        return 0, total_pages

    s = str(page_range_str).strip()
    try:
        if "-" in s:
            parts = s.split("-", 1)
            start_str, end_str = parts[0].strip(), parts[1].strip()
            start = int(start_str) if start_str else 1
            end = int(end_str) if end_str else total_pages
        else:
            start = end = int(s)
    except ValueError:
        raise ValueError(
            f"Invalid page range format: '{page_range_str}'.\n\n"
            f"Please enter a valid range using one of these formats:\n"
            f"  • Range of pages:  1-50  or  40-120\n"
            f"  • Single page:     10\n"
            f"  • Open-ended:      5-  (page 5 to end) or -50 (start to page 50)"
        )

    if start < 1:
        start = 1
    if end > total_pages:
        end = total_pages
    if start > end:
        raise ValueError(
            f"Invalid page range: '{page_range_str}'. Start page ({start}) cannot be greater than end page ({end}).\n\n"
            f"Supported format examples:\n"
            f"  • 1-50  (pages 1 to 50)\n"
            f"  • 40-120  (pages 40 to 120)\n"
            f"  • 10  (single page 10)"
        )

    return start - 1, end

def _read_completed_chunks_from_file(output_path):
    """
    Parses existing markdown file at output_path to recover previously completed chunk transcriptions.
    Returns list of chunk text strings.
    """
    if not output_path or not os.path.exists(output_path):
        return []
    
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if not content.strip():
            return []
            
        parts = content.split("\n\n---\n\n")
        valid_chunks = []
        for p in parts:
            p_strip = p.strip()
            if p_strip.startswith("> **[WARNING] Processing failed on chunk"):
                break
            if p_strip:
                valid_chunks.append(p)
        return valid_chunks
    except Exception:
        return []

def validate_pdf(file_path, max_size_mb=200, max_pages=500):
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not os.path.isfile(file_path):
        raise ValueError(f"Path is not a regular file: {file_path}")

    if not file_path.lower().endswith(".pdf"):
        raise ValueError(f"File must have a .pdf extension: {os.path.basename(file_path)}")

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError(f"PDF file is empty (0 bytes): {os.path.basename(file_path)}")

    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise ValueError(f"PDF file size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed size ({max_size_mb} MB).")

    with open(file_path, "rb") as f:
        header = f.read(4)
        if header != b"%PDF":
            raise ValueError(f"File '{os.path.basename(file_path)}' is not a valid PDF document (header missing %PDF).")

    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        if getattr(reader, "is_encrypted", False):
            raise ValueError(f"PDF document is encrypted/password-protected: {os.path.basename(file_path)}")
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise ValueError(f"PDF has {page_count} pages, which exceeds the maximum allowed limit of {max_pages} pages.")
        return page_count
    except ImportError:
        return None
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not read PDF metadata: {e}")

def _prepare_and_upload_chunk(client, reader, chunk_num, total_chunks, page_indices, log, cancel_event):
    """
    Worker task: extracts specific page_indices from reader into a temporary PDF and uploads it to Gemini File API.
    Returns (temp_dir, pdf_file).
    """
    from pypdf import PdfWriter
    _check_cancelled(cancel_event)
    temp_dir = tempfile.mkdtemp()
    temp_file_path = os.path.join(temp_dir, f"chunk_{chunk_num}.pdf")
    writer = PdfWriter()
    for page_idx in page_indices:
        writer.add_page(reader.pages[page_idx])
    with open(temp_file_path, "wb") as f:
        writer.write(f)

    try:
        pdf_file = _upload_file_with_retry(
            client, 
            temp_file_path, 
            f"Uploading chunk {chunk_num}/{total_chunks} to Gemini...", 
            log, 
            cancel_event
        )
        return temp_dir, pdf_file
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

def parse_pdf(
    api_key, 
    file_path, 
    log_callback=None, 
    usage_callback=None, 
    custom_prompt=None, 
    ignore_quota=False, 
    cancel_event=None,
    page_range=None,
    resume=False,
    output_path=None
):
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg + "\n")

    _check_cancelled(cancel_event)

    total_pages = validate_pdf(file_path)

    try:
        from pypdf import PdfReader
    except ImportError:
        log("Warning: pypdf is not installed. PDF splitting will be disabled. Processing as a single file...")
        client = genai.Client(api_key=api_key, http_options={'timeout': 120000})
        return _process_single_file(client, file_path, log, usage_callback, custom_prompt, cancel_event=cancel_event)

    client = genai.Client(api_key=api_key, http_options={'timeout': 120000})

    try:
        reader = PdfReader(file_path)
        if total_pages is None:
            total_pages = len(reader.pages)
    except Exception as e:
        log(f"Error reading PDF page count: {e}. Processing as a single file...")
        return _process_single_file(client, file_path, log, usage_callback, custom_prompt, cancel_event=cancel_event)

    # Resolve active page range
    start_page_idx, end_page_idx = _parse_page_range(page_range, total_pages)
    target_page_indices = list(range(start_page_idx, end_page_idx))
    target_page_count = len(target_page_indices)

    if page_range:
        log(f"Page range selected: Pages {start_page_idx + 1} to {end_page_idx} ({target_page_count} pages of {total_pages} total).")

    left = config.get_remaining_requests()
    effective_chunk_size = CHUNK_SIZE

    if target_page_count <= effective_chunk_size:
        return _process_single_file(
            client, 
            file_path, 
            log, 
            usage_callback, 
            custom_prompt, 
            cancel_event=cancel_event,
            reader=reader,
            page_indices=target_page_indices
        )

    chunk_groups = _build_chunk_groups(
        target_page_indices, chunk_size=effective_chunk_size, overlap=CHUNK_OVERLAP
    )
    total_chunks = len(chunk_groups)
    model_hint = "lite-model" if left <= 0 else "3.5-Flash"
    log(
        f"PDF selection has {target_page_count} pages. Splitting into {total_chunks} chunks "
        f"({effective_chunk_size} pages, {CHUNK_OVERLAP}-page overlap; requires ~{total_chunks} "
        f"{model_hint} requests; {left}/{config.MAX_FREE_REQUESTS} left in free 3.5-flash daily quota)..."
    )
    
    if not ignore_quota and total_chunks > left:
        raise QuotaExceededError(
            f"Parsing requires {total_chunks} API requests, but only {left} requests remain in daily quota. "
            f"Use --force (CLI) or confirm quota bypass in GUI to proceed."
        )

    active_model_chain = _build_chunk_model_chain(remaining_free=left)
    if left <= 0 and _FREE_TIER_TRACKED_MODEL not in active_model_chain:
        log(
            f"Local free-tier quota for {_FREE_TIER_TRACKED_MODEL} is 0/{config.MAX_FREE_REQUESTS}; "
            f"skipping it and starting with {active_model_chain[0]}."
        )
    results = []
    start_chunk_idx = 0

    # Auto-resume support check (automatically detects existing partial progress)
    if output_path and os.path.exists(output_path):
        previous_chunks = _read_completed_chunks_from_file(output_path)
        if previous_chunks:
            completed_count = min(len(previous_chunks), total_chunks)
            results = previous_chunks[:completed_count]
            start_chunk_idx = completed_count
            log(f"Auto-resuming from partial output: {start_chunk_idx}/{total_chunks} chunks already completed.")

    if start_chunk_idx >= total_chunks:
        log("All requested chunks have already been processed according to partial output.")
        return _stitch_chunk_results(results, chunk_groups)

    # Pipeline Overlap Execution using a max_workers=1 ThreadPoolExecutor for pre-fetching chunk N+1
    executor = ThreadPoolExecutor(max_workers=1)
    future_upload = None

    # Helper to schedule chunk upload
    def schedule_upload(c_idx):
        if c_idx < total_chunks:
            c_num = c_idx + 1
            c_indices = chunk_groups[c_idx]
            log(f"Preparing chunk {c_num}/{total_chunks} (Pages {c_indices[0] + 1} to {c_indices[-1] + 1})...")
            return executor.submit(_prepare_and_upload_chunk, client, reader, c_num, total_chunks, c_indices, log, cancel_event)
        return None

    try:
        # Pre-fetch the first chunk that needs to be processed
        future_upload = schedule_upload(start_chunk_idx)

        for i in range(start_chunk_idx, total_chunks):
            _check_cancelled(cancel_event)
            chunk_num = i + 1

            # Wait for current chunk upload to finish
            temp_dir, pdf_file = future_upload.result()
            future_upload = None

            # Schedule next chunk (N+1) pre-fetch immediately while chunk N is transcribing
            next_future = schedule_upload(i + 1)

            try:
                _check_cancelled(cancel_event)
                c_indices = chunk_groups[i]
                chunk_text, used_model = _generate_transcription(
                    client, 
                    pdf_file, 
                    log, 
                    usage_callback, 
                    model_chain=active_model_chain, 
                    custom_prompt=custom_prompt, 
                    cancel_event=cancel_event,
                    count_tokens=False,
                )

                results.append(chunk_text)

                # If fallback occurred, adjust active_model_chain for remaining chunks
                if used_model in active_model_chain:
                    used_idx = active_model_chain.index(used_model)
                    if used_idx > 0:
                        active_model_chain = active_model_chain[used_idx:]
                        log(f"Active chunking model updated to: {used_model}")

                log(f"Successfully processed chunk {chunk_num}/{total_chunks} using {used_model}.")
                log(f"--- CHUNK_PROGRESS: {chunk_num}/{total_chunks} ---")
            except Exception as e:
                log(f"Failed to process chunk {chunk_num}/{total_chunks}: {e}")
                # Cancel pending next upload if present
                if next_future:
                    next_future.cancel()

                if results:
                    partial_text = _stitch_chunk_results(results, chunk_groups[:len(results)]) + (
                        f"\n\n---\n\n> **[WARNING] Processing failed on chunk {chunk_num}/{total_chunks}: {e}. "
                        f"Partial results from chunks 1 to {len(results)} are saved above.**"
                    )
                    raise PartialParseError(partial_text, e)
                raise e
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
                if pdf_file:
                    _unregister_upload(pdf_file)
                    try:
                        log(f"Cleaning up chunk {chunk_num} from Gemini storage...")
                        client.files.delete(name=pdf_file.name)
                    except Exception as cleanup_err:
                        log(f"Warning: Failed to delete chunk from Gemini API: {cleanup_err}")

            future_upload = next_future
            next_future = None

            # Pacing delay between chunk generations to keep RPM steady
            if i < total_chunks - 1:
                time.sleep(2)

        full_text = _stitch_chunk_results(results, chunk_groups)
        return full_text
    finally:
        _cleanup_pending_future(future_upload, client)
        _cleanup_pending_future(next_future, client)
        executor.shutdown(wait=False)

def _process_single_file(client, file_path, log, usage_callback=None, custom_prompt=None, cancel_event=None, reader=None, page_indices=None):
    _check_cancelled(cancel_event)
    temp_dir = tempfile.mkdtemp()
    temp_file_path = os.path.join(temp_dir, "input.pdf")
    pdf_file = None
    try:
        if reader and page_indices is not None and len(page_indices) < len(reader.pages):
            from pypdf import PdfWriter
            writer = PdfWriter()
            for idx in page_indices:
                writer.add_page(reader.pages[idx])
            with open(temp_file_path, "wb") as f:
                writer.write(f)
        else:
            shutil.copy2(file_path, temp_file_path)

        pdf_file = _upload_file_with_retry(
            client, 
            temp_file_path, 
            f"Uploading {os.path.basename(file_path)} to Gemini...", 
            log, 
            cancel_event
        )

        _check_cancelled(cancel_event)
        left = config.get_remaining_requests()
        chain = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        if left <= 0:
            log(f"Free 3.5-flash daily quota limit reached (0/{config.MAX_FREE_REQUESTS} left). Using fallback models...")
            chain = [m for m in chain if m != _FREE_TIER_TRACKED_MODEL]

        res_text, _ = _generate_transcription(
            client, 
            pdf_file, 
            log, 
            usage_callback, 
            model_chain=chain, 
            custom_prompt=custom_prompt, 
            cancel_event=cancel_event, 
            count_tokens=False,
        )
        return res_text
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if pdf_file:
            _unregister_upload(pdf_file)
            try:
                log("Cleaning up uploaded file from Gemini API storage...")
                client.files.delete(name=pdf_file.name)
            except Exception as cleanup_err:
                log(f"Warning: Failed to delete file {pdf_file.name} from Gemini API: {cleanup_err}")

def _generate_transcription(client, pdf_file, log, usage_callback=None, model=None, model_chain=None, custom_prompt=None, cancel_event=None, count_tokens=False):
    _check_cancelled(cancel_event)
    if custom_prompt:
        prompt_contents = [pdf_file, custom_prompt]
    else:
        prompt_contents = [
            pdf_file,
            "Transcribe this document into clean, readable markdown as is. Use LaTeX for equations in the main body text.\n"
            "IMPORTANT: You must transcribe every single page in the document, including references, bibliographies, indexes, and appendices. Do not skip or summarize anything.\n"
            "Rules for Tables:\n"
            "1. LaTeX math (like $...$) often fails to render inside table cells. "
            "Therefore, DO NOT use LaTeX notation ($) inside tables. Instead, use standard Unicode symbols "
            "directly (e.g., use 'cm²', 'nΩ', 'µΩ·cm²', '°', '·', '10⁻⁴') so they render cleanly as text.\n"
            "2. ALWAYS output ALL tables using HTML <table> tags (using <tr>, <td>, <th>, and appropriate 'colspan' / 'rowspan' attributes for spanned cells). "
            "DO NOT use standard markdown table syntax (with pipes `|`). This guarantees that all tables render with perfect alignment and readability.\n"
            "Rules for Figures/Images:\n"
            "1. For every figure, diagram, photo, or chart in the PDF, insert an image placeholder at the position it appears in the text "
            "(e.g., `![Figure X: Caption text](figure_x_placeholder.png)`).\n"
            "2. Directly below the placeholder, include a detailed visual description in a blockquote (starting with `> **Figure X Visual Description:** `). "
            "Describe the visual layout, schematics, graphs, axes, labels, data points, or diagrams in detail so the reader understands the exact visual contents of the figure."
        ]

    if count_tokens:
        try:
            token_info = client.models.count_tokens(model="gemini-3.5-flash", contents=prompt_contents)
            log(f"Token count for payload: {token_info.total_tokens}")
        except Exception as e:
            log(f"Warning: Could not count tokens: {e}")

    # Build execution chain
    if model:
        chain = [model]
    elif model_chain:
        chain = list(model_chain)
    else:
        chain = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

    last_err = None
    for idx, target_model in enumerate(chain):
        _check_cancelled(cancel_event)
        log(f"Attempting transcription using {target_model}...")
        max_retries = 3
        for attempt in range(max_retries):
            _check_cancelled(cancel_event)
            try:
                response = client.models.generate_content(
                    model=target_model,
                    contents=prompt_contents
                )
                if not response or not getattr(response, "text", None):
                    raise ValueError(f"Empty or blocked response returned by {target_model}.")
                
                if target_model == "gemini-3.5-flash":
                    config.increment_usage()
                    if usage_callback:
                        usage_callback()
                return response.text, target_model
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                is_429 = "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str
                is_high_demand = (
                    "503" in err_str
                    or "unavailable" in err_str
                    or "high demand" in err_str
                    or "overloaded" in err_str
                )
                is_daily = is_429 and _is_daily_quota_error(err_str)
                
                if is_daily and target_model == "gemini-3.5-flash":
                    current = config.get_usage()
                    if current < config.MAX_FREE_REQUESTS:
                        config.increment_usage(config.MAX_FREE_REQUESTS - current)
                        if usage_callback:
                            usage_callback()

                has_fallback = idx < len(chain) - 1

                # Daily/free-tier quota: switch models immediately (no same-model retries/sleep)
                if is_daily and has_fallback:
                    next_m = chain[idx + 1]
                    log(
                        f"{target_model} daily/free-tier quota exhausted ({e}). "
                        f"Skipping retries and switching to fallback model: {next_m}..."
                    )
                    break

                # High-demand / unavailable: switch models immediately (no same-model retries)
                if is_high_demand and has_fallback:
                    next_m = chain[idx + 1]
                    log(f"{target_model} failed ({e}). Automatically switching to fallback model: {next_m}...")
                    break

                # If last retry for this model in chain and another model is available, break to try next model
                if attempt == max_retries - 1:
                    if has_fallback:
                        next_m = chain[idx + 1]
                        log(f"{target_model} failed ({e}). Automatically switching to fallback model: {next_m}...")
                        break
                    else:
                        raise e
                
                backoff = _calculate_backoff(attempt, is_429=is_429)
                if is_429:
                    log(f"Rate limit hit (429) on {target_model}. Waiting {backoff:.1f}s before retrying (Attempt {attempt + 2}/{max_retries})...")
                else:
                    log(f"Generation failed on {target_model}: {e}. Retrying in {backoff:.1f}s (Attempt {attempt + 2}/{max_retries})...")
                time.sleep(backoff)

    if last_err:
        raise last_err
    raise RuntimeError("All models in execution chain failed.")

def parse_directory(
    api_key, 
    directory_path, 
    output_dir=None, 
    custom_prompt=None, 
    log_callback=None, 
    throttle_seconds=15, 
    ignore_quota=False, 
    cancel_event=None,
    page_range=None,
    resume=False
):
    """
    Batch processing helper to handle entire directories of PDFs with a throttle mechanism.
    Respects Gemini Free Tier rate limits (15 RPM). Returns (success_count, fail_count).
    """
    import glob
    
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg + "\n")

    if not os.path.exists(directory_path) or not os.path.isdir(directory_path):
        raise FileNotFoundError(f"Directory not found: {directory_path}")

    pdf_files = glob.glob(os.path.join(directory_path, "*.pdf"))
    if not pdf_files:
        log(f"No PDF files found in {directory_path}")
        return 0, 0

    log(f"Found {len(pdf_files)} PDF files in {directory_path}.")
    
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        log(f"Created output directory: {output_dir}")

    success_count = 0
    fail_count = 0

    for i, file_path in enumerate(pdf_files):
        _check_cancelled(cancel_event)
        log(f"--- Processing File {i+1}/{len(pdf_files)}: {os.path.basename(file_path)} ---")
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        out_path = os.path.join(output_dir, f"{base_name}.md") if output_dir else f"{os.path.splitext(file_path)[0]}.md"
        try:
            md_content = parse_pdf(
                api_key=api_key, 
                file_path=file_path, 
                log_callback=log_callback, 
                custom_prompt=custom_prompt,
                ignore_quota=ignore_quota,
                cancel_event=cancel_event,
                page_range=page_range,
                resume=resume,
                output_path=out_path
            )
            
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            log(f"Successfully saved to {out_path}")
            success_count += 1
        except PartialParseError as ppe:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(ppe.partial_text)
            log(f"Partial results saved to {out_path} (Failed mid-chunk: {ppe.original_error})")
            fail_count += 1
        except Exception as e:
            log(f"Failed to process {file_path}: {e}")
            fail_count += 1
        
        # Pacing/Throttling between files
        if i < len(pdf_files) - 1:
            log(f"Throttling for {throttle_seconds} seconds to respect API limits...")
            time.sleep(throttle_seconds)

    log(f"Batch processing completed. Successful: {success_count}, Failed: {fail_count}")
    return success_count, fail_count
