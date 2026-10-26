import math
import struct
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

    def test_rfc8785_appendix_b_number_serialization_vectors(self):
        vectors = [
            ("0000000000000000", "0"),
            ("8000000000000000", "0"),
            ("0000000000000001", "5e-324"),
            ("8000000000000001", "-5e-324"),
            ("7fefffffffffffff", "1.7976931348623157e+308"),
            ("ffefffffffffffff", "-1.7976931348623157e+308"),
            ("4340000000000000", "9007199254740992"),
            ("c340000000000000", "-9007199254740992"),
            ("4430000000000000", "295147905179352830000"),
            ("44b52d02c7e14af5", "9.999999999999997e+22"),
            ("44b52d02c7e14af6", "1e+23"),
            ("44b52d02c7e14af7", "1.0000000000000001e+23"),
            ("444b1ae4d6e2ef4e", "999999999999999700000"),
            ("444b1ae4d6e2ef4f", "999999999999999900000"),
            ("444b1ae4d6e2ef50", "1e+21"),
        ]
        for ieee_bits, expected in vectors:
            with self.subTest(ieee_bits=ieee_bits):
                value = struct.unpack(">d", bytes.fromhex(ieee_bits))[0]
                self.assertEqual(canonical_json(value), expected)

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
