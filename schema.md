# Output Schema

The tool takes a directory of Python source files and produces a JSON file per source file, plus a top-level `index.json`. All paths written into the data are relative to the input directory.

---

## index.json

A single flat object mapping each source file (relative path) to its output JSON filename.

```json
{
  "core/main.py":     "0.json",
  "utils/helpers.py": "1.json"
}
```

---

## Per-file JSON

Each source file produces one JSON object. The keys are source locations in `"line:col"` format, pointing to every identifier the AST visitor resolved in that file. The values are entry objects whose shape depends on the `node_type`.

```json
{
  "line:col": { ...entry },
  "line:col": { ...entry }
}
```

Entries are sorted by source position (line, then column).

---

## Entry object

Every entry has these three fields:

| Field | Type | Description |
|---|---|---|
| `scope` | `string` | Dot-separated scope path at the point of definition, e.g. `"F:my_func"` or `"C:MyClass.F:method"`. Empty string at module level. |
| `identifier` | `string` | The name of the symbol as it appears in source. |
| `node_type` | `string` | One of `Name`, `Call`, `Parameter`, `Function`, `Class`. |

Additional fields appear depending on `node_type`:

| Field | Present on | Type | Description |
|---|---|---|---|
| `type` | All except `Class` | `object` | Type information for this symbol (see below). |
| `goto` | `Name`, `Call` | `string` | Definition site: `"relpath:line:col"`. |
| `params` | `Function` | `object` | Declared parameter names mapped to their type objects. |
| `callsites` | `Function` | `object` | All observed call sites (see below). |

### `type` object

| Field | Type | Description |
|---|---|---|
| `usage` | `string` | Type inferred from usage/context analysis. Empty string if not resolved. |
| `retrieved` | `object` | Type candidates surfaced by the retrieval system, keyed by type name. Each value is `{"score": float, "hits": int}`. Empty object `{}` until retrieval runs. Candidates are ordered by descending score (insertion order). |

---

## node_type reference

### `Name`
A bare name expression or attribute access — a symbol being read or written.

```json
"14:4": {
  "scope":       "F:main",
  "identifier":  "result",
  "node_type":   "Name",
  "type": {
    "usage": "Optional[int]",
    "retrieved": {
      "int":           { "score": 14.2, "hits": 4 },
      "Optional[int]": { "score": 9.1,  "hits": 2 },
      "str":           { "score": 3.0,  "hits": 1 }
    }
  },
  "goto": "utils/helpers.py:38:0"
}
```

---

### `Call`
A function being invoked at this position.

```json
"27:8": {
  "scope":       "F:main",
  "identifier":  "process",
  "node_type":   "Call",
  "type":        { "usage": "list[str]", "retrieved": {} },
  "goto":        "core/ops.py:12:4"
}
```

---

### `Parameter`
A formal parameter in a function signature.

```json
"6:12": {
  "scope":       "F:parse",
  "identifier":  "text",
  "node_type":   "Parameter",
  "type":        { "usage": "str", "retrieved": {} }
}
```

Note: `Parameter` has no `goto` field.

---

### `Function`
A function (or async function) definition. Has `params` and `callsites` instead of `goto`.

```json
"5:4": {
  "scope":       "",
  "identifier":  "parse",
  "node_type":   "Function",
  "type":        { "usage": "dict[str, Any]", "retrieved": {} },
  "params": {
    "text":  { "usage": "str", "retrieved": {} },
    "limit": { "usage": "Optional[int]", "retrieved": {} }
  },
  "callsites": {
    "core/main.py:42:8": {
      "params": {
        "text":  { "usage": "bytes", "retrieved": {} },
        "limit": { "usage": "int", "retrieved": {} }
      },
      "type": { "usage": "dict[int, float]", "retrieved": {} }
    },
    "tests/test_parse.py:17:4": {
      "params": {
        "text":  { "usage": "str", "retrieved": {} },
        "limit": { "usage": "None", "retrieved": {} }
      },
      "type": { "usage": "dict[str, Any]", "retrieved": {} }
    }
  }
}
```

`params` represents the declared (definition-site) types of each parameter.

`callsites` is keyed by location strings (`"relpath:line:col"`). Each value has a `params` mapping (parameter names to the types passed at that call site) and a `type` field (the return type observed at that call site). Different call sites may supply different types for the same parameter or observe different return types, which is the primary signal this schema is designed to capture.

---

### `Class`
A class definition. Has neither `type` nor `goto`.

```json
"3:6": {
  "scope":       "",
  "identifier":  "MyProcessor",
  "node_type":   "Class"
}
```

---

## Location string format

Locations appear as values of `goto` and as keys in `callsites`:

```
relpath/to/file.py:line:col
```

- **relpath** — path to the source file, relative to the input directory, using the OS path separator.
- **line** — 1-based line number.
- **col** — 0-based column offset.
