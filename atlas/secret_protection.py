from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes
from typing import Optional


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


CRYPTPROTECT_UI_FORBIDDEN = 0x00000001


def protection_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        probe = _protect("atlas-probe")
        return probe is not None and _unprotect(probe) == "atlas-probe"
    except Exception:
        return False


def _protect(plaintext: str) -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        data = plaintext.encode("utf-8")
        input_blob = _DataBlob(len(data), (ctypes.c_byte * len(data))(*data))
        output_blob = _DataBlob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not ok:
            return None
        raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        return "dpapi:" + base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


def _unprotect(stored: str) -> Optional[str]:
    if not stored.startswith("dpapi:"):
        return stored
    if sys.platform != "win32":
        return None
    try:
        raw = base64.b64decode(stored[len("dpapi:"):], validate=True)
        input_blob = _DataBlob(len(raw), (ctypes.c_byte * len(raw))(*raw))
        output_blob = _DataBlob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        if not ok:
            return None
        result = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        return result.decode("utf-8")
    except Exception:
        return None


def protect_secret(plaintext: str) -> Optional[str]:
    text = (plaintext or "").strip()
    if not text:
        return ""
    return _protect(text)


def unprotect_secret(stored: str) -> str:
    text = (stored or "").strip()
    if not text:
        return ""
    if not text.startswith("dpapi:"):
        return text
    result = _unprotect(text)
    return result if result is not None else ""
