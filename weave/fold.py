"""Incremental per-cell fold: the materialized view over the intent log.

``state = fold(intents)`` — but computed per spacetime cell, not as one
amorphous replay. Each cell caches its (slice, state, cell_id); when new
intents arrive only the cells they touch are recomputed. Everything else is
byte-identical, by content addressing.

Prototype semantics: the working tree at first fold is genesis (the base);
after that the fold owns the working tree — ``weave fold`` rewrites files
from the fold. The intent log stays the source of truth.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field

from .cell import (Cell, canonical_source, compute_cell_id, node_id,
                   node_source, node_span)
from .cone import apply_ops
from .intent import Intent


def _all_nodes(source: str) -> list[str]:
    tree = ast.parse(source)
    return [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _state_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass
class Fold:
    """The materialized view: per-cell cache over a prefix of the intent log."""
    base_sources: dict[str, str] = field(default_factory=dict)
    cells: dict[str, Cell] = field(default_factory=dict)  # keyed by node_id
    log_pos: int = 0                                       # intents folded
    reverted: set[str] = field(default_factory=set)        # excised intent ids

    # ---- construction ----

    @classmethod
    def build(cls, base_sources: dict[str, str],
              intents: list[Intent]) -> "Fold":
        """Full fold from genesis. `intents` in log order."""
        fold = cls(base_sources=dict(base_sources))
        fold._init_cells()
        fold.advance(intents)
        return fold

    def _init_cells(self) -> None:
        for file, source in self.base_sources.items():
            touched_nodes = {n for n in _all_nodes(source)}
            for node in touched_nodes:
                src = canonical_source(node_source(source, node) or "")
                h = _state_hash(src)
                self.cells[node_id(file, node)] = Cell(
                    file=file, node=node, intent_ids=[], state_hash=h,
                    cell_id=compute_cell_id(file, node, [], h),
                    span=node_span(source, node), source=src)

    # ---- incremental ----

    def advance(self, intents: list[Intent]) -> list[str]:
        """Fold `intents` (next in log order) incrementally.

        Returns the dirty cell ids — the only cells recomputed.
        Reverted intents are skipped (rewind is append-only).
        """
        dirty: list[str] = []
        for it in intents:
            self.log_pos += 1
            if not it.id or it.id in self.reverted:
                continue
            for op in it.operations:
                file, node = op.get("file"), op.get("node")
                if not file or not node or "new_source" not in op:
                    continue
                key = node_id(file, node)
                cell = self.cells.get(key)
                if cell is None:
                    # brand-new node (not in genesis): empty base state
                    cell = Cell(file=file, node=node, intent_ids=[],
                                state_hash=_state_hash(""),
                                cell_id=compute_cell_id(file, node, [], _state_hash("")),
                                source="")
                    self.cells[key] = cell
                new_source = canonical_source(op["new_source"])
                if it.id and (not cell.intent_ids
                              or cell.intent_ids[-1] != it.id):
                    cell.intent_ids = [*cell.intent_ids, it.id]
                cell.source = new_source
                cell.state_hash = _state_hash(new_source)
                cell.cell_id = compute_cell_id(file, node, cell.intent_ids,
                                               cell.state_hash)
                cell.span = node_span(self.base_sources.get(file, ""), node) \
                    or cell.span
                if key not in dirty:
                    dirty.append(key)
        return dirty

    # ---- materialization ----

    def materialize(self) -> dict[str, str]:
        """Render the fold back to {file: source}."""
        out = {}
        for file, base in self.base_sources.items():
            touched = [c for c in self.cells.values()
                       if c.file == file and c.intent_ids]
            known = {c.node for c in touched
                     if node_source(base, c.node) is not None}
            ops = [{"node": c.node, "new_source": c.source} for c in touched
                   if c.node in known]
            src = apply_ops(base, ops) if ops else base
            new_nodes = [c for c in touched if c.node not in known]
            if new_nodes:
                src = (src.rstrip("\n") + "\n\n"
                       + "\n\n".join(c.source.rstrip("\n") for c in new_nodes)
                       + "\n")
            out[file] = src
        return out

    # ---- persistence ----

    def to_dict(self) -> dict:
        return {
            "log_pos": self.log_pos,
            "reverted": sorted(self.reverted),
            "base_sources": self.base_sources,
            "cells": {k: c.to_dict() for k, c in self.cells.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Fold":
        return cls(
            base_sources=d.get("base_sources", {}),
            cells={k: Cell.from_dict(v) for k, v in d.get("cells", {}).items()},
            log_pos=d.get("log_pos", 0),
            reverted=set(d.get("reverted", [])),
        )
