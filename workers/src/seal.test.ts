import { describe, expect, it } from "vitest";
import { canonical, sealIntent } from "./seal";
import type { Intent } from "./types";

function fakeIntent(): Omit<Intent, "id"> {
  return {
    goal: "touch charge",
    author: { agent_id: "agent-1" },
    operations: [{ op: "replace_function", file: "payments.py", node: "charge" }],
    verification: { tests: [], passed: true },
    parents: [],
    stream: "s",
    created_at: "2026-10-02T00:00:00.000Z",
  };
}

describe("seal (content addressing)", () => {
  it("is deterministic", async () => {
    expect(await sealIntent(fakeIntent())).toBe(await sealIntent(fakeIntent()));
  });

  it("ignores key order", async () => {
    const a = await sealIntent({ ...fakeIntent(), goal: "x", rationale: "y" });
    // same key-value pairs, different literal order
    const b = await sealIntent({
      rationale: "y",
      goal: "x",
      author: { agent_id: "agent-1" },
      operations: [
        { op: "replace_function", file: "payments.py", node: "charge" },
      ],
      verification: { tests: [], passed: true },
      parents: [],
      stream: "s",
      created_at: "2026-10-02T00:00:00.000Z",
    });
    expect(a).toBe(b);
  });

  it("changes with content and looks like a sha256", async () => {
    const a = await sealIntent(fakeIntent());
    const b = await sealIntent({ ...fakeIntent(), goal: "different" });
    expect(a).not.toBe(b);
    expect(a).toMatch(/^[0-9a-f]{64}$/);
  });

  it("canonical sorts keys recursively", () => {
    expect(canonical({ b: 1, a: { y: 2, x: 1 } })).toBe('{"a":{"x":1,"y":2},"b":1}');
  });
});
