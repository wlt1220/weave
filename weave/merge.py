"""Intent merge engine: disjoint cones merge lock-free, overlap negotiates."""
from __future__ import annotations

from dataclasses import dataclass

from .cone import FuncGraph, apply_ops, find_conflict
from .intent import Intent, Verification
from .negotiate import DecisionRecord, NegotiationSession, RuleArbiter


@dataclass
class MergeResult:
    merged: Intent | None
    decision: DecisionRecord | None
    detail: str = ""


def _nodes_of(intent: Intent, fname: str) -> list[str]:
    return [op["node"] for op in intent.operations
            if op.get("file") == fname and "node" in op]


def fold_intents(a: Intent, b: Intent) -> Intent:
    """Combine two disjoint intents. Merged intent is verified only if both are."""
    return Intent(
        goal=f"{a.goal} + {b.goal}",
        author=a.author,  # the fold is a system act; keep first author for prototype
        plan=a.plan + b.plan,
        operations=a.operations + b.operations,
        verification=Verification(
            tests=a.verification.tests + b.verification.tests
                  if a.verification and b.verification else [],
            passed=bool(a.verified and b.verified),
            sandbox="fold",
        ),
        rationale=f"auto-merge (disjoint cones): [{a.rationale}] + [{b.rationale}]",
        parents=[x for x in (a.id, b.id) if x],
        stream=a.stream,
    ).seal()


def try_merge(intent_a: Intent, intent_b: Intent, sources: dict[str, str],
              arbiter=None) -> MergeResult:
    """Attempt to merge two intents over {file: source}."""
    arbiter = arbiter or RuleArbiter()
    for op in intent_a.operations:
        op.setdefault("intent", intent_a.id[:12])
    for op in intent_b.operations:
        op.setdefault("intent", intent_b.id[:12])

    files = {op.get("file") for op in intent_a.operations + intent_b.operations}
    for fname in files:
        if fname not in sources:
            continue
        graph = FuncGraph(sources[fname])
        hit, (a, b, why) = find_conflict(graph,
                                         _nodes_of(intent_a, fname),
                                         _nodes_of(intent_b, fname))
        if hit:
            session = NegotiationSession(
                intent_a, intent_b,
                reason=f"{why} in {fname}")
            decision = session.run(arbiter)
            return MergeResult(None, decision,
                               detail=f"overlap: {why} in {fname}")
    return MergeResult(fold_intents(intent_a, intent_b), None,
                       detail="disjoint cones — merged lock-free")
