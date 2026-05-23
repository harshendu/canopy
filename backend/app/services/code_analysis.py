"""Static code analysis for drift detection (pure, unit-testable).

The substance of "declared-vs-actual dependencies": parse Python source into the set of
modules it imports, then map those imports onto the components that own them to recover
the *actual* dependency edges between components. The Drift Sentinel (plugin) reads code
via its tools and uses this same shape; the API runs detection over the result.

Only Python is handled here (stdlib `ast`, no extra deps). Other languages can plug in
their own `imports()` later — the edge-mapping below is language-agnostic.
"""

from __future__ import annotations

import ast


def python_imports(source: str) -> set[str]:
    """The set of dotted module names a Python source file imports.

    `import a.b.c` -> {"a.b.c"}; `from a.b import x` -> {"a.b"}. Returns an empty set on
    syntax errors (a malformed file shouldn't crash a scan)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        # Skip relative imports (node.level > 0) — they stay within a component.
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _owner_of(module: str, module_prefixes: dict[int, list[str]]) -> int | None:
    """The component whose prefix most specifically owns `module` (longest match wins)."""
    best: int | None = None
    best_len = -1
    for component_id, prefixes in module_prefixes.items():
        for prefix in prefixes:
            if (module == prefix or module.startswith(prefix + ".")) and len(prefix) > best_len:
                best = component_id
                best_len = len(prefix)
    return best


def actual_edges(
    component_imports: dict[int, set[str]],
    module_prefixes: dict[int, list[str]],
) -> set[tuple[int, int]]:
    """Recover component-to-component edges from observed imports.

    `component_imports`: the modules each component's code imports.
    `module_prefixes`: the module prefixes each component owns (from its code bindings).
    An edge (A, B) means code in A imports a module owned by B (A != B).
    """
    edges: set[tuple[int, int]] = set()
    for source_id, modules in component_imports.items():
        for module in modules:
            target_id = _owner_of(module, module_prefixes)
            if target_id is not None and target_id != source_id:
                edges.add((source_id, target_id))
    return edges
