"""Spacetime cells (时空胞): the unifying data-model frame (DESIGN.md §3).

A cell is the smallest addressable unit of the repo spacetime:

    cell = (node, intent_slice) -> state of that code region during that slice

    cell_id = sha256(node_id + intent_ids + state_hash)

Space axis: AST nodes (``file:function``). Time axis: the intent log.
Every Weave feature is a cell operation: fold takes the present slice of every
cell, ``weave why`` is cell lookup, a causal cone is the set of cells causally
downstream of a change, rewind excises polluted cells, negotiation decides
which lineage of overlapping cells survives, and the ghost bank archives the
losing cells.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field

from .intent import Intent


def node_id(file: str, node: str) -> str:
    """Address of a code region on the space axis: ``payments.py:charge``."""
    return f"{file}:{node}"


def canonical_source(source: str) -> str:
    """Canonical cell state: source text without trailing newlines.

    Both ``weave why`` (AST segment) and ``weave fold`` (op new_source) must
    hash the same bytes for the same cell, or cell_ids diverge.
    """
    return source.rstrip("\n")


def compute_cell_id(file: str, node: str, intent_ids: list[str],
                    state_hash: str) -> str:
    """Content-address a cell: same (node, slice, state) -> same id."""
    h = hashlib.sha256()
    h.update(node_id(file, node).encode("utf-8"))
    h.update(b"\x00")
    h.update("\x00".join(intent_ids).encode("utf-8"))
    h.update(b"\x00")
    h.update(state_hash.encode("utf-8"))
    return h.hexdigest()


def find_node(source: str, line: int) -> str | None:
    """Innermost function definition containing 1-based `line`, or None."""
    tree = ast.parse(source)
    best: ast.FunctionDef | None = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.lineno <= line <= (n.end_lineno or n.lineno):
                # innermost def starts latest
                if best is None or n.lineno >= best.lineno:
                    best = n
    return best.name if best else None


def node_source(source: str, node: str) -> str | None:
    """Current source text of `node` in `source`, or None if absent."""
    tree = ast.parse(source)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == node:
            return ast.get_source_segment(source, n)
    return None


def node_span(source: str, node: str) -> tuple[int, int] | None:
    tree = ast.parse(source)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and n.name == node:
            return (n.lineno, n.end_lineno or n.lineno)
    return None


@dataclass
class Cell:
    """One spacetime cell: a code region + the intent slice that made it."""
    file: str
    node: str
    intent_ids: list[str]          # the slice, in log order
    state_hash: str                # sha256 of the node's current source
    cell_id: str                   # content address of the cell
    span: tuple[int, int] | None = None
    source: str = ""               # the node's current source text
    intents: list[Intent] = field(default_factory=list)  # resolved, for display

    @property
    def nid(self) -> str:
        return node_id(self.file, self.node)

    def to_dict(self) -> dict:
        return {
            "file": self.file, "node": self.node,
            "intent_ids": self.intent_ids, "state_hash": self.state_hash,
            "cell_id": self.cell_id,
            "span": list(self.span) if self.span else None,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Cell":
        sp = d.get("span")
        return cls(
            file=d["file"], node=d["node"], intent_ids=d["intent_ids"],
            state_hash=d["state_hash"], cell_id=d["cell_id"],
            span=(sp[0], sp[1]) if sp else None, source=d.get("source", ""),
        )


def _touches(intent: Intent, file: str, node: str) -> bool:
    return any(op.get("file") == file and op.get("node") == node
               for op in intent.operations)


def resolve_cell(file: str, target: int | str, sources: dict[str, str],
                 intents: list[Intent]) -> Cell | None:
    """Resolve ``file:line`` (or ``file:node``) to its current spacetime cell.

    `sources` maps file -> current (folded) source; `intents` is the log in
    order. The cell's slice is every intent (in log order) whose operations
    touch the node; the state is the node's current source text.
    """
    source = sources.get(file)
    if source is None:
        return None
    node = target if isinstance(target, str) else find_node(source, target)
    if node is None or node_source(source, node) is None:
        return None
    touching = [it for it in intents if _touches(it, file, node)]
    src = canonical_source(node_source(source, node) or "")
    state_hash = hashlib.sha256(src.encode("utf-8")).hexdigest()
    intent_ids = [it.id for it in touching if it.id]
    return Cell(
        file=file,
        node=node,
        intent_ids=intent_ids,
        state_hash=state_hash,
        cell_id=compute_cell_id(file, node, intent_ids, state_hash),
        span=node_span(source, node),
        source=src,
        intents=touching,
    )
