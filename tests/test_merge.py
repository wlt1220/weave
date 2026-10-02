from weave import cli
from weave.merge import fold_intents, try_merge


def _intent(goal, agent, node, src, rationale, verified):
    return cli._mk_intent(goal, agent, node, src, rationale, verified)


def test_merge_disjoint_cones():
    a = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    b = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    res = try_merge(a, b, {"payments.py": cli.DEMO_SOURCE})
    assert res.merged is not None and res.decision is None
    assert res.merged.verified
    assert set(res.merged.parents) == {a.id, b.id}


def test_merge_unverified_parent_marks_fold():
    a = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    b = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", False)
    res = try_merge(a, b, {"payments.py": cli.DEMO_SOURCE})
    assert res.merged is not None and not res.merged.verified


def test_negotiation_verified_wins():
    a = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    c = _intent("c", "agent-3", "charge", cli.CHARGE_FEE, "r3", False)
    res = try_merge(a, c, {"payments.py": cli.DEMO_SOURCE})
    assert res.merged is None and res.decision is not None
    assert res.decision.outcome == "merged"
    assert res.decision.winner == a.id
    assert len(res.decision.ghost_genes) == 1


def test_negotiation_tie_escalates():
    a = _intent("a", "agent-4", "log", cli.LOG_STRUCTURED, "r4", True)
    b = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    res = try_merge(a, b, {"payments.py": cli.DEMO_SOURCE})
    assert res.decision is not None
    assert res.decision.outcome == "escalated"
    assert "refund" in res.decision.human_context
