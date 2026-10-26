import math
import unittest

from deter_agent.canonical import CanonicalizationError, canonical_json, normalize_json, sha256_json
from deter_agent.schema import SchemaValidationError, normalize_and_validate


class CanonicalizationTests(unittest.TestCase):
    def test_object_order_hash(self):
        self.assertEqual(sha256_json({"b": 2, "a": 1}), sha256_json({"a": 1, "b": 2}))

    def test_nfc_is_recursive(self):
        self.assertEqual(normalize_json({"name": "e\u0301"}), {"name": "\u00e9"})

    def test_nfc_key_collision_rejected(self):
        with self.assertRaises(CanonicalizationError):
            canonical_json({"e\u0301": 1, "\u00e9": 2})

    def test_surrogate_rejected(self):
        with self.assertRaises(CanonicalizationError):
            canonical_json({"bad": "\ud800"})

    def test_nonfinite_rejected(self):
        with self.assertRaises(CanonicalizationError):
            canonical_json({"x": math.nan})

    def test_number_formatting(self):
        self.assertEqual(canonical_json([1.0, -0.0, 1e-6, 1e-7, 1e20, 1e21]), "[1,0,0.000001,1e-7,100000000000000000000,1e+21]")

    def test_utf16_key_order(self):
        self.assertEqual(canonical_json({"\ue000": 1, "\U00010000": 2}), '{"\U00010000":2,"\ue000":1}')

    def test_unsafe_integer_rejected(self):
        with self.assertRaises(CanonicalizationError):
            canonical_json(9_007_199_254_740_992)


class SchemaTests(unittest.TestCase):
    def test_reject_unknown_and_normalize(self):
        schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}, "additionalProperties": False}
        self.assertEqual(normalize_and_validate({"name": "e\u0301"}, schema), {"name": "\u00e9"})
        with self.assertRaises(SchemaValidationError):
            normalize_and_validate({"name": "ok", "extra": True}, schema)

    def test_bool_is_not_integer(self):
        with self.assertRaises(SchemaValidationError):
            normalize_and_validate({"count": True}, {"type": "object", "properties": {"count": {"type": "integer"}}, "additionalProperties": False})

    def test_required_enum_range(self):
        schema = {"type": "object", "required": ["level"], "properties": {"level": {"type": "integer", "minimum": 1, "maximum": 3, "enum": [1, 2, 3]}}, "additionalProperties": False}
        self.assertEqual(normalize_and_validate({"level": 2}, schema), {"level": 2})
        with self.assertRaises(SchemaValidationError):
            normalize_and_validate({"level": 4}, schema)
