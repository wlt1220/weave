# Weave — Version Control for the Agent Century

Git was built in 2005 for humans mailing patches. Weave is version control
rebuilt for the next 30 years: agents writing code at machine speed, hundreds
of thousands concurrently.

**The reframing:** version control as event sourcing. Git stores snapshots and
diffs; Weave stores a causal **intent log** as the source of truth, and the repo
state is a materialized view — a fold over intents.

- **Intent, not diff** — the atomic unit is {goal, plan, operations, verification, rationale}
- **Streams, not branches** — agents publish intents; the system continuously integrates
- **Negotiate, don't conflict** — semantic merge at the AST level; genuine conflicts trigger structured agent-to-agent negotiation (versioned)
- **Verification is versioned** — an intent without test receipts cannot integrate
- **`weave why`** — every line maps to the decision that produced it
- **`weave review`** — humans review risk and intent digests, not diffs

Full design: [DESIGN.md](DESIGN.md)

Built for the Cloudflare "Build the next GitHub" challenge (Oct 1–14, 2026):
coordination plane on Cloudflare Workers, intents/verifications/decisions as
Artifacts.

## Quickstart (prototype)

```bash
pip install -e .
weave init
weave commit-intent --goal "fix race in pool" --author "agent-1"
weave log
weave why README.md
```

## License

MIT — see [LICENSE](LICENSE).
