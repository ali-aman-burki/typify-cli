"""
Tests for the typify type inference engine.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from typify.engine import TypeInferenceVisitor
from typify.types import (
    INT, FLOAT, STR, BOOL, NONE, UNKNOWN, ANY,
    ListType, TupleType, SetType, DictType,
    FunctionType, UnionType, NoneType, PrimitiveType,
    InstanceType,
)


def infer(source: str):
    """Helper: run inference and return result."""
    v = TypeInferenceVisitor("<test>", "test")
    return v.infer(source)


def get_type(source: str, name: str):
    """Infer and look up a specific binding by name."""
    result = infer(source)
    for qname, sym in result.bindings:
        if qname == name:
            return sym.inferred_type
    return UNKNOWN


# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

class TestLiterals:
    def test_int(self):       assert get_type("x = 42", "x") == INT
    def test_neg_int(self):   assert get_type("x = -1", "x") == INT
    def test_float(self):     assert get_type("x = 3.14", "x") == FLOAT
    def test_str(self):       assert get_type("x = 'hello'", "x") == STR
    def test_bool_true(self): assert get_type("x = True", "x") == BOOL
    def test_bool_false(self):assert get_type("x = False", "x") == BOOL
    def test_none(self):      assert get_type("x = None", "x") == NONE
    def test_bytes(self):     assert get_type("x = b'hi'", "x") == PrimitiveType("bytes")
    def test_fstring(self):   assert get_type("name='A'; x = f'hi {name}'", "x") == STR


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

class TestCollections:
    def test_list_of_ints(self):
        t = get_type("x = [1, 2, 3]", "x")
        assert t == ListType(INT)

    def test_list_of_strs(self):
        t = get_type("x = ['a', 'b']", "x")
        assert t == ListType(STR)

    def test_empty_list(self):
        t = get_type("x = []", "x")
        assert isinstance(t, ListType)

    def test_tuple(self):
        t = get_type("x = (1, 'a', True)", "x")
        assert isinstance(t, TupleType)
        assert t.element_types == (INT, STR, BOOL)

    def test_set(self):
        t = get_type("x = {1, 2, 3}", "x")
        assert t == SetType(INT)

    def test_dict(self):
        t = get_type("x = {'a': 1, 'b': 2}", "x")
        assert t == DictType(STR, INT)

    def test_mixed_list_union(self):
        t = get_type("x = [1, 2.0]", "x")
        assert isinstance(t, ListType)
        assert isinstance(t.element_type, UnionType)


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

class TestArithmetic:
    def test_int_add(self):
        assert get_type("a=1; b=2; x=a+b", "x") == INT

    def test_int_float_add(self):
        assert get_type("a=1; b=2.0; x=a+b", "x") == FLOAT

    def test_str_concat(self):
        assert get_type("a='hi'; b=' there'; x=a+b", "x") == STR

    def test_division_always_float(self):
        assert get_type("a=10; b=3; x=a/b", "x") == FLOAT

    def test_floor_div_int(self):
        assert get_type("a=10; b=3; x=a//b", "x") == INT

    def test_modulo_int(self):
        assert get_type("a=10; b=3; x=a%b", "x") == INT

    def test_unary_neg_int(self):
        assert get_type("a=5; x=-a", "x") == INT

    def test_unary_not(self):
        assert get_type("a=True; x=not a", "x") == BOOL

    def test_comparison(self):
        assert get_type("a=1; b=2; x=a<b", "x") == BOOL

    def test_str_multiply(self):
        assert get_type("s='hi'; x=s*3", "x") == STR


# ---------------------------------------------------------------------------
# Builtins
# ---------------------------------------------------------------------------

class TestBuiltins:
    def test_len(self):
        assert get_type("x = len([1,2,3])", "x") == INT

    def test_str_call(self):
        assert get_type("x = str(42)", "x") == STR

    def test_int_call(self):
        assert get_type("x = int('3')", "x") == INT

    def test_float_call(self):
        assert get_type("x = float('3.14')", "x") == FLOAT

    def test_bool_call(self):
        assert get_type("x = bool(0)", "x") == BOOL

    def test_list_call(self):
        t = get_type("x = list()", "x")
        assert isinstance(t, ListType)

    def test_range(self):
        t = get_type("x = range(10)", "x")
        assert t == PrimitiveType("range")

    def test_abs_int(self):
        assert get_type("a=-5; x=abs(a)", "x") == INT

    def test_abs_float(self):
        assert get_type("a=-5.0; x=abs(a)", "x") == FLOAT

    def test_sorted(self):
        t = get_type("x = sorted([3,1,2])", "x")
        assert isinstance(t, ListType)

    def test_isinstance(self):
        assert get_type("x = isinstance(1, int)", "x") == BOOL

    def test_print_returns_none(self):
        assert get_type("x = print('hi')", "x") == NONE


# ---------------------------------------------------------------------------
# String methods
# ---------------------------------------------------------------------------

class TestStringMethods:
    def test_upper(self):
        assert get_type("s='hello'; x=s.upper()", "x") == STR

    def test_split(self):
        t = get_type("s='a b'; x=s.split()", "x")
        assert t == ListType(STR)

    def test_strip(self):
        assert get_type("s='  hi  '; x=s.strip()", "x") == STR

    def test_startswith(self):
        assert get_type("s='hello'; x=s.startswith('h')", "x") == BOOL

    def test_len_of_str(self):
        assert get_type("s='hello'; x=len(s)", "x") == INT

    def test_join(self):
        assert get_type("x = ', '.join(['a','b'])", "x") == STR


# ---------------------------------------------------------------------------
# Function return types
# ---------------------------------------------------------------------------

class TestFunctions:
    def test_literal_return(self):
        src = "def f():\n    return 42\nx = f()"
        assert get_type(src, "x") == INT

    def test_str_return(self):
        src = "def greet():\n    return 'hello'\nx = greet()"
        assert get_type(src, "x") == STR

    def test_none_return(self):
        src = "def f():\n    pass\nx = f()"
        assert get_type(src, "x") == NONE

    def test_conditional_return_union(self):
        src = (
            "def f(flag):\n"
            "    if flag:\n"
            "        return 1\n"
            "    return 'no'\n"
            "x = f(True)"
        )
        t = get_type(src, "x")
        assert isinstance(t, UnionType)
        assert INT in t.types
        assert STR in t.types

    def test_return_type_recorded(self):
        src = "def add(a, b):\n    return a + b\n"
        result = infer(src)
        assert "add" in result.function_returns

    def test_chained_call(self):
        src = (
            "def get_name():\n"
            "    return 'Alice'\n"
            "def greet():\n"
            "    name = get_name()\n"
            "    return name\n"
            "x = greet()\n"
        )
        assert get_type(src, "x") == STR


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

class TestClasses:
    def test_class_instantiation(self):
        src = (
            "class Foo:\n"
            "    pass\n"
            "x = Foo()\n"
        )
        t = get_type(src, "x")
        assert isinstance(t, InstanceType)
        assert t.class_name == "Foo"

    def test_instance_attribute(self):
        src = (
            "class Box:\n"
            "    def __init__(self):\n"
            "        self.value = 42\n"
            "        self.label = 'box'\n"
        )
        result = infer(src)
        assert result.class_attrs.get("Box.value") == INT
        assert result.class_attrs.get("Box.label") == STR

    def test_method_return(self):
        src = (
            "class Counter:\n"
            "    def __init__(self):\n"
            "        self.count = 0\n"
            "    def get(self):\n"
            "        return self.count\n"
        )
        result = infer(src)
        assert result.function_returns.get("Counter.get") == INT

    def test_self_attr_propagation(self):
        src = (
            "class C:\n"
            "    def __init__(self):\n"
            "        self.x = 1\n"
            "    def double(self):\n"
            "        return self.x * 2\n"
        )
        result = infer(src)
        assert result.function_returns.get("C.double") == INT


# ---------------------------------------------------------------------------
# Variable propagation
# ---------------------------------------------------------------------------

class TestPropagation:
    def test_simple_copy(self):
        src = "a = 99\nb = a"
        assert get_type(src, "b") == INT

    def test_chain(self):
        src = "a = 'x'\nb = a\nc = b"
        assert get_type(src, "c") == STR

    def test_augmented_assign(self):
        src = "x = 0\nx += 1"
        assert get_type(src, "x") == INT

    def test_multiple_assign_union(self):
        src = "x = 1\nx = 'hello'"
        # x should be int | str
        t = get_type(src, "x")
        assert isinstance(t, UnionType)


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------

class TestControlFlow:
    def test_for_loop_var_list(self):
        src = "items = [1,2,3]\nfor x in items:\n    pass"
        assert get_type(src, "x") == INT

    def test_for_loop_var_str(self):
        src = "for c in 'hello':\n    pass"
        assert get_type(src, "c") == STR

    def test_ternary(self):
        src = "flag=True\nx = 1 if flag else 2.0"
        t = get_type(src, "x")
        assert isinstance(t, UnionType)
        assert INT in t.types
        assert FLOAT in t.types


# ---------------------------------------------------------------------------
# Run the sample project as an integration test
# ---------------------------------------------------------------------------

class TestSampleProject:
    def test_utils_module(self):
        sample = os.path.join(os.path.dirname(__file__), "sample_project", "utils.py")
        src = open(sample).read()
        result = TypeInferenceVisitor(sample, "utils").infer(src)
        # Module-level constants
        by_name = {qn: sym for qn, sym in result.bindings}
        assert by_name["PI"].inferred_type == FLOAT
        assert by_name["VERSION"].inferred_type == STR
        assert by_name["MAX_RETRIES"].inferred_type == INT
        assert by_name["DEBUG"].inferred_type == BOOL

    def test_models_module(self):
        sample = os.path.join(os.path.dirname(__file__), "sample_project", "models.py")
        src = open(sample).read()
        result = TypeInferenceVisitor(sample, "models").infer(src)
        assert result.class_attrs.get("Counter.count") == INT
        assert result.class_attrs.get("Counter.name") == STR
        assert result.class_attrs.get("Counter.active") == BOOL
        assert result.function_returns.get("Counter.get_name") == STR
        assert result.function_returns.get("Counter.is_active") == BOOL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
