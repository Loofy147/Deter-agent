"""Canonical JSON, Unicode normalization, and content-addressed identities."""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_DEPTH = 64
MAX_NODES = 100_000


class CanonicalizationError(ValueError):
    pass


def _text(value: str, path: str) -> str:
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(f"{path}: unpaired Unicode surrogate") from exc
    return unicodedata.normalize("NFC", value)


def normalize_json(value: Any, *, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> Any:
    """Return an NFC-normalized JSON copy; reject exotic types, nonfinite numbers and key collisions."""
    count = 0

    def visit(node: Any, path: str, depth: int) -> Any:
        nonlocal count
        count += 1
        if count > max_nodes:
            raise CanonicalizationError(f"{path}: JSON node limit exceeded")
        if depth > max_depth:
            raise CanonicalizationError(f"{path}: JSON depth limit exceeded")
        if node is None or isinstance(node, bool):
            return node
        if isinstance(node, int):
            if abs(node) > MAX_SAFE_INTEGER:
                raise CanonicalizationError(f"{path}: integer outside interoperable IEEE-754 safe range")
            return node
        if isinstance(node, float):
            if not math.isfinite(node):
                raise CanonicalizationError(f"{path}: NaN and Infinity are invalid JSON numbers")
            return 0.0 if node == 0.0 else node
        if isinstance(node, str):
            return _text(node, path)
        if isinstance(node, (list, tuple)):
            return [visit(item, f"{path}[{index}]", depth + 1) for index, item in enumerate(node)]
        if isinstance(node, dict):
            output = {}
            originals = {}
            for key, item in node.items():
                if not isinstance(key, str):
                    raise CanonicalizationError(f"{path}: object keys must be strings")
                nkey = _text(key, f"{path}.<key>")
                if nkey in output:
                    raise CanonicalizationError(f"{path}: keys {originals[nkey]!r} and {key!r} collide after NFC")
                output[nkey] = visit(item, f"{path}.{nkey}", depth + 1)
                originals[nkey] = key
            return output
        raise CanonicalizationError(f"{path}: unsupported JSON type {type(node).__name__}")

    return visit(value, "$", 0)


def _number(value: int | float) -> str:
    if isinstance(value, bool):
        raise CanonicalizationError("boolean is not a number")
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalizationError("integer outside interoperable IEEE-754 safe range")
        return str(value)
    if not math.isfinite(value):
        raise CanonicalizationError("nonfinite number")
    if value == 0:
        return "0"
    negative = value < 0
    raw = repr(abs(value)).lower()
    if "e" in raw:
        mantissa, exponent_text = raw.split("e", 1)
        exponent = int(exponent_text)
    else:
        mantissa, exponent = raw, 0
    if "." in mantissa:
        integer_part, fractional_part = mantissa.split(".", 1)
    else:
        integer_part, fractional_part = mantissa, ""
    digits = integer_part + fractional_part
    decimal_position = len(integer_part) + exponent
    leading = len(digits) - len(digits.lstrip("0"))
    digits = digits.lstrip("0")
    decimal_position -= leading
    if not digits:
        return "0"
    digits = digits.rstrip("0")
    if 0 < decimal_position <= 21:
        if decimal_position >= len(digits):
            rendered = digits + "0" * (decimal_position - len(digits))
        else:
            rendered = digits[:decimal_position] + "." + digits[decimal_position:]
    elif -6 < decimal_position <= 0:
        rendered = "0." + "0" * (-decimal_position) + digits
    else:
        e = decimal_position - 1
        rendered = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
        rendered += "e" + ("+" if e >= 0 else "") + str(e)
    return ("-" if negative else "") + rendered


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda item: item.encode("utf-16-be"))
        return "{" + ",".join(_serialize(key) + ":" + _serialize(value[key]) for key in keys) + "}"
    raise CanonicalizationError(f"unsupported value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize deterministically after NFC normalization."""
    return _serialize(normalize_json(value))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
