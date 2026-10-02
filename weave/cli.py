"""weave CLI (prototype)."""
from __future__ import annotations

import argparse
import os
import sys

from .intent import Author, Intent, Verification
from .store import Store

DEFAULT_DIR = os.path.join(os.getcwd(), ".weave")


def find_root() -> str:
    d = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(d, ".weave")):
            return os.path.join(d, ".weave")
        parent = os.path.dirname(d)
        if parent == d:
            raise SystemExit("not a weave repo (run `weave init`)")
        d = parent


def cmd_init(args):
    Store.init(DEFAULT_DIR)
    print(f"initialized weave repo in {DEFAULT_DIR}")


def cmd_commit_intent(args):
    store = Store.open(find_root())
    head = store.head(args.stream)
    intent = Intent(
        goal=args.goal,
        author=Author(agent_id=args.author, model=args.model),
        plan=args.plan.split("|") if args.plan else [],
        rationale=args.rationale or "",
        parents=[head] if head else [],
        stream=args.stream,
        verification=Verification(tests=[], passed=args.verified,
                                  sandbox=args.sandbox or ""),
    ).seal()
    if not intent.verified:
        print("warning: intent has no passing verification; "
              "it cannot integrate to trunk (verification is versioned).")
    iid = store.put(intent)
    print(f"intent {iid[:12]} committed to stream '{args.stream}'")


def cmd_log(args):
    store = Store.open(find_root())
    for e in store.log(args.stream):
        flag = "✓" if store.get(e["id"]).verified else "○"
        print(f"{flag} {e['id'][:12]} [{e['stream']}] {e['goal']}")


def cmd_why(args):
    # prototype: show intents touching a path (operations carry file paths)
    store = Store.open(find_root())
    hits = []
    for e in store.log():
        it = store.get(e["id"])
        if any(args.path in str(op) for op in it.operations):
            hits.append(it)
    if not hits:
        print(f"no intents found touching {args.path}")
        return
    for it in hits:
        print(f"intent {it.id[:12]} — {it.goal}")
        print(f"  author: {it.author.agent_id} ({it.author.model})")
        print(f"  rationale: {it.rationale or '(none recorded)'}")
        print(f"  verified: {it.verified}")


DEMO_SOURCE = '''\
def log(msg):
    print(f"[log] {msg}")


def charge(amount):
    log(f"charging {amount}")
    return {"status": "ok", "amount": amount}


def refund(tx_id):
    log(f"refunding {tx_id}")
    return {"status": "refunded", "tx": tx_id}
'''

CHARGE_IDEMPOTENT = '''\
def charge(amount, idem_key=None):
    log(f"charging {amount} key={idem_key}")
    return {"status": "ok", "amount": amount, "idem_key": idem_key}
'''

REFUND_AUDIT = '''\
def refund(tx_id, audit=True):
    log(f"refunding {tx_id}")
    entry = {"status": "refunded", "tx": tx_id}
    if audit:
        log(f"audit: refund {tx_id}")
    return entry
'''

CHARGE_FEE = '''\
def charge(amount):
    log(f"charging {amount}")
    fee = round(amount * 0.029 + 0.30, 2)
    return {"status": "ok", "amount": amount, "fee": fee}
'''

LOG_STRUCTURED = '''\
def log(msg):
    print("[LOG] " + str(msg).upper())
'''


def _mk_intent(goal, agent, node, new_source, rationale, verified):
    from .intent import Verification
    op = {"op": "replace_function", "file": "payments.py",
          "node": node, "new_source": new_source}
    return Intent(
        goal=goal,
        author=Author(agent_id=agent, model="claude-opus"),
        operations=[op],
        rationale=rationale,
        verification=Verification(tests=["test_payments.py"],
                                  passed=verified, sandbox="sbx-demo"),
        stream="payments",
    ).seal()


def cmd_demo(args):
    from .cone import apply_ops
    from .merge import try_merge
    import time

    print("=" * 64)
    print("WEAVE DEMO — causal-cone merge vs negotiation")
    print("=" * 64)

    # ---- Scenario 1: disjoint cones → lock-free merge ----
    print("\n--- Scenario 1: two agents, disjoint cones → auto-merge ---")
    a1 = _mk_intent("add idempotency key to charge", "agent-1", "charge",
                    CHARGE_IDEMPOTENT,
                    "200k req/day hit double-charge on retries; key makes it safe",
                    verified=True)
    a2 = _mk_intent("add audit trail to refund", "agent-2", "refund",
                    REFUND_AUDIT,
                    "finance requires an audit trail on every refund",
                    verified=True)
    t0 = time.perf_counter()
    res = try_merge(a1, a2, {"payments.py": DEMO_SOURCE})
    dt = (time.perf_counter() - t0) * 1000
    print(f"cone(charge) ∩ cone(refund): no dependency either way")
    print(f"→ {res.detail} ({dt:.1f}ms)")
    merged_src = apply_ops(apply_ops(DEMO_SOURCE, a1.operations), a2.operations)
    import ast as _ast
    _ast.parse(merged_src)  # must still compile
    print("✓ merged file compiles; trunk holds both intents")

    # ---- Scenario 2: same node → negotiation, verified wins ----
    print("\n--- Scenario 2: same node, one verified → negotiation ---")
    a3 = _mk_intent("fix cross-border fee calc", "agent-3", "charge",
                    CHARGE_FEE,
                    "fee was flat 2%; cross-border needs 2.9% + 30c",
                    verified=False)
    res2 = try_merge(a1, a3, {"payments.py": DEMO_SOURCE})
    print(f"→ {res2.detail}")
    d = res2.decision
    for t in d.transcript:
        print(f"  [{t['speaker']}] {t['message']}")
    print(f"  outcome={d.outcome} winner={d.winner[:12] if d.winner else None} "
          f"ghost_genes={len(d.ghost_genes)}")

    # ---- Scenario 3: dependency cone → negotiation → escalate ----
    print("\n--- Scenario 3: dependency overlap, both verified → escalate ---")
    a4 = _mk_intent("normalize log format", "agent-4", "log",
                    LOG_STRUCTURED,
                    "new log pipeline requires uppercase normalized lines",
                    verified=True)
    res3 = try_merge(a4, a2, {"payments.py": DEMO_SOURCE})
    print(f"→ {res3.detail}")
    d3 = res3.decision
    for t in d3.transcript:
        print(f"  [{t['speaker']}] {t['message']}")
    print(f"  outcome={d3.outcome}")
    print(f"  human_context: {d3.human_context}")
    print("\n" + "=" * 64)
    print("done: 1 lock-free merge, 1 negotiated merge, 1 human escalation")
    print("=" * 64)


def main(argv=None):
    p = argparse.ArgumentParser(prog="weave", description="version control for the agent century")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="initialize a weave repo")

    c = sub.add_parser("commit-intent", help="record an intent")
    c.add_argument("--goal", required=True)
    c.add_argument("--author", required=True)
    c.add_argument("--model", default="")
    c.add_argument("--plan", default="")
    c.add_argument("--rationale", default="")
    c.add_argument("--stream", default="main")
    c.add_argument("--verified", action="store_true")
    c.add_argument("--sandbox", default="")
    c.set_defaults(fn=cmd_commit_intent)

    l = sub.add_parser("log", help="show the intent log")
    l.add_argument("--stream", default=None)
    l.set_defaults(fn=cmd_log)

    w = sub.add_parser("why", help="provenance: why does this path look like this?")
    w.add_argument("path")
    w.set_defaults(fn=cmd_why)

    dm = sub.add_parser("demo", help="run the causal-cone merge demo")
    dm.set_defaults(fn=cmd_demo)

    p.set_defaults(fn=lambda a: p.print_help())
    args = p.parse_args(argv)
    if args.cmd == "init":
        cmd_init(args)
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
