# Symbolic Execution Roadmap

Items are grouped by theme and roughly ordered by dependency. Tick them off as each is completed.

---

## Baseline

- [x] Add `depth`, `memo`, `computing`, and `ast_cache` parameters to `infer_return_with_args`
  - `depth: int` — remaining recursion budget
  - `memo: dict[(def_relpath, def_key, frozenset[arg_items]), TypeExpr]` — cache to avoid re-simulating the same (function, arg-types) pair
  - `computing: set[(def_relpath, def_key, frozenset[arg_items])]` — current call stack; return `UNKNOWN` immediately on re-entry (cycle guard)
  - `ast_cache: dict[relpath, ast.Module]` — parse each source file at most once per run
- [x] Thread the above state into the `_InferVisitor` used during simulation
- [x] Override the project-function branch of `_infer_call`: when `depth > 0`, look up the callee's AST node, check memo and computing, then recurse instead of falling back to `fi.return_type`
- [x] Add `"symbolic-depth": 3` to `_DEFAULT_CONFIG` and write it to newly-created `config.json`
- [x] Read `symbolic-depth` from config in `infer_callsite_returns` and pass it down through the call chain

---

## Simulation fidelity

- [ ] Attribute access on symbolically-typed objects: `x.field` where the type of `x` is a known class should resolve via `ClassInfo.fields` during simulation (currently only works when types come from the registry, not from the local symbolic scope)
- [ ] Method calls on symbolically-typed objects: `x.upper()` where `x: str` during simulation should resolve via `_METHOD_TABLE`
- [ ] Class instantiation within a simulated body: `Foo(args)` should recursively simulate `Foo.__init__` and return `TypeExpr("Foo")`
- [ ] Default argument types: when a call omits an argument that has a default value, infer the type of the default expression and use it as the arg type for that parameter

---

## Control flow

- [ ] `isinstance(x, T)` narrowing: inside the `if isinstance(x, T):` branch, treat `x` as type `T` rather than its declared type
- [ ] Early-return short-circuit: if every reachable path through an `if`/`else` block ends in a `return`, don't union the fall-through `None` into the result
- [ ] Loop body awareness: infer element type from `for item in collection` when the collection type carries a known element type (e.g. `list[int]` → `item: int`)

---

## Recursion handling

- [ ] Fixpoint for self-recursive functions: instead of returning `UNKNOWN` on re-entry, seed the recursive call with the current partial result and iterate until the result stabilises
- [ ] Mutual recursion: extend the fixpoint to groups of mutually-recursive functions (SCCs of the call graph)

---

## Pass integration

- [x] Update the `Call` entry in the **caller** file with the per-callsite return type (currently only `Function.callsites[site].type.usage` in the **callee** file is updated; the corresponding `Call` node in the caller's JSON should reflect the same value)
- [x] Nested callee param back-propagation: re-record callsites after Pass 3c (with now-typed params) and re-union them in a new Pass 3d, so that functions called from typed contexts (e.g. `process(a, b)` inside `execute(a: int, b: str)`) get their param entries populated — uses `preserve_callsite_returns=True` to avoid clobbering symbolic return types
- [ ] Per-callsite inner-variable propagation: for each specific callsite, propagate the context-sensitive types all the way to the variable entries inside the function body, not just the unioned result used by Pass 3c

---

## Configuration

- [ ] `symbolic-depth` (int, default `3`) — maximum call-chain depth to simulate *(added in baseline)*
- [ ] `symbolic-memo-limit` (int, optional) — cap the memo dict size for very large projects to bound memory use

---

## Call resolution

- [ ] Inheritance-aware method lookup: when `obj.method()` is called and `method` is not found directly on `obj`'s class, walk the class's AST base classes and check each ancestor in MRO order. Affects both `goto` on `Call` nodes and return-type resolution in `_infer_call` and `_resolve_callee`.

---

## Advanced / future

- [ ] `*args` / `**kwargs` mapping: spread positional and keyword splats across parameter names where statically determinable
- [ ] Lambda simulation: treat `lambda x: expr` as an anonymous function and simulate its body when called
- [ ] Comprehension element types: infer the element type of list/dict/set comprehensions from the iterator and filter expressions
- [ ] Tuple unpacking: `a, b = expr` where `expr` is a known `tuple[X, Y]` → `a: X`, `b: Y`
