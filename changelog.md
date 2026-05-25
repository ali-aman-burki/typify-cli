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
- Cross-file function return types (return types are propagated within a file only)
- Callsite-driven parameter inference
- Import resolution (imported names have no type)
- Types that require control-flow sensitivity (variable re-assigned under `if`)
- Comprehension element types
- `*args` / `**kwargs` parameter types
- Inferred types from exception handlers
