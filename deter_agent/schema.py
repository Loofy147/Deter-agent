"""Deterministic JSON Schema subset for versioned agent contracts."""
from __future__ import annotations
import re
from typing import Any
from .canonical import CanonicalizationError, normalize_json


class SchemaValidationError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def normalize_and_validate(value: Any, schema: dict[str, Any]) -> Any:
    try:
        normalized = normalize_json(value)
    except CanonicalizationError as exc:
        raise SchemaValidationError("$", str(exc)) from exc
    _validate(normalized, schema, "$")
    return normalized


def _validate(value: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(schema, dict):
        raise SchemaValidationError(path, "schema must be an object")
    supported = {
        "type", "properties", "required", "additionalProperties", "enum",
        "minLength", "maxLength", "pattern", "items", "minItems", "maxItems",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "minProperties", "maxProperties",
    }
    extra_keywords = set(schema) - supported
    if extra_keywords:
        raise SchemaValidationError(path, f"unsupported schema keywords: {sorted(extra_keywords)}")
    types = {
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
        "string": lambda x: isinstance(x, str),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "boolean": lambda x: isinstance(x, bool),
        "null": lambda x: x is None,
    }
    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not expected_types or any(item not in types for item in expected_types):
            raise SchemaValidationError(path, f"unsupported type {expected!r}")
        if not any(types[item](value) for item in expected_types):
            raise SchemaValidationError(path, f"expected one of {expected_types}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(path, "value is not an allowed enum member")
    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(x, str) for x in required):
            raise SchemaValidationError(path, "required must be a list of strings")
        missing = sorted(set(required) - set(value))
        if missing:
            raise SchemaValidationError(path, f"missing required fields: {missing}")
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            raise SchemaValidationError(path, "properties must be an object")
        extras = set(value) - set(props)
        additional = schema.get("additionalProperties", True)
        if extras and additional is False:
            raise SchemaValidationError(path, f"unknown fields are forbidden: {sorted(extras)}")
        if isinstance(additional, dict):
            for key in sorted(extras):
                _validate(value[key], additional, f"{path}.{key}")
        if len(value) < schema.get("minProperties", 0):
            raise SchemaValidationError(path, "object has too few properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            raise SchemaValidationError(path, "object has too many properties")
        for key in sorted(set(value) & set(props)):
            _validate(value[key], props[key], f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise SchemaValidationError(path, "array has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaValidationError(path, "array has too many items")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise SchemaValidationError(path, "string is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaValidationError(path, "string is too long")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise SchemaValidationError(path, "string does not match required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(path, "number is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(path, "number is above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaValidationError(path, "number must be greater than exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise SchemaValidationError(path, "number must be less than exclusiveMaximum")
