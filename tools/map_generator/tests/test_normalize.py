"""Tests for the global ``normalize_map_objects`` helper in ``utils.py``."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from tools.map_generator.utils import (
    _cascade_value,
    _coerce_float,
    _coerce_int,
    normalize_map_objects,
)


# ---------------------------------------------------------------------------
# Test helpers – objects that simulate various schemas
# ---------------------------------------------------------------------------

class FlatDictObject:
    """Plain dictionary with top-level keys (the canonical form)."""

    def __init__(self, *, id: Any, x: Any, y: Any, time: Any, type: Any = "circle") -> None:
        self.data: dict[str, Any] = {"id": id, "x": x, "y": y, "time": time, "type": type}

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class NestedPositionDict:
    """Dict that stores coordinates inside a ``position`` sub-dict."""

    def __init__(self, *, id: Any, x: Any, y: Any, time: Any) -> None:
        self.data: dict[str, Any] = {
            "id": id,
            "position": {"x": x, "y": y},
            "time": time,
        }

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class NestedTimingDict:
    """Dict that stores timing inside a ``timing`` sub-dict."""

    def __init__(self, *, id: Any, x: Any, y: Any, time: Any) -> None:
        self.data: dict[str, Any] = {
            "id": id,
            "x": x,
            "y": y,
            "timing": {"time": time},
        }

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class ClassInstance:
    """Plain class with attributes (no dict interface)."""

    def __init__(self, *, id: Any, x: Any, y: Any, time: Any, type: str = "circle") -> None:
        self.id = id
        self.x = x
        self.y = y
        self.time = time
        self.type = type


class ClassInstanceStartTime:
    """Class instance using ``start_time`` instead of ``time``."""

    def __init__(self, *, id: Any, x: Any, y: Any, start_time: Any) -> None:
        self.id = id
        self.x = x
        self.y = y
        self.start_time = start_time


class ClassInstanceNestedPosition:
    """Class instance with a ``position`` sub-object."""

    def __init__(self, *, id: Any, x: Any, y: Any, time: Any) -> None:
        self.id = id
        self.position = _Pos(x, y)
        self.time = time


@dataclass
class _Pos:
    x: int
    y: int


class MinimalDict:
    """Dict missing most fields – only has ``id``."""

    def __init__(self, id: Any) -> None:
        self.data: dict[str, Any] = {"id": id}

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class NormalizeMapObjectsTests(unittest.TestCase):
    """Comprehensive tests for ``normalize_map_objects``."""

    # --- basic shapes ---

    def test_flat_dict_with_top_level_keys(self) -> None:
        items = [{"id": 1, "x": 512, "y": 256, "time": 1000}]
        result = normalize_map_objects(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], {"id": "1", "x": 512, "y": 256, "time": 1000.0, "type": "circle"})

    def test_nested_position_dict(self) -> None:
        items = [{"id": 2, "position": {"x": 100, "y": 200}, "time": 500}]
        result = normalize_map_objects(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["x"], 100)
        self.assertEqual(result[0]["y"], 200)
        self.assertEqual(result[0]["time"], 500.0)

    def test_nested_timing_dict(self) -> None:
        items = [{"id": 3, "x": 300, "y": 400, "timing": {"time": 750}}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["time"], 750.0)

    def test_start_time_fallback(self) -> None:
        items = [{"id": 4, "x": 0, "y": 0, "start_time": 2000}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["time"], 2000.0)

    def test_class_instance_with_attributes(self) -> None:
        obj = ClassInstance(id=5, x=640, y=480, time=3000)
        result = normalize_map_objects([obj])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["x"], 640)
        self.assertEqual(result[0]["y"], 480)
        self.assertEqual(result[0]["time"], 3000.0)
        self.assertEqual(result[0]["id"], "5")

    def test_class_instance_start_time(self) -> None:
        obj = ClassInstanceStartTime(id=6, x=10, y=20, start_time=999)
        result = normalize_map_objects([obj])
        self.assertEqual(result[0]["time"], 999.0)

    def test_class_instance_nested_position(self) -> None:
        obj = ClassInstanceNestedPosition(id=7, x=123, y=456, time=800)
        result = normalize_map_objects([obj])
        self.assertEqual(result[0]["x"], 123)
        self.assertEqual(result[0]["y"], 456)

    # --- missing fields / defaults ---

    def test_missing_x_y_defaults_to_zero(self) -> None:
        items = [{"id": 10, "time": 100}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["x"], 0)
        self.assertEqual(result[0]["y"], 0)

    def test_missing_time_defaults_to_zero(self) -> None:
        items = [{"id": 11, "x": 50, "y": 50}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["time"], 0.0)

    def test_missing_id_generates_obj_idx(self) -> None:
        items = [{"x": 10, "y": 20, "time": 30}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["id"], "obj_0")

    def test_missing_type_defaults_to_circle(self) -> None:
        items = [{"id": 1, "x": 0, "y": 0, "time": 0}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["type"], "circle")

    def test_missing_everything(self) -> None:
        items = [{}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["id"], "obj_0")
        self.assertEqual(result[0]["x"], 0)
        self.assertEqual(result[0]["y"], 0)
        self.assertEqual(result[0]["time"], 0.0)
        self.assertEqual(result[0]["type"], "circle")

    # --- type coercion ---

    def test_string_coordinates_are_coerced_to_int(self) -> None:
        items = [{"id": "abc", "x": "512", "y": "256", "time": "1000"}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["x"], 512)
        self.assertEqual(result[0]["y"], 256)
        self.assertIsInstance(result[0]["x"], int)
        self.assertIsInstance(result[0]["y"], int)

    def test_float_coordinates_are_coerced_to_int(self) -> None:
        items = [{"id": 1, "x": 100.7, "y": 200.3, "time": 500}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["x"], 100)
        self.assertEqual(result[0]["y"], 200)

    def test_non_numeric_coordinates_default_to_zero(self) -> None:
        items = [{"id": 1, "x": "invalid", "y": None, "time": "abc"}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["x"], 0)
        self.assertEqual(result[0]["y"], 0)
        self.assertEqual(result[0]["time"], 0.0)

    def test_boolean_id_is_stringified(self) -> None:
        items = [{"id": True, "x": 0, "y": 0, "time": 0}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["id"], "True")

    # --- edge cases ---

    def test_empty_list_returns_empty(self) -> None:
        self.assertEqual(normalize_map_objects([]), [])

    def test_none_input_returns_empty(self) -> None:
        self.assertEqual(normalize_map_objects(None), [])

    def test_non_list_input_returns_empty(self) -> None:
        self.assertEqual(normalize_map_objects("not a list"), [])
        self.assertEqual(normalize_map_objects(42), [])

    def test_none_items_are_skipped(self) -> None:
        items = [None, {"id": 1, "x": 10, "y": 20, "time": 30}, None]
        result = normalize_map_objects(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "1")

    def test_explicit_type_is_preserved(self) -> None:
        items = [{"id": 1, "x": 0, "y": 0, "time": 0, "type": "slider"}]
        result = normalize_map_objects(items)
        self.assertEqual(result[0]["type"], "slider")

    def test_multiple_objects_mixed_schemas(self) -> None:
        items = [
            {"id": 1, "x": 10, "y": 20, "time": 100},                       # flat dict
            {"id": 2, "position": {"x": 30, "y": 40}, "time": 200},          # nested position
            {"id": 3, "x": 50, "y": 60, "timing": {"time": 300}},           # nested timing
            ClassInstance(id=4, x=70, y=80, time=400),                       # class instance
            {},                                                               # empty dict
        ]
        result = normalize_map_objects(items)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["x"], 10)
        self.assertEqual(result[1]["x"], 30)
        self.assertEqual(result[2]["time"], 300.0)
        self.assertEqual(result[3]["x"], 70)
        self.assertEqual(result[4]["id"], "obj_4")
        self.assertEqual(result[4]["x"], 0)


class CascadeValueTests(unittest.TestCase):
    """Tests for the internal ``_cascade_value`` helper."""

    def test_direct_dict_key(self) -> None:
        item = {"x": 42}
        self.assertEqual(_cascade_value(item, ["x"]), 42)

    def test_multiple_keys_uses_first_match(self) -> None:
        item = {"time": 100, "start_time": 200}
        self.assertEqual(_cascade_value(item, ["time", "start_time"]), 100)

    def test_falls_back_to_second_key(self) -> None:
        item = {"start_time": 200}
        self.assertEqual(_cascade_value(item, ["time", "start_time"]), 200)

    def test_nested_dict_fallback(self) -> None:
        item = {"position": {"x": 99}}
        self.assertEqual(_cascade_value(item, ["x"], nested_key="position", nested_sub="x"), 99)

    def test_nested_dict_not_present(self) -> None:
        # Direct key "other" is missing; nested key "position" is also missing → None
        item = {"x": 5}
        self.assertIsNone(
            _cascade_value(item, ["other"], nested_key="position", nested_sub="x"),
        )

    def test_direct_key_takes_precedence_over_nested(self) -> None:
        # "x" is present at top level; nested position.x exists too → top-level wins
        item = {"x": 10, "position": {"x": 99}}
        self.assertEqual(
            _cascade_value(item, ["x"], nested_key="position", nested_sub="x"),
            10,
        )

    def test_class_attribute_lookup(self) -> None:
        obj = ClassInstance(id=1, x=10, y=20, time=30)
        self.assertEqual(_cascade_value(obj, ["x"]), 10)

    def test_nested_attribute_lookup(self) -> None:
        obj = ClassInstanceNestedPosition(id=1, x=10, y=20, time=30)
        self.assertEqual(
            _cascade_value(obj, ["other"], nested_key="position", nested_sub="x"),
            10,
        )

    def test_missing_everywhere_returns_none(self) -> None:
        item = {"unrelated": True}
        self.assertIsNone(_cascade_value(item, ["x"]))
        self.assertIsNone(_cascade_value(item, ["x"], nested_key="position", nested_sub="x"))

    def test_none_value_is_not_returned(self) -> None:
        item = {"x": None}
        self.assertIsNone(_cascade_value(item, ["x"]))


class CoerceIntTests(unittest.TestCase):
    """Tests for ``_coerce_int``."""

    def test_int_passthrough(self) -> None:
        self.assertEqual(_coerce_int(42), 42)

    def test_float_truncated(self) -> None:
        self.assertEqual(_coerce_int(3.9), 3)

    def test_string_numeric(self) -> None:
        self.assertEqual(_coerce_int("100"), 100)

    def test_none_returns_zero(self) -> None:
        self.assertEqual(_coerce_int(None), 0)

    def test_invalid_string_returns_zero(self) -> None:
        self.assertEqual(_coerce_int("abc"), 0)

    def test_bool_coerced(self) -> None:
        self.assertEqual(_coerce_int(True), 1)
        self.assertEqual(_coerce_int(False), 0)


class CoerceFloatTests(unittest.TestCase):
    """Tests for ``_coerce_float``."""

    def test_float_passthrough(self) -> None:
        self.assertEqual(_coerce_float(3.14), 3.14)

    def test_int_promoted(self) -> None:
        self.assertEqual(_coerce_float(10), 10.0)

    def test_string_numeric(self) -> None:
        self.assertEqual(_coerce_float("2.5"), 2.5)

    def test_none_returns_zero(self) -> None:
        self.assertEqual(_coerce_float(None), 0.0)

    def test_invalid_string_returns_zero(self) -> None:
        self.assertEqual(_coerce_float("xyz"), 0.0)


if __name__ == "__main__":
    unittest.main()
