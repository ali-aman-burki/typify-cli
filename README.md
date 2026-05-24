# typify-prototype

Prototype backend CLI for **Typify**, a lightweight usage-driven static analyzer for precise Python type inference. Published at the *34th IEEE/ACM International Conference on Program Comprehension (ICPC 2026)*, Rio de Janeiro, Brazil.

Typify infers types for variables, function parameters, and return values in unannotated Python codebases using symbolic execution, fixpoint analysis, and cross-module dependency resolution — no training data or existing annotations required.

Given a Python project directory, the tool produces a JSON file per source file describing inferred types at every resolved identifier, plus a top-level `index.json`. This output is intended to be consumed by the **Typify VS Code extension**. See [schema.md](schema.md) for the full output format.

## Usage

```
typify-prototype <project_directory> <output_directory>
```
