/**
 * Artifacts layer: one git repo per stream, binding-native.
 *
 * The Worker only ever makes Artifacts binding RPCs (create/get/token/info) —
 * no filesystem, no git client inside the Worker — so this module is
 * production-safe by construction.
 *
 * Writes go through the git bridge: any git client holding a minted token
 * from GET /v1/streams/:stream/git clones the repo remote and pushes
 * intents/<id>.json. The weave CLI does this with `weave mirror`
 * (see weave/mirror.py). Intent filenames are content hashes, so mirrors
 * never conflict.
 */

function repoName(stream: string): string {
  return `weave-stream-${stream.replace(/[^a-zA-Z0-9-_]/g, "-")}`;
}

function isAlreadyExists(e: unknown): boolean {
  return (e as { code?: string })?.code === "ALREADY_EXISTS";
}

export class ArtifactLayer {
  constructor(private ns: Artifacts | undefined) {}

  get enabled(): boolean {
    return !!this.ns;
  }

  /** Create the stream repo, or return the existing one (idempotent). */
  async ensureStreamRepo(
    stream: string,
  ): Promise<{ repo: string; remote: string | null; created: boolean }> {
    if (!this.ns) return { repo: repoName(stream), remote: null, created: false };
    const name = repoName(stream);
    try {
      const created = await this.ns.create(name, {
        description: `Weave intent stream: ${stream}`,
        setDefaultBranch: "main",
      });
      return { repo: created.name, remote: created.remote, created: true };
    } catch (e) {
      if (!isAlreadyExists(e)) throw e;
      const repo = await this.ns.get(name);
      try {
        const info = await repo.info();
        return { repo: info.name, remote: info.remote, created: false };
      } finally {
        repo[Symbol.dispose]();
      }
    }
  }

  /** Mint a short-lived git token for the stream repo (the git bridge). */
  async gitAccess(
    stream: string,
    ttlSeconds = 3600,
  ): Promise<{ remote: string; token: string } | null> {
    if (!this.ns) return null;
    const repo = await this.ns.get(repoName(stream)); // NOT_FOUND if missing
    try {
      const info = await repo.info();
      const tok = await repo.createToken("write", ttlSeconds);
      return { remote: info.remote, token: tok.plaintext };
    } finally {
      repo[Symbol.dispose]();
    }
  }
}
