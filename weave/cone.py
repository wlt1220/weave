"""Causal cone analysis over Python source (prototype: ast-based, single file).

Refinement of the full-cone criterion: two intents conflict iff one touches a
node the other *depends on* (transitively) — or the same node. Two intents
touching nodes that merely share a dependency (e.g. both call log()) do NOT
conflict: neither can change the other's behavior.
"""
from __future__ import annotations

import ast


class FuncGraph:
    """Function-level call graph for one file."""

    def __init__(self, source: str):
        self.nodes: dict[str, dict] = {}
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                        calls.add(sub.func.id)
                self.nodes[node.name] = {
                    "calls": calls,
                    "source": ast.get_source_segment(source, node) or "",
                }
        known = set(self.nodes)
        for n in self.nodes.values():
            n["calls"] &= known

    def depends_on(self, a: str, b: str) -> bool:
        """Does `a` transitively call `b`?"""
        seen, stack = set(), [a]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for callee in self.nodes.get(cur, {}).get("calls", ()):
                if callee == b:
                    return True
                stack.append(callee)
        return False

    def influence_cone(self, v: str) -> set[str]:
        """Nodes whose behavior v can change: v + its transitive callers."""
        cone = {v}
        changed = True
        while changed:
            changed = False
            for name, n in self.nodes.items():
                if name not in cone and cone & n["calls"]:
                    cone.add(name)
                    changed = True
        return cone


def find_conflict(graph: FuncGraph, nodes_a: list[str], nodes_b: list[str]):
    """Return (True, (a, b, why)) on first conflict, else (False, (None, None, ''))."""
    for a in nodes_a:
        for b in nodes_b:
            if a == b:
                return True, (a, b, f"same node '{a}'")
            if graph.depends_on(a, b):
                return True, (a, b, f"'{a}' depends on '{b}'")
            if graph.depends_on(b, a):
                return True, (a, b, f"'{b}' depends on '{a}'")
    return False, (None, None, "")


def apply_ops(source: str, ops: list[dict]) -> str:
    """Apply replace_function ops to source. Ops are disjoint by construction."""
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    reps = []
    for op in ops:
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == op["node"]):
                new = op["new_source"]
                reps.append((node.lineno - 1, node.end_lineno,
                             new if new.endswith("\n") else new + "\n"))
    for start, end, new in sorted(reps, reverse=True):
        lines[start:end] = [new]
    return "".join(lines)
