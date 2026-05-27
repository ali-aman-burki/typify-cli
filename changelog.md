# Changelog

## Baseline

### Literal types
- Integer, float, string, bytes, bool, and `None` constants are assigned their exact types (`int`, `float`, `str`, `bytes`, `bool`, `None`).

### Collection literals
- `[1, 2, 3]` → `list[int]`
- `{"a": 1}` → `dict[str, int]`
- `{1, 2}` → `set[int]`
- `(1, "x")` → `tuple[Union[int, str]]`
- Element types are unioned when heterogeneous (e.g. `[1, "a"]` → `list[Union[int, str]]`).
- Empty or fully-unknown-element collections fall back to the bare container type (e.g. `list`).

### Assignment propagation
- Simple name assignments (`x = expr`) propagate the inferred type of the right-hand side into the name's entry and the local scope.
- Annotated assignments (`x: int = 0`) use the annotation as the type; the annotation takes precedence over the inferred value type.
- Augmented assignments (`x += expr`) are visited for side-effect entry updates but do not change the stored type of the target.
- `self.field = expr` assignments inside methods update the class's field table so attribute accesses on instances can resolve the type.

### Annotation harvesting
- Explicit type annotations on function parameters (`def f(x: int)`) are used directly, even in otherwise unannotated code.
- Function return annotations (`def f() -> str`) are used as the function's type.
- PEP 604 union syntax (`X | Y`) in annotations is parsed and represented as `Union[X, Y]`.
- Subscript annotations (`list[int]`, `dict[str, float]`, `Optional[str]`) are parsed recursively.

### Class instantiation
- `x = Foo()` where `Foo` is a class defined anywhere in the project → `x: Foo`.

### Attribute access
- `x.field` where the type of `x` is a known class and `field` was assigned in `__init__` → resolves to the field's type.
- Chained access (`a.b.c`) resolves each step in turn as long as the intermediate types are known.

### Return type inference
- Return types are inferred by unioning the inferred types of all `return` expressions in a function body.
- Nested function bodies are excluded from the enclosing function's return-type collection.
- Control-flow sub-bodies (`if`, `for`, `while`, `with`, `try`) are traversed for return statements.
- Inferred return types are written back to the registry so other functions calling this one can benefit within the same pass.

### Built-in function return types
The following built-ins have hardcoded return types:

| Built-in | Return type |
|---|---|
| `len`, `id`, `hash`, `ord`, `round` | `int` |
| `abs`, `sum` | `int` |
| `str`, `repr`, `format`, `chr`, `hex`, `oct`, `bin` | `str` |
| `float` | `float` |
| `bool`, `isinstance`, `issubclass`, `hasattr`, `callable`, `any`, `all` | `bool` |
| `int` | `int` |
| `list`, `sorted`, `dir` | `list` |
| `dict`, `vars` | `dict` |
| `set` | `set` |
| `tuple` | `tuple` |
| `bytes` | `bytes` |
| `input` | `str` |
| `type` | `type` |
| `print` | `None` |
| `open` | `IO` |
| `range` | `range` |
| `enumerate` | `enumerate` |
| `zip` | `zip` |
| `map` | `map` |
| `filter` | `filter` |
| `reversed` | `reversed` |

### Method return types
Common methods on `str`, `bytes`, `list`, `dict`, and `set` have hardcoded return types. Selected examples:

| Receiver | Method | Return type |
|---|---|---|
| `str` | `upper`, `lower`, `strip`, `replace`, `join`, `format`, … | `str` |
| `str` | `split`, `rsplit`, `splitlines` | `list[str]` |
| `str` | `encode` | `bytes` |
| `str` | `startswith`, `endswith`, `isdigit`, … | `bool` |
| `str` | `find`, `rfind`, `index`, `count` | `int` |
| `bytes` | `decode` | `str` |
| `list` | `append`, `extend`, `insert`, `sort`, `reverse`, `clear` | `None` |
| `list` | `count`, `index` | `int` |
| `list` | `pop` | element type (if known from `list[T]`) |
| `dict` | `keys` | `KeysView` |
| `dict` | `values` | `ValuesView` |
| `dict` | `items` | `ItemsView` |
| `dict` | `get`, `pop`, `setdefault` | value type (if known from `dict[K, V]`) |
| `set` | `add`, `remove`, `discard`, `clear` | `None` |
| `set` | `union`, `intersection`, `difference`, `copy` | `set` |
| `set` | `issubset`, `issuperset`, `isdisjoint` | `bool` |

### Arithmetic / binary operations
- Same-type operands for `int`, `float`, `complex`, `str`, `bytes`, `list` return the same type.
- Mixed numeric operands follow Python's coercion order: `complex` > `float` > `int`.
- `"fmt" % args` → `str`.

### Other expression types
- f-strings → `str`
- `not expr` → `bool`
- Comparison expressions → `bool`
- `x and y`, `x or y` → union of operand types
- Ternary `a if cond else b` → union of branch types
- Lambda → `Callable`
- List/dict/set comprehensions → `list` / `dict` / `set` (element type not yet inferred)
- Generator expressions → `Generator`

### `self` type inside methods
- Inside a method, `self` is typed as the enclosing class, enabling attribute lookups on `self.field`.

### Multi-pass architecture
- **Pass 1 (collect):** all files are walked first to populate a project-wide registry of class definitions (with field types from `__init__`), and function signatures. This means a class defined in file B is known when inferring types in file A.
- **Pass 2 (infer):** per-file type inference runs after the full registry is built, so cross-file class instantiation and field resolution work.

### What is not yet inferred (left blank)
- For/with loop target variable types
- Tuple unpacking (`a, b = expr`)
- Callsite-driven parameter inference
- Types that require control-flow sensitivity (variable re-assigned under `if`)
- Comprehension element types
- `*args` / `**kwargs` parameter types
- Inferred types from exception handlers
- Third-party library imports (only intra-project imports are resolved)

---

## Cross-module inference

### Module index
- At the start of Pass 1, all source file paths are converted to dotted module names (`foo/bar.py` → `foo.bar`, `foo/__init__.py` → `foo`) and stored in a project-wide index. This index is used to resolve import statements to concrete relpaths.

### Import resolution
- `from foo.bar import MyClass` — the local name `MyClass` is mapped to its definition relpath and original name. Subsequent calls `MyClass()` resolve to `TypeExpr("MyClass")` and attribute accesses `obj.field` resolve through `MyClass`'s field table.
- `from foo.bar import some_func` — the local name `some_func` is resolved to its `FuncInfo`. Calls `some_func()` return its inferred return type.
- `import foo.bar` / `import utils` — the module alias is mapped to the source relpath. `module.SomeClass()` resolves to `TypeExpr("SomeClass")`; `module.some_func()` resolves to the function's return type; `module.SomeClass` (bare read) resolves to `TypeExpr("SomeClass")`.
- Relative imports (`from . import X`, `from .sibling import X`) are resolved to absolute module names using the current file's package path, then looked up in the module index.

### Cross-file return type pre-computation
- During Pass 1, function return types are pre-populated from return annotations (`-> T`) and from literal-only `return` expressions. This ensures that when file A calls a function defined in file B, the return type is already available when file A is processed in Pass 2, regardless of file processing order.

### Module-level variable access
- `import main; w = main.x` — if `x` is assigned a literal value at module level in `main.py` (e.g. `x = 2`), `main.x` resolves to `int`. Annotated module-level variables (`x: int = 2`) are also captured using the annotation.
- Applies to all primitive and collection literals assigned at the top level of any file in the project.

### What cross-module inference does not cover
- `from module import *` (star imports are skipped)
- Third-party or stdlib imports (only files within the project directory are indexed)
- Re-exports: if `foo/__init__.py` imports `Bar` from `foo/bar.py` and re-exports it, `from foo import Bar` resolves to `foo/__init__.py` which may not have `Bar` in its own registry — the original definition in `foo/bar.py` would not be found
