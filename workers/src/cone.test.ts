import { describe, expect, it } from "vitest";
import { findConflict } from "./cone";
import type { Intent } from "./types";

const GRAPH = {
  "payments.py": {
    log: { calls: [] },
    charge: { calls: ["log"] },
    refund: { calls: ["log"] },
  },
};

function intent(node: string): Intent {
  return {
    id: `id-${node}`,
    goal: `touch ${node}`,
    author: { agent_id: "agent-1" },
    operations: [{ op: "replace_function", file: "payments.py", node }],
    verification: { tests: [], passed: true },
    parents: [],
    stream: "s",
    created_at: new Date().toISOString(),
    graph: GRAPH,
  };
}

describe("findConflict (TS port of the Python merge rule)", () => {
  it("disjoint nodes do not conflict", () => {
    // charge and refund both call log, but neither can change the other
    expect(findConflict(intent("charge"), intent("refund"))).toEqual({
      hit: false,
      why: "",
    });
  });

  it("same node conflicts", () => {
    const r = findConflict(intent("charge"), intent("charge"));
    expect(r.hit).toBe(true);
    expect(r.why).toContain("same node 'charge'");
  });

  it("transitive dependency conflicts", () => {
    // refund -> log: touching log can change refund's behavior
    const r = findConflict(intent("log"), intent("refund"));
    expect(r.hit).toBe(true);
    expect(r.why).toContain("depends on");
  });

  it("is symmetric", () => {
    expect(findConflict(intent("refund"), intent("log")).hit).toBe(true);
    expect(findConflict(intent("refund"), intent("charge")).hit).toBe(false);
  });

  it("does not conflict across files", () => {
    const a = intent("charge");
    const b: Intent = {
      ...intent("charge"),
      operations: [{ op: "replace_function", file: "other.py", node: "charge" }],
      graph: { "other.py": { charge: { calls: [] } } },
    };
    expect(findConflict(a, b).hit).toBe(false);
  });
});
