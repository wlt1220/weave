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
weave demo            # causal-cone merge: 3 scenarios, local engine
```

## Coordination plane (Cloudflare Workers)

`workers/` is the multi-agent coordination plane: intent ingestion,
content-hash sealing, per-stream Durable Object serialization, and the
continuous integrator (disjoint cones fold lock-free; overlaps open
negotiations; unverified intents wait for receipts).

```bash
cd workers && npm install
npx wrangler dev                                # local: http://localhost:8787
npm test                                        # 25 vitest: cone/seal/artifacts/coordinator
python3 loadtest.py --agents 20 --intents 5     # concurrency proof
cd .. && weave demo-remote --stream demo         # 3 scenarios via the Worker
```

API: `POST /v1/streams`, `POST /v1/streams/:s/intents`,
`GET /v1/streams/:s`, `POST /v1/streams/:s/intents/:id/verify`,
`POST /v1/streams/:s/retry`, `GET /v1/streams/:s/git` (git bridge).

Each stream is backed by a Cloudflare Artifacts repo
(`weave-stream-<name>`), managed entirely through the binding
(create/get/token — no filesystem in the Worker, production-safe by
construction). Intents are mirrored as `intents/<id>.json` by any git
client holding a minted token: `weave mirror --stream <name>` does it
with real git (`GET /v1/streams/:s/git` → clone → write → commit →
push). Set `USE_ARTIFACTS=1` with a Cloudflare account for production;
local dev degrades to the Durable Object store.

## License

MIT — see [LICENSE](LICENSE).
