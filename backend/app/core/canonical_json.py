"""RFC 8785 (JSON Canonicalization Scheme - JCS) implementation for NEXUS.

Guarantees deterministic, cryptographic serialization:
1. Output is strictly UTF-8 encoded bytes without BOM.
2. Object keys are sorted strictly by UTF-16 code unit sequences (RFC 8785 §3.2.3).
3. Numbers follow ECMAScript 2020 §7.1.12.1 ToString formatting:
   - -0.0 and +0.0 serialize as "0".
   - Shortest IEEE 754 round-trip decimal representation without trailing zeros.
   - Non-finite numbers (NaN, Infinity, -Infinity) are strictly rejected.
4. Strings escape only required characters (\\", \\\\, and control codes U+0000..U+001F).
   All Unicode characters outside ASCII (including BMP and astral planes) are emitted
   as literal UTF-8 without unicode escape sequences (RFC 8785 §3.2.2.2).
5. Zero whitespace outside string literals.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any


def normalize_timestamp_utc(dt: datetime | str) -> str:
    """
    Normalize datetime or ISO timestamp string to canonical UTC format:
    YYYY-MM-DDTHH:MM:SS.ffffffZ.
    
    Guarantees cross-database serialization invariance between PostgreSQL and SQLite.
    """
    if isinstance(dt, str):
        clean_str = dt.replace("Z", "+00:00")
        dt_obj = datetime.fromisoformat(clean_str)
    else:
        dt_obj = dt

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=UTC)
    else:
        dt_obj = dt_obj.astimezone(UTC)

    return dt_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def float_to_ecma_str(x: float) -> str:
    """Format IEEE 754 double precision float per ECMAScript 2020 §7.1.12.1 / RFC 8785 §3.2.2.3."""
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"Non-finite numbers ({x}) are forbidden in JSON Canonicalization Scheme (RFC 8785)")

    if x == 0.0:
        return "0"

    sign = "-" if math.copysign(1.0, x) < 0.0 else ""
    abs_x = abs(x)

    rep = repr(abs_x)
    if "e" in rep:
        mantissa_str, exp_str = rep.split("e")
        exp = int(exp_str)
        digits = mantissa_str.replace(".", "")
        k = len(digits)
        n = exp + 1
        s = digits
    else:
        parts = rep.split(".")
        int_part = parts[0]
        frac_part = parts[1] if len(parts) > 1 else ""
        if frac_part == "0":
            frac_part = ""
        digits = int_part + frac_part
        digits_stripped = digits.lstrip("0")
        if not digits_stripped:
            return "0"

        if int_part == "0":
            leading_zeros = len(frac_part) - len(frac_part.lstrip("0"))
            n = -leading_zeros
            s = digits_stripped
            k = len(s)
        else:
            n = len(int_part)
            s = digits_stripped
            k = len(s)

    # ECMAScript ToString §7.1.12.1 branch cases
    if k <= n <= 21:
        res = s + ("0" * (n - k))
    elif 0 < n <= 21:
        res = s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        res = "0." + ("0" * (-n)) + s
    else:
        # Exponential notation: n <= -6 or n > 21
        if k == 1:
            m = s
        else:
            m = s[0] + "." + s[1:]
        sign_e = "+" if (n - 1) >= 0 else "-"
        res = m + "e" + sign_e + str(abs(n - 1))

    return sign + res


def _escape_string(s: str) -> str:
    """Escape string according to RFC 8785 §3.2.2.2."""
    out: list[str] = ['"']
    for char in s:
        code = ord(char)
        if char == '"':
            out.append(r'\"')
        elif char == "\\":
            out.append(r"\\")
        elif char == "\b":
            out.append(r"\b")
        elif char == "\t":
            out.append(r"\t")
        elif char == "\n":
            out.append(r"\n")
        elif char == "\f":
            out.append(r"\f")
        elif char == "\r":
            out.append(r"\r")
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            # Emit literal character (UTF-8)
            out.append(char)
    out.append('"')
    return "".join(out)


def _serialize_element(obj: Any) -> str:
    """Recursively serialize an element to its RFC 8785 canonical string representation."""
    if obj is None:
        return "null"

    if isinstance(obj, bool):
        return "true" if obj else "false"

    if isinstance(obj, int):
        return str(obj)

    if isinstance(obj, float):
        return float_to_ecma_str(obj)

    if isinstance(obj, str):
        return _escape_string(obj)

    if isinstance(obj, (list, tuple)):
        items = [_serialize_element(item) for item in obj]
        return "[" + ",".join(items) + "]"

    if isinstance(obj, dict):
        # RFC 8785 §3.2.3: Keys MUST be strings, sorted by UTF-16 code units
        for k in obj:
            if not isinstance(k, str):
                raise TypeError(f"Dictionary keys in RFC 8785 must be strings, found: {type(k).__name__}")

        # UTF-16 BE encoding directly yields UTF-16 code units in lexicographical order
        sorted_keys = sorted(obj.keys(), key=lambda k: k.encode("utf-16-be"))
        kvs = [f"{_escape_string(k)}:{_serialize_element(obj[k])}" for k in sorted_keys]
        return "{" + ",".join(kvs) + "}"

    raise TypeError(
        f"Unsupported data type for RFC 8785 canonical serialization: {type(obj).__name__}"
    )


def jcs_rfc8785_serialize(data: Any) -> bytes:
    """
    Serialize Python data structure to deterministic RFC 8785 canonical JSON bytes.
    
    Returns:
        UTF-8 encoded bytes adhering strictly to the JSON Canonicalization Scheme.
    """
    canonical_str = _serialize_element(data)
    return canonical_str.encode("utf-8")


def canonical_json_dumps(data: Any) -> str:
    """Return decoded UTF-8 string of RFC 8785 canonical serialization."""
    return jcs_rfc8785_serialize(data).decode("utf-8")


def canonical_sha256(data: Any) -> str:
    """Compute standard SHA-256 hex digest over RFC 8785 canonical bytes."""
    raw_bytes = jcs_rfc8785_serialize(data)
    return hashlib.sha256(raw_bytes).hexdigest()
