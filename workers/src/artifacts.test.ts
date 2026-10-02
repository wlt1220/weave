import { describe, expect, it } from "vitest";
import { ArtifactLayer } from "./artifacts";

describe("ArtifactLayer (binding absent → graceful degradation)", () => {
  const arts = new ArtifactLayer(undefined);

  it("reports disabled", () => {
    expect(arts.enabled).toBe(false);
  });

  it("ensureStreamRepo degrades to a deterministic repo name", async () => {
    await expect(arts.ensureStreamRepo("demo")).resolves.toEqual({
      repo: "weave-stream-demo",
      remote: null,
    });
  });

  it("sanitizes stream names for repo names", async () => {
    const r = await arts.ensureStreamRepo("a/b c");
    expect(r.repo).toBe("weave-stream-a-b-c");
  });

  it("persistIntent is a no-op returning false", async () => {
    await expect(arts.persistIntent("demo", {} as never)).resolves.toBe(false);
  });

  it("gitAccess returns null", async () => {
    await expect(arts.gitAccess("demo")).resolves.toBeNull();
  });
});
