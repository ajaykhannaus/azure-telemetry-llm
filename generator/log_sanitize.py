"""Redact host-specific paths and other sensitive fragments from log output."""
from __future__ import annotations

import os
import re
from typing import Any

_HOME = os.path.expanduser("~") or ""
_CWD = os.getcwd() or ""

# Longest paths first so partial replacements do not leave suffixes behind.
_PATH_PREFIXES = tuple(
    p for p in sorted({_HOME, _CWD}, key=len, reverse=True) if p
)

_UNIX_USER_PATH = re.compile(r"/(?:Users|home)/[^/\s\"']+")
_WIN_USER_PATH = re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+", re.IGNORECASE)


def sanitize_string(value: str) -> str:
    """Replace user home, cwd, and common user-profile path prefixes."""
    if not value:
        return value

    text = value
    for prefix in _PATH_PREFIXES:
        if prefix in text:
            text = text.replace(prefix, "~")

    text = _UNIX_USER_PATH.sub("~", text)
    text = _WIN_USER_PATH.sub("~", text)
    return text


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize strings inside log payload values."""
    if isinstance(value, str):
        return sanitize_string(value)
    if isinstance(value, dict):
        return {k: sanitize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(v) for v in value]
    return value
