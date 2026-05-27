"""Tests for log output sanitization."""
from __future__ import annotations

import json
import logging
import sys

from generator.azure_logger import JSONFormatter
from generator.log_sanitize import sanitize_string


def test_sanitize_string_replaces_home_and_project_paths():
    home = "/Users/testuser"
    path = f"{home}/Documents/CompanyWork/EXLData/Telemetry/generator/runner.py"
    assert sanitize_string(path) == "~/Documents/CompanyWork/EXLData/Telemetry/generator/runner.py"


def test_json_formatter_strips_log_record_internals():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="generator.runner",
        level=logging.INFO,
        pathname="/Users/testuser/project/generator/runner.py",
        lineno=42,
        msg="startup complete",
        args=(),
        exc_info=None,
    )
    record.custom_field = "ok"

    doc = json.loads(formatter.format(record))

    assert "pathname" not in doc
    assert "filename" not in doc
    assert "lineno" not in doc
    assert "process" not in doc
    assert "thread" not in doc
    assert doc["message"] == "startup complete"
    assert doc["custom_field"] == "ok"


def test_json_formatter_sanitizes_exception_paths():
    formatter = JSONFormatter()
    home = "/Users/testuser"
    path = f"{home}/project/generator/runner.py"

    try:
        raise RuntimeError(f"boom at {path}")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="generator.runner",
        level=logging.ERROR,
        pathname=path,
        lineno=1,
        msg="failed",
        args=(),
        exc_info=exc_info,
    )

    doc = json.loads(formatter.format(record))

    assert "/Users/testuser" not in doc["exception"]
    assert "~/project/generator/runner.py" in doc["exception"]
