import os
import sys
import json
import datetime
import tempfile
import contextlib

def get_config_dir():
    custom_dir = os.environ.get("PDF_PARSER_CONFIG_DIR")
    if custom_dir:
        return custom_dir
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "pdf_parser_light")
    elif sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "pdf_parser_light")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        return os.path.join(base, "pdf_parser_light")

CONFIG_DIR = get_config_dir()
USAGE_FILE = os.path.join(CONFIG_DIR, "usage.json")
LOCK_FILE = os.path.join(CONFIG_DIR, "usage.lock")
MAX_FREE_REQUESTS = int(os.environ.get("GEMINI_FREE_LIMIT", 20))

@contextlib.contextmanager
def _usage_lock():
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    lock_fd = None
    try:
        lock_fd = open(LOCK_FILE, "w")
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    except Exception as e:
        print(f"Warning: Failed to acquire usage lock: {e}", file=sys.stderr)
        yield
    finally:
        if lock_fd:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                lock_fd.close()
            except Exception:
                pass

def _atomic_write_json(file_path, data):
    dir_name = os.path.dirname(file_path)
    os.makedirs(dir_name, mode=0o700, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="usage_", suffix=".tmp")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e

def _get_pacific_date():
    """Return current ISO date (YYYY-MM-DD) in US/Pacific time (Midnight PT quota reset)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        offset_hours = -7 if 3 <= now_utc.month <= 10 else -8
        tz_pt = datetime.timezone(datetime.timedelta(hours=offset_hours))
        return now_utc.astimezone(tz_pt).date().isoformat()

def _read_usage(today):
    try:
        if os.path.exists(USAGE_FILE):
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("date") == today:
                    return data.get("requests", 0)
    except Exception as e:
        print(f"Warning: Failed to read usage tracking file: {e}", file=sys.stderr)
    return 0

def get_usage():
    today = _get_pacific_date()
    with _usage_lock():
        return _read_usage(today)

def increment_usage(count=1):
    today = _get_pacific_date()
    with _usage_lock():
        requests = _read_usage(today) + count
        try:
            _atomic_write_json(USAGE_FILE, {"date": today, "requests": requests})
        except Exception as e:
            print(f"Error writing to usage tracking file: {e}", file=sys.stderr)
        return requests

def get_remaining_requests():
    return max(0, MAX_FREE_REQUESTS - get_usage())

def reset_usage():
    today = _get_pacific_date()
    with _usage_lock():
        try:
            _atomic_write_json(USAGE_FILE, {"date": today, "requests": 0})
        except Exception as e:
            print(f"Error resetting usage tracking file: {e}", file=sys.stderr)
        return 0


