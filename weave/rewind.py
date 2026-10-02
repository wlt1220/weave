"""weave rewind: excise the cells polluted by a bad intent, re-fold the rest.

Event-sourcing honest: the log is append-only — rewind never deletes history.
The bad intent is added to the fold's `reverted` set and skipped on every
(re)fold. Pollution flows downstream: the bad intent's nodes plus every node
that transitively *depends on* them (callers). Dependencies of the bad nodes
are unaffected (their source and behavior don't change).

Cells outside the polluted cone are byte-identical after rewind — the rewind
is incremental by construction.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .cell import (canonical_source, compute_cell_id, node_id, node_source,
                   node_span)
from .cone import FuncGraph
from .intent import Intent
from .fold import Fold


@dataclass
class RewindReport:
    bad_id: str
    bad_goal: str
    affected: list[str]                 # node_ids in the polluted cone
    restored: list[dict]               # per cell: node_id, old/new cell_id, slice
    downstream: list[Intent] = field(default_factory=list)  # built on pollution
    untouched_cells: int = 0


def _touched_nodes(intent: Intent) -> set[str]:
    return {node_id(op["file"], op["node"]) for op in intent.operations
            if op.get("file") and op.get("node")}


def _touches(intent: Intent, file: str, node: str) -> bool:
    return any(op.get("file") == file and op.get("node") == node
               for op in intent.operations)


def _last_source(intent: Intent, file: str, node: str) -> str | None:
    """Canonical new_source of the intent's last op touching (file, node)."""
    out = None
    for op in intent.operations:
        if op.get("file") == file and op.get("node") == node \
                and "new_source" in op:
            out = canonical_source(op["new_source"])
    return out


def compute_affected_nodes(sources: dict[str, str],
                           bad_nodes: set[str]) -> set[str]:
    """Bad nodes + every node that transitively depends on them (callers)."""
    affected = set(bad_nodes)
    for file, source in sources.items():
        try:
            graph = FuncGraph(source)
        except SyntaxError:
            continue
        local_bad = [b.split(":", 1)[1] for b in bad_nodes
                     if b.startswith(file + ":")]
        if not local_bad:
            continue
        for node in graph.nodes:
            nid = node_id(file, node)
            if nid in affected:
                continue
            if any(graph.depends_on(node, b) for b in local_bad):
                affected.add(nid)
    return affected


def rewind_fold(fold: Fold, intents_in_order: list[Intent],
                bad_id: str) -> RewindReport:
    """Excise `bad_id` from the fold, recomputing only the polluted cone.

    `intents_in_order` must be the folded log prefix in order. The bad intent
    is added to `fold.reverted` (append-only log: history is never deleted).
    Returns a report; unaffected cells are byte-identical.
    """
    by_id = {it.id: it for it in intents_in_order if it.id}
    if bad_id not in by_id:
        raise KeyError(f"intent {bad_id} not in folded log")
    if bad_id in fold.reverted:
        raise ValueError(f"intent {bad_id[:12]} already reverted")
    bad = by_id[bad_id]
    bad_nodes = _touched_nodes(bad)

    sources = fold.materialize()  # pre-rewind state, for the call graph
    affected = compute_affected_nodes(sources, bad_nodes)
    dependents = affected - bad_nodes

    fold.reverted.add(bad_id)
    order_index = {it.id: i for i, it in enumerate(intents_in_order) if it.id}
    bad_idx = order_index[bad_id]

    restored = []
    for nid in sorted(affected):
        cell = fold.cells.get(nid)
        if cell is None:
            continue
        old_cell_id = cell.cell_id
        remaining = [it for it in intents_in_order
                     if it.id and it.id != bad_id and it.id not in fold.reverted
                     and _touches(it, cell.file, cell.node)]
        new_ids = [it.id for it in remaining]
        new_source = canonical_source(
            node_source(fold.base_sources.get(cell.file, ""), cell.node) or "")
        for it in remaining:
            s = _last_source(it, cell.file, cell.node)
            if s is not None:
                new_source = s
        cell.intent_ids = new_ids
        cell.source = new_source
        cell.state_hash = hashlib.sha256(new_source.encode("utf-8")).hexdigest()
        cell.cell_id = compute_cell_id(cell.file, cell.node, new_ids,
                                       cell.state_hash)
        restored.append({"node_id": nid, "old_cell_id": old_cell_id,
                         "new_cell_id": cell.cell_id, "slice": new_ids})

    downstream = [it for it in intents_in_order
                  if it.id and it.id != bad_id and it.id not in fold.reverted
                  and order_index.get(it.id, -1) > bad_idx
                  and (_touched_nodes(it) & dependents)]

    return RewindReport(
        bad_id=bad_id, bad_goal=bad.goal, affected=sorted(affected),
        restored=restored, downstream=downstream,
        untouched_cells=len(fold.cells) - len(restored),
    )
