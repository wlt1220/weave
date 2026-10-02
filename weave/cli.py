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

    p.set_defaults(fn=lambda a: p.print_help())
    args = p.parse_args(argv)
    if args.cmd == "init":
        cmd_init(args)
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
