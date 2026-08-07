import os
import json
import pytest

import pdf_parser_light.config as config

@pytest.fixture
def temp_config_dir(tmp_path):
    """Fixture that isolates CONFIG_DIR and USAGE_FILE to a temporary path."""
    test_dir = str(tmp_path / "test_config")
    os.makedirs(test_dir, exist_ok=True)
    
    orig_config_dir = config.CONFIG_DIR
    orig_usage_file = config.USAGE_FILE
    orig_lock_file = config.LOCK_FILE

    config.CONFIG_DIR = test_dir
    config.USAGE_FILE = os.path.join(test_dir, "usage.json")
    config.LOCK_FILE = os.path.join(test_dir, "usage.lock")

    yield test_dir

    config.CONFIG_DIR = orig_config_dir
    config.USAGE_FILE = orig_usage_file
    config.LOCK_FILE = orig_lock_file

def test_initial_usage_zero(temp_config_dir):
    assert config.get_usage() == 0
    assert config.get_remaining_requests() == config.MAX_FREE_REQUESTS

def test_increment_usage(temp_config_dir):
    assert config.increment_usage(1) == 1
    assert config.get_usage() == 1
    assert config.get_remaining_requests() == config.MAX_FREE_REQUESTS - 1

def test_increment_usage_multiple(temp_config_dir):
    config.increment_usage(5)
    assert config.get_usage() == 5
    assert config.get_remaining_requests() == config.MAX_FREE_REQUESTS - 5

def test_atomic_write_json(temp_config_dir):
    target_file = os.path.join(temp_config_dir, "sub", "test.json")
    data = {"key": "value", "count": 42}
    config._atomic_write_json(target_file, data)
    
    assert os.path.exists(target_file)
    with open(target_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data

def test_usage_reset_on_new_day(temp_config_dir):
    # Pre-populate usage file with yesterday's date
    old_data = {"date": "2020-01-01", "requests": 15}
    with open(config.USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(old_data, f)

    # Calling get_usage today should see the date mismatch and return 0
    assert config.get_usage() == 0

def test_get_pacific_date(temp_config_dir):
    pacific_date = config._get_pacific_date()
    assert len(pacific_date) == 10
    assert pacific_date.count("-") == 2

def test_usage_lock_handles_exception_and_logs(temp_config_dir, capsys, monkeypatch):
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("Lock permission denied")))
    with config._usage_lock():
        pass
    captured = capsys.readouterr()
    assert "Warning: Failed to acquire usage lock: Lock permission denied" in captured.err


