import { describe, expect, it } from "vitest";
import { StreamCoordinator } from "./coordinator";
import type { Intent } from "./types";

const GRAPH = {
  "payments.py": {
    log: { calls: [] },
    charge: { calls: ["log"] },
    refund: { calls: ["log"] },
  },
};

function mkIntent(
  node: string,
  opts: {
    verified?: boolean;
    parents?: string[];
    goal?: string;
    agent?: string;
  } = {},
): Omit<Intent, "id" | "stream"> {
  return {
    goal: opts.goal ?? `touch ${node}`,
    author: { agent_id: opts.agent ?? "agent-1" },
    operations: [{ op: "replace_function", file: "payments.py", node }],
    verification: { tests: ["t"], passed: opts.verified ?? true },
    rationale: `rationale for ${node}`,
    parents: opts.parents ?? [],
    created_at: new Date().toISOString(),
    graph: GRAPH,
  };
}

function makeCoord(): StreamCoordinator {
  const store = new Map<string, unknown>();
  const ctx = {
    storage: {
      get: async <T>(k: string): Promise<T | undefined> =>
        store.get(k) as T | undefined,
      put: async (k: string, v: unknown): Promise<void> => {
        store.set(k, v);
      },
    },
  };
  return new StreamCoordinator(ctx as never, { USE_ARTIFACTS: "0" } as never);
}

async function ingestOk(
  coord: StreamCoordinator,
  node: string,
  opts?: Parameters<typeof mkIntent>[1],
) {
  const res = await coord.ingest(mkIntent(node, opts), "s");
  if (!res.ok) throw new Error(`ingest failed: ${res.error}`);
  return res;
}

describe("StreamCoordinator", () => {
  describe("verification gate", () => {
    it("records but never folds unverified intents", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const res = await ingestOk(coord, "charge", { verified: false });
      expect(res.integrated).toBe(false);
      expect("awaiting_verification" in res && res.awaiting_verification).toBe(
        true,
      );
      const state = await coord.getState();
      expect(state.log).toHaveLength(1); // recorded…
      expect(state.trunk.folds).toBe(0); // …but never folded
      expect(state.pending).toContain(res.id);
    });

    it("a late verification receipt folds the waiting intent", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const res = await ingestOk(coord, "charge", { verified: false });
      const v = await coord.verifyIntent(res.id, {
        tests: ["t"],
        passed: true,
      });
      if (!v.ok) throw new Error("verify failed");
      expect(v.integrated).toBe(true);
      const state = await coord.getState();
      expect(state.trunk.folds).toBe(1);
      expect(state.pending).toHaveLength(0);
    });
  });

  describe("conflict detection", () => {
    it("disjoint cones fold lock-free", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const a = await ingestOk(coord, "charge", { agent: "agent-1" });
      const b = await ingestOk(coord, "refund", { agent: "agent-2" });
      expect(a.integrated).toBe(true);
      expect(b.integrated).toBe(true);
      const state = await coord.getState();
      expect(state.trunk.folds).toBe(2);
      expect(state.trunk.head).toBe(b.id);
      expect(state.negotiations).toHaveLength(0);
    });

    it("same node opens a negotiation; both verified → escalated", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      await ingestOk(coord, "charge", { agent: "agent-1" });
      const b = await ingestOk(coord, "charge", { agent: "agent-2" });
      expect(b.integrated).toBe(false);
      expect("negotiation" in b && typeof b.negotiation === "string").toBe(
        true,
      );
      const state = await coord.getState();
      expect(state.negotiations).toHaveLength(1);
      const ng = state.negotiations[0];
      expect(ng.outcome).toBe("escalated");
      expect(ng.winner).toBeNull();
      expect(ng.human_context).toContain("charge");
      expect(state.pending).toContain(b.id);
      expect(state.trunk.folds).toBe(1); // loser never folds
    });

    it("verified vs unverified rival → verified wins, loser → ghost bank", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const a = await ingestOk(coord, "charge", {
        agent: "agent-1",
        verified: false,
      });
      const b = await ingestOk(coord, "charge", {
        agent: "agent-2",
        verified: true,
      });
      expect(b.integrated).toBe(true);
      expect("won_negotiation" in b).toBe(true);
      const state = await coord.getState();
      const ng = state.negotiations[0];
      expect(ng.outcome).toBe("merged");
      expect(ng.winner).toBe(b.id);
      expect(ng.ghost_genes).toHaveLength(1);
      expect(ng.ghost_genes[0].intent).toBe(a.id);
      expect(ng.ghost_genes[0].superseded_by).toBe(b.id);
      expect(state.trunk.folds).toBe(1);
      expect(state.pending).toContain(a.id); // loser stays pending as ghost
    });

    it("transitive dependency (refund → log) opens a negotiation", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      await ingestOk(coord, "log", { agent: "agent-1" });
      const b = await ingestOk(coord, "refund", { agent: "agent-2" });
      expect(b.integrated).toBe(false);
      const state = await coord.getState();
      expect(state.negotiations).toHaveLength(1);
      expect(state.negotiations[0].reason).toContain("depends on");
    });

    it("causal successors via parents do not conflict", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const a = await ingestOk(coord, "charge", { agent: "agent-1" });
      const b = await ingestOk(coord, "charge", {
        agent: "agent-2",
        parents: [a.id],
      });
      expect(b.integrated).toBe(true);
      const state = await coord.getState();
      expect(state.negotiations).toHaveLength(0);
      expect(state.trunk.folds).toBe(2);
    });
  });

  describe("rebase-and-retry", () => {
    it("folds pending intents once parents fast-forward past the conflict", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      await ingestOk(coord, "charge", { agent: "agent-1" });
      const b = await ingestOk(coord, "charge", { agent: "agent-2" });
      expect(b.integrated).toBe(false); // escalated, pending

      const r = await coord.retryPending();
      expect(r.retried).toBe(1);
      expect(r.still_pending).toBe(0);

      const state = await coord.getState();
      expect(state.trunk.folds).toBe(2);
      expect(state.pending).toHaveLength(0);
    });
  });

  describe("ingest validation", () => {
    it("rejects an intent whose id does not match its content hash", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const res = await coord.ingest(
        { ...mkIntent("charge"), id: "deadbeef" },
        "s",
      );
      expect(res.ok).toBe(false);
      if (res.ok) throw new Error("unreachable");
      expect(res.error).toContain("content hash");
    });

    it("getIntent round-trips a sealed intent", async () => {
      const coord = makeCoord();
      await coord.ensureStream("s");
      const res = await ingestOk(coord, "charge");
      const got = await coord.getIntent(res.id);
      expect(got?.goal).toBe("touch charge");
      expect(got?.id).toBe(res.id);
    });

    it("ensureStream reports artifacts off in local dev", async () => {
      const coord = makeCoord();
      const meta = await coord.ensureStream("s");
      expect(meta.repo).toBe("weave-stream-s");
      expect(meta.artifacts).toBe(false);
    });
  });
});
