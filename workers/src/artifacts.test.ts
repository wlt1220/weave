import { describe, expect, it } from "vitest";
import { ArtifactLayer } from "./artifacts";

/** In-memory fake of the Artifacts binding namespace. */
function mockNs(opts: { createError?: string } = {}) {
  const repos = new Map<string, { name: string; remote: string }>();
  const calls: string[] = [];
  const disposed: string[] = [];
  const ns = {
    calls,
    disposed,
    async create(name: string, _o?: unknown) {
      calls.push(`create:${name}`);
      if (opts.createError) {
        const e = new Error(opts.createError) as Error & { code: string };
        e.code = opts.createError;
        throw e;
      }
      if (repos.has(name)) {
        const e = new Error("already exists") as Error & { code: string };
        e.code = "ALREADY_EXISTS";
        throw e;
      }
      const repo = { name, remote: `https://artifacts.example/git/${name}` };
      repos.set(name, repo);
      return repo;
    },
    async get(name: string) {
      calls.push(`get:${name}`);
      const repo = repos.get(name);
      if (!repo) {
        const e = new Error("not found") as Error & { code: string };
        e.code = "NOT_FOUND";
        throw e;
      }
      return {
        info: async () => ({ name: repo.name, remote: repo.remote }),
        createToken: async (scope: string, ttl: number) => ({
          id: "tok-1",
          plaintext: `tok-${name}`,
          scope,
          expiresAt: "2030-01-01T00:00:00.000Z",
        }),
        [Symbol.dispose]() {
          disposed.push(name);
        },
      };
    },
  };
  return ns;
}

const asBinding = (ns: unknown) => ns as unknown as Artifacts;

describe("ArtifactLayer (binding-native, no filesystem)", () => {
  it("reports disabled without a binding", () => {
    const arts = new ArtifactLayer(undefined);
    expect(arts.enabled).toBe(false);
  });

  it("degrades gracefully without a binding", async () => {
    const arts = new ArtifactLayer(undefined);
    await expect(arts.ensureStreamRepo("demo")).resolves.toEqual({
      repo: "weave-stream-demo",
      remote: null,
      created: false,
    });
    await expect(arts.gitAccess("demo")).resolves.toBeNull();
  });

  it("creates the stream repo on first ensure", async () => {
    const m = mockNs();
    const arts = new ArtifactLayer(asBinding(m));
    await expect(arts.ensureStreamRepo("demo")).resolves.toEqual({
      repo: "weave-stream-demo",
      remote: "https://artifacts.example/git/weave-stream-demo",
      created: true,
    });
    expect(m.calls).toEqual(["create:weave-stream-demo"]);
  });

  it("falls back to get() when the repo already exists", async () => {
    const m = mockNs();
    const arts = new ArtifactLayer(asBinding(m));
    await arts.ensureStreamRepo("demo");
    const second = await arts.ensureStreamRepo("demo");
    expect(second.created).toBe(false);
    expect(second.remote).toBe(
      "https://artifacts.example/git/weave-stream-demo",
    );
    expect(m.calls).toContain("get:weave-stream-demo");
    expect(m.disposed).toContain("weave-stream-demo");
  });

  it("sanitizes stream names for repo names", async () => {
    const m = mockNs();
    const arts = new ArtifactLayer(asBinding(m));
    const r = await arts.ensureStreamRepo("a/b c");
    expect(r.repo).toBe("weave-stream-a-b-c");
  });

  it("rethrows non-exists errors from create", async () => {
    const m = mockNs({ createError: "INVALID_INPUT" });
    const arts = new ArtifactLayer(asBinding(m));
    await expect(arts.ensureStreamRepo("demo")).rejects.toThrow();
    expect(m.calls).not.toContain("get:weave-stream-demo");
  });

  it("gitAccess mints a token and disposes the handle", async () => {
    const m = mockNs();
    const arts = new ArtifactLayer(asBinding(m));
    await arts.ensureStreamRepo("demo");
    const access = await arts.gitAccess("demo", 600);
    expect(access?.remote).toBe(
      "https://artifacts.example/git/weave-stream-demo",
    );
    expect(access?.token).toBe("tok-weave-stream-demo");
    expect(m.disposed).toContain("weave-stream-demo");
  });

  it("gitAccess on a missing stream throws NOT_FOUND", async () => {
    const m = mockNs();
    const arts = new ArtifactLayer(asBinding(m));
    await expect(arts.gitAccess("nope")).rejects.toMatchObject({
      code: "NOT_FOUND",
    });
  });
});
