# Weave — Version Control for the Agent Century

> Design document. Competition: Cloudflare "Build the next GitHub" (Oct 1–14, 2026).
> Thesis: Git was built in 2005 for humans mailing patches. The next 30 years belong
> to agents writing code at machine speed, hundreds of thousands concurrently.
> Version control must be rebuilt around that reality.

---

## 1. The problem with Git for agents

Git's design bakes in human constraints that agents don't have — and misses
capabilities agents need:

| Git assumption (human era) | Agent-era reality |
|---|---|
| The unit of change is a **text diff** | Agents need the **why**, not the what — goal, plan, alternatives considered |
| **Branches + PRs** coordinate work | Agents don't wait for review rituals; they need continuous integration of intent |
| **Merge conflicts** are resolved by humans staring at `<<<<<<<` | Line-based conflicts are an artifact of text thinking; agents can negotiate semantically |
| `git blame` shows **who** touched a line | Agents need **why**: which task, which conversation, which decision |
| CI is a **separate system** bolted on | Verification must be **part of the versioned record** |
| One repo, one working tree per human | Agents need **thousands of ephemeral sandboxes** per minute |

**Core reframing: version control as event sourcing.**
Git stores snapshots and diffs; the repository state is primary. Weave stores a
causal **intent log** as the source of truth; the repo state is a materialized
view — a fold over intents. Time travel, provenance, and replay fall out for free.

---

## 2. Design principles (30-year bets)

1. **Intent is the atomic unit, not the diff.** A diff is a lossy rendering for
   human eyes. The durable record is: goal → plan → operations → verification →
   rationale.
2. **Streams, not branches.** Branches are human coordination rituals (name it,
   push it, open a PR, wait). Agents publish change intents to streams; the
   system continuously integrates them. The merge queue becomes the whole system.
3. **Merge semantically, negotiate the rest.** Textual merges die. Weave merges
   operation logs at the AST level (CRDT-inspired for commutative edits).
   Genuine semantic conflicts trigger structured **agent-to-agent negotiation**
   with full shared context — producing either a merged intent or a decision
   record. Humans are the escalation path, not the default.
4. **Verification is versioned.** An intent without a verification receipt
   (tests run, results, sandbox attestation) cannot integrate. CI isn't a
   separate service; it's a field on the commit.
5. **Provenance is queryable.** Every symbol maps to intent → task →
   conversation. `weave why <symbol>` replays the decision context, not just a hash.
6. **Humans review risk, not diffs.** `weave review` renders intent digests:
   what changed, why, blast radius, risk score. Humans supervise at the intent
   level — the oversight layer for the agent century.

---

## 3. Core concepts

### Intent
The atomic unit. Content-addressed (sha256 over canonical form):

```
Intent {
  id:           hash(canonical(intent))        # content-addressed
  author:       { agent_id, model, session }    # who/what made this
  goal:         "fix race in connection pool"   # natural language
  plan:         [step, ...]                     # what the agent intended
  operations:   [AST-level edit ops]            # NOT text diffs
  verification: { tests, results, sandbox }     # receipts, required
  rationale:    "chose X over Y because..."    # alternatives considered
  rejected:     [{ alternative, flaw }]         # explored but discarded (ghost genes)
  certificate:  "formal-proof-hash"             # oracle signature, when available
  parents:      [intent_ids]                   # causal links
  stream:       "payments/refactor"
}
```

### Stream
An append-only, ordered log of intents for a task or area. Many streams exist
concurrently; a continuous integrator folds them into trunk. No long-lived
branches, no branch namespace contention at 100k-agent scale.

### Weave (the merge)
Semantic three-way merge over operation logs:
- **Causal cones first.** For any change touching node `v`, compute its causal
  cone `C(v)` = transitive dependents + dependencies. Two concurrent intents
  with **disjoint cones merge lock-free, zero coordination** (orthogonal
  non-interference). Cone overlap is the *only* case that needs real work —
  this turns "merge" from a text heuristic into a graph decision procedure.
  (Implemented refinement: conflict iff one intent's node *is* or *transitively
  depends on* the other's node. Two intents touching nodes that merely share a
  dependency — e.g. both call `log()` — do **not** conflict, since neither can
  change the other's behavior. Stricter and more precise than full-cone
  intersection.)
- Commutative operations inside overlapping cones still merge automatically
  (CRDT insight applied to code).
- Genuine semantic conflicts → **negotiation session**: the authoring agents
  are resumed with a shared context snapshot (both intents, both rationales,
  failing verifications) and must produce a merged intent or a decision record.
- The negotiation transcript itself is versioned. Losing candidates are
  compressed into the **ghost bank** (superseded-by links) — conflict
  resolution becomes training data instead of trash.

### Spacetime cell (时空胞)
The unifying data-model frame: the repository is a **spacetime manifold**,
not a file tree with history attached.

- **Space axis**: AST nodes (file → function → block). A position in code.
- **Time axis**: the intent log. A position in history.
- **A cell** = `(node, intent_slice)` → the state of that code region during
  that slice, plus the intents that acted on it.
  Content-addressed: `cell_id = hash(node_id, intent_range, state_hash)`.

Every Weave feature is a cell operation:

| Feature | Cell reading |
|---|---|
| fold / checkout | take the present slice — the "now" of every cell |
| `weave why <line>` | cell lookup: which cell holds this line, which intents touched it |
| causal cone | the cells causally downstream of a change; disjoint cell-sets compose lock-free |
| `weave rewind <intent>` | excise the polluted cells and re-fold; all other cells untouched |
| negotiation | two agents claim overlapping cells; the transcript decides the surviving lineage |
| ghost bank | archived cells of losing lineages — superseded, never deleted |

This framing earns its keep (it's not poetry): "the repo is a fold over
intents" becomes operationally precise. A fold isn't an amorphous replay —
it's **per-cell**. That gives us incremental fold (re-fold only dirty cells),
per-cell blame, and a natural addressable unit for Artifacts mirroring
(`intents/<id>.json` today; cells as objects tomorrow).

Deliberate difference from the ChronoSoma (2046) spec this image comes from:
there it was cosmology; here every term maps to something implementable now —
the prototype already computes cones over cells, and `weave why` already
resolves lines to intents. Same ambition, running today.

### Local rewind
`weave rewind <intent>` reverses only the causal cone polluted by a bad intent
and re-folds the log — the rest of the system keeps running. Global revert is
a special case (cone = everything), not the default.

### Git bridge (bidirectional)
Weave doesn't ask the world to abandon git on day one:
- **Export**: compile the intent fold to a standard git tree + history for
  legacy tools, CI, and humans (`weave export`).
- **Ingest**: a git push is parsed into the intent log (operations + author,
  verification pending) — old-world tools keep working while agents live in
  the fast lane.
- **AGENTS.md manifest**: the active invariant set is rendered as a
  machine-readable constitution every agent entering the repo must follow.

### Provenance graph
`weave why <file>:<line>` → the intent → the task → the conversation that
produced it. Onboarding a new agent onto a codebase means replaying decisions,
not reading diffs.

### Sandbox
`weave spawn` → an ephemeral, content-addressed execution environment in
milliseconds. Verification receipts are bound to sandbox attestations, so "it
worked on my machine" is cryptographically meaningless — the receipt names the
exact environment.

### Oversight
`weave review` → natural-language digest per intent: goal, operations summary,
blast radius (symbols/callers affected), risk score, verification status.
Humans approve intents, not lines.

---

## 4. Data model

Objects are content-addressed and typed (like git objects, but richer):

```
blob         # file content (unchanged concept)
tree         # directory snapshot (unchanged concept)
intent       # the atomic unit (§3)
verification # test receipts bound to sandbox attestation
decision     # negotiation outcome / human override record
```

The **intent log** is the source of truth. `HEAD` is not a commit — it's a
pointer to a fold state: `state = fold(intents)`. Checking out an old state is
replaying the log to a prefix. `bisect` becomes binary search over verifications.

---

## 5. Architecture (Cloudflare-native)

```
┌─ Agents (100k concurrent) ─────────────────────────┐
│  weave CLI / SDK  →  intent streams                 │
└───────────────────────┬────────────────────────────┘
                        ▼
┌─ Coordination plane (Workers) ──────────────────────┐
│  ingest → validate → route to stream                 │
│  continuous integrator (fold streams → trunk)        │
│  negotiation orchestrator (Durable Objects)          │
└───────┬─────────────────────────────┬──────────────┘
        ▼                             ▼
┌─ Objects (R2) ────────────┐  ┌─ Artifacts ───────────────┐
│  content-addressed blobs  │  │  intents, verifications,  │
│  trees, sandboxes         │  │  decisions, review digests│
└───────────────────────────┘  └───────────────────────────┘
```

- **Workers**: intent ingestion, validation, stream routing, the continuous
  integrator. Scales horizontally with agent count.
- **Durable Objects**: per-stream serialization and negotiation sessions —
  strong consistency exactly where merge ordering matters, nowhere else.
- **R2**: content-addressed object storage for blobs/trees/sandbox images.
- **Artifacts** (Cloudflare): intents, verification receipts, decision records
  and review digests as first-class, queryable agent artifacts.

---

## 6. What the prototype demonstrates (by Oct 14)

1. `weave init / commit-intent / log` — intent log as source of truth (local).
2. Two agents, conflicting intents → semantic merge or **negotiation session**
   with transcript → merged intent. The money demo.
3. `weave why` — spacetime-cell lookup: `file[:line]` → cell coordinates
   `(node, intent slice, cell_id)` + the intents that touched it.
4. `weave fold` — per-cell incremental fold: the log materialized to the
   working tree, recomputing only dirty cells (untouched cells byte-identical).
5. `weave review` — intent digest with blast radius + risk score.
6. Coordination plane on Workers + Artifacts (multi-agent concurrency).

## 7. Roadmap (beyond the competition)

- **v0.2**: AST-level operation log (tree-sitter), real semantic merge.
- **v0.3**: sandbox attestations (Workers-based execution receipts).
- **v0.4**: negotiation as a protocol (agents from different vendors negotiate).
- **v1**: hosted streams — "GitHub for intents."

---

## 8. Why this wins

Judging weights: 50% originality/quality of the agent-collaboration prototype,
25% multi-agent concurrency/coordination/conflict handling, 25% UX.

- **Originality**: nobody else reframes VCS as event sourcing over intents;
  negotiation-as-versioned-protocol is new.
- **Concurrency story**: causal cones + streams + continuous integration +
  Durable Object serialization directly answers "hundreds of thousands of
  agents" — with a decision procedure, not hand-waving.
- **UX**: `weave review` / `weave why` give humans the oversight layer the
  agent century needs — reviewers judge risk, not diffs. The git bridge means
  judges (who live in git) can touch it on day one.

## 9. Influences & credit

The causal-cone merge criterion, local rewind, ghost bank, git projection
bridge, and proof-carrying provenance fields were inspired by the ChronoSoma
(2046 Next-Gen Agentic VCS) system design specification, shared with us via
Google Doc. Weave differs deliberately: same ambition, but every concept above
is scoped to something implementable *now* — the prototype in this repo
already runs.

License: MIT.
