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
    reverted = store.reverted_ids()
    for e in store.log(args.stream):
        it = store.get(e["id"])
        flag = "✗" if e["id"] in reverted else ("✓" if it.verified else "○")
        print(f"{flag} {e['id'][:12]} [{e['stream']}] {e['goal']}")


def _print_cell(cell):
    flag = lambda it: "✓" if it.verified else "○"
    print(f"cell {cell.nid}")
    print(f"  cell_id  {cell.cell_id[:16]}…")
    if cell.span:
        print(f"  span     lines {cell.span[0]}-{cell.span[1]}")
    print(f"  state    sha256:{cell.state_hash[:16]}…")
    n = len(cell.intent_ids)
    rng = (f"{cell.intent_ids[0][:8]} → {cell.intent_ids[-1][:8]}"
           if n else "(untouched since init)")
    print(f"  slice    {n} intent{'s' if n != 1 else ''} {rng}")
    if cell.intents:
        print("  touched by:")
        for it in cell.intents:
            print(f"    {flag(it)} {it.id[:12]} — {it.goal}")
            print(f"      author: {it.author.agent_id} ({it.author.model})")
            print(f"      rationale: {it.rationale or '(none recorded)'}")


def _ensure_fold(store):
    """Load the fold, building from working-tree genesis if absent.

    Returns (fold, is_new). The intent log is the source of truth; the
    working tree at first fold is genesis.
    """
    from .fold import Fold
    fold = store.load_fold()
    if fold is not None:
        return fold, False
    entries = store.log()
    intents = [store.get(e["id"]) for e in entries]
    files = sorted({op.get("file") for it in intents
                    for op in it.operations if op.get("file")})
    if not files:
        raise SystemExit("nothing to fold (no intents with file operations)")
    base = {}
    for f in files:
        if not os.path.isfile(f):
            raise SystemExit(f"genesis file missing in working tree: {f}")
        with open(f) as fh:
            base[f] = fh.read()
    return Fold.build(base, intents), True


def cmd_fold(args):
    """Materialize the intent log to the working tree, per-cell incremental."""
    store = Store.open(find_root())
    entries = store.log()
    intents = [store.get(e["id"]) for e in entries]
    fold, is_new = _ensure_fold(store)
    if is_new:
        print(f"fold built: {len(fold.cells)} cells from "
              f"{len(intents)} intents (genesis = working tree)")
    else:
        new = intents[fold.log_pos:]
        if not new:
            print(f"fold up to date: {fold.log_pos} intents, "
                  f"{len(fold.cells)} cells")
            return
        dirty = fold.advance(new)
        print(f"incremental fold: {len(new)} new intent(s) → "
              f"{len(dirty)} dirty cell(s)")
        for d in dirty:
            print(f"  dirty {d}")
    material = fold.materialize()
    for f, src in material.items():
        with open(f, "w") as fh:
            fh.write(src)
    store.save_fold(fold)
    print(f"wrote {len(material)} file(s); fold at log_pos={fold.log_pos}")


def cmd_rewind(args):
    """Excise a bad intent's polluted cells; re-fold everything else."""
    from .rewind import rewind_fold
    store = Store.open(find_root())
    entries = store.log()
    intents = [store.get(e["id"]) for e in entries]
    matches = [it for it in intents if it.id and it.id.startswith(args.intent)]
    if not matches:
        print(f"no intent matching {args.intent!r}")
        return
    if len(matches) > 1:
        print(f"ambiguous prefix {args.intent!r}:")
        for it in matches:
            print(f"  {it.id[:12]} — {it.goal}")
        return
    bad = matches[0]
    fold, _ = _ensure_fold(store)
    new = intents[fold.log_pos:]
    if new:
        fold.advance(new)
    try:
        report = rewind_fold(fold, intents[:fold.log_pos], bad.id)
    except (KeyError, ValueError) as e:
        print(f"rewind: {e}")
        return
    material = fold.materialize()
    for f, src in material.items():
        with open(f, "w") as fh:
            fh.write(src)
    store.save_fold(fold)
    print(f"rewound {bad.id[:12]} — {bad.goal!r} (log untouched, marked reverted)")
    print(f"  polluted cone: {len(report.affected)} cell(s)")
    for r in report.restored:
        sl = len(r["slice"])
        print(f"    {r['node_id']}: {r['old_cell_id'][:8]} → "
              f"{r['new_cell_id'][:8]}  slice={sl} intent(s)")
    if report.downstream:
        print("  downstream intents built on polluted state — review advised:")
        for it in report.downstream:
            print(f"    ○ {it.id[:12]} — {it.goal}")
    print(f"  untouched cells: {report.untouched_cells} (byte-identical)")


def cmd_why(args):
    """Spacetime-cell lookup: file[:line] -> the cell + its intent slice."""
    import ast as _ast
    from .cell import resolve_cell
    store = Store.open(find_root())
    target = args.path
    file, line = target, None
    if ":" in target:
        maybe_file, _, spec = target.rpartition(":")
        if os.path.isfile(maybe_file):
            file = maybe_file
            line = int(spec) if spec.isdigit() else spec  # line number or node name
    if not os.path.isfile(file):
        print(f"no such file in working tree: {file}")
        return
    with open(file) as f:
        source = f.read()
    sources = {file: source}
    reverted = store.reverted_ids()
    intents = [store.get(e["id"]) for e in store.log()
               if e["id"] not in reverted]
    if line is not None:
        cell = resolve_cell(file, line, sources, intents)
        if cell is None:
            print(f"no cell at {target} (line outside any function?)")
            return
        _print_cell(cell)
        return
    # census: one cell per top-level function
    tree = _ast.parse(source)
    nodes = [n.name for n in tree.body
             if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
    if not nodes:
        print(f"no functions in {file}")
        return
    for name in nodes:
        cell = resolve_cell(file, name, sources, intents)
        sl = f"{len(cell.intent_ids)} intents" if cell.intent_ids else "untouched"
        sp = f"{cell.span[0]}-{cell.span[1]}" if cell.span else "?"
        print(f"cell {cell.nid}  {cell.cell_id[:12]}…  "
              f"slice={sl}  lines={sp}")


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

    # ---- Spacetime cell: weave why charge() ----
    print("\n--- Spacetime cell: weave why charge() ---")
    from .cell import resolve_cell
    cell = resolve_cell("payments.py", 6, {"payments.py": merged_src},
                        [a1, a2])
    print(f"  cell {cell.nid}  id={cell.cell_id[:16]}…")
    print(f"  slice: {[i[:8] for i in cell.intent_ids]} "
          f"({len(cell.intent_ids)} intents touched this node)")
    print(f"  state sha256:{cell.state_hash[:16]}…  "
          f"span lines {cell.span[0]}-{cell.span[1]}")

    # ---- Incremental per-cell fold ----
    print("\n--- Incremental fold: per-cell cache ---")
    from .fold import Fold
    fold = Fold.build({"payments.py": DEMO_SOURCE}, [a1])
    before = {k: c.cell_id for k, c in fold.cells.items()}
    dirty = fold.advance([a2])
    print(f"  built from 1 intent: {len(fold.cells)} cells; "
          f"+1 intent → dirty cells: {dirty}")
    untouched = [k for k in fold.cells if k not in dirty]
    same = all(fold.cells[k].cell_id == before[k] for k in untouched)
    print(f"  untouched cells byte-identical: {same} "
          f"({len(untouched)}/{len(fold.cells)})")
    _ast.parse(fold.materialize()["payments.py"])
    print("  materialized fold compiles")

    # ---- Rewind: excise a bad intent ----
    print("\n--- Rewind: excise a bad intent, keep everything else ---")
    from .rewind import rewind_fold
    bad = _mk_intent("normalize log format", "agent-4", "log",
                     LOG_STRUCTURED,
                     "pipeline requires uppercase (later found to break parsers)",
                     verified=True)
    f2 = Fold.build({"payments.py": DEMO_SOURCE}, [a1, a2])
    f2.advance([bad])
    print(f"  +bad intent → log cell: "
          f"{f2.cells['payments.py:log'].cell_id[:12]}…")
    rep = rewind_fold(f2, [a1, a2, bad], bad.id)
    aff = sorted(n.split(":")[1] for n in rep.affected)
    print(f"  rewind {bad.id[:8]}: polluted cone = {aff}")
    for r in rep.restored:
        print(f"    {r['node_id']}: {r['old_cell_id'][:8]} → "
              f"{r['new_cell_id'][:8]}")
    print(f"  untouched cells: {rep.untouched_cells} (byte-identical)")
    print("  log untouched by rewind — bad intent marked reverted, not deleted")

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


def cmd_demo_remote(args):
    """Same three scenarios as `weave demo`, but through the Workers plane."""
    from .remote import WeaveRemote
    r = WeaveRemote(args.base)
    stream = args.stream
    meta = r.ensure_stream(stream)
    print(f"stream '{stream}' → repo {meta['repo']} "
          f"(artifacts={'on' if meta.get('artifacts') else 'off, local DO store'})")

    a1 = _mk_intent("add idempotency key to charge", "agent-1", "charge",
                    CHARGE_IDEMPOTENT,
                    "200k req/day hit double-charge on retries; key makes it safe",
                    verified=True)
    a2 = _mk_intent("add audit trail to refund", "agent-2", "refund",
                    REFUND_AUDIT, "finance requires an audit trail on every refund",
                    verified=True)
    a3 = _mk_intent("fix cross-border fee calc", "agent-3", "charge",
                    CHARGE_FEE, "fee was flat 2%; cross-border needs 2.9% + 30c",
                    verified=False)
    src = {"payments.py": DEMO_SOURCE}

    print("\n--- agent-1 → charge (verified) ---")
    res1 = r.submit(stream, a1, src)
    print(f"  integrated={res1.get('integrated')} id={res1['id'][:12]}")

    print("--- agent-2 → refund (verified, disjoint) ---")
    a2.parents = [res1["id"]]
    res2 = r.submit(stream, a2, src)
    print(f"  integrated={res2.get('integrated')} id={res2['id'][:12]}")

    print("--- agent-3 → charge (UNVERIFIED, same node) ---")
    res3 = r.submit(stream, a3, src)
    print(f"  integrated={res3.get('integrated')} "
          f"awaiting_verification={res3.get('awaiting_verification')}")

    print("--- agent-3's CI finishes → receipt arrives ---")
    v = r.verify(stream, res3["id"], passed=True)
    print(f"  verified, integrated={v.get('integrated')} "
          f"negotiation={v.get('negotiation')} reason={v.get('reason')}")

    st = r.state(stream)
    print(f"\nstream state: trunk_folds={st['trunk']['folds']} "
          f"pending={len(st['pending'])} "
          f"negotiations={len(st['negotiations'])} log={len(st['log'])}")
    for n in st["negotiations"]:
        print(f"  [{n['id']}] {n['outcome']} winner="
              f"{n['winner'][:12] if n['winner'] else None} :: {n['reason']}")


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

    w = sub.add_parser("why", help="spacetime cell lookup: file[:line|node] -> cell + intent slice")
    w.add_argument("path")
    w.set_defaults(fn=cmd_why)

    fl = sub.add_parser("fold", help="materialize the intent log to the working tree (per-cell incremental)")
    fl.set_defaults(fn=cmd_fold)

    rw = sub.add_parser("rewind", help="excise a bad intent's polluted cells; re-fold the rest")
    rw.add_argument("intent", help="intent id (prefix ok)")
    rw.set_defaults(fn=cmd_rewind)

    dm = sub.add_parser("demo", help="run the causal-cone merge demo")
    dm.set_defaults(fn=cmd_demo)

    dr = sub.add_parser("demo-remote",
                        help="run the merge demo against a Workers coordinator")
    dr.add_argument("--base", default="http://localhost:8787")
    dr.add_argument("--stream", default="demo")
    dr.set_defaults(fn=cmd_demo_remote)

    p.set_defaults(fn=lambda a: p.print_help())
    args = p.parse_args(argv)
    if args.cmd == "init":
        cmd_init(args)
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
