import type { Intent } from "./types";

/**
 * Artifacts layer: one repo per stream, intents as versioned files.
 *
 * Uses the real Cloudflare Artifacts Workers binding
 * (env.ARTIFACTS: create/get/createToken/…​). Writes go through the
 * git protocol via isomorphic-git with a minted repo token — the documented
 * write path. If the binding is unavailable (local dev without a Cloudflare
 * account), every method degrades gracefully and the Durable Object remains
 * the operational store.
 */

interface ArtifactsNs {
  create(name: string, opts?: any): Promise<any>;
  get(name: string): Promise<any>;
}

function repoName(stream: string): string {
  return `weave-stream-${stream.replace(/[^a-zA-Z0-9-_]/g, "-")}`;
}

export class ArtifactLayer {
  constructor(private ns: ArtifactsNs | undefined) {}

  get enabled(): boolean {
    return !!this.ns;
  }

  async ensureStreamRepo(stream: string): Promise<{ repo: string; remote: string | null }> {
    if (!this.ns) return { repo: repoName(stream), remote: null };
    const name = repoName(stream);
    try {
      const created = await this.ns.create(name, {
        description: `Weave intent stream: ${stream}`,
        setDefaultBranch: "main",
      });
      return { repo: name, remote: created.remote ?? null };
    } catch (e: any) {
      // already exists → fall through to get()
      const handle = await this.ns.get(name);
      const info = await handle.info();
      return { repo: name, remote: info.remote ?? null };
    }
  }

  /** Mint a short-lived git token for the stream repo (the git bridge). */
  async gitAccess(stream: string, ttlSeconds = 3600): Promise<{ remote: string; token: string } | null> {
    if (!this.ns) return null;
    const handle = await this.ns.get(repoName(stream));
    const info = await handle.info();
    const tok = await handle.createToken("write", ttlSeconds);
    return { remote: info.remote, token: tok.plaintext };
  }

  /**
   * Persist an intent as intents/<id>.json via git-over-HTTPS.
   * Implemented with isomorphic-git against the repo remote + minted token.
   * Called best-effort from the coordinator; failures never block ingestion.
   */
  async persistIntent(stream: string, intent: Intent): Promise<boolean> {
    if (!this.ns) return false;
    try {
      const git = await import("isomorphic-git");
      const access = await this.gitAccess(stream);
      if (!access) return false;
      const dir = `/tmp/${repoName(stream)}`;
      // NOTE: in production workerd, use a writable FS shim; local dev uses node fs.
      const fs = (await import("node:fs")).promises as any;
      const http = (await import("isomorphic-git/http/node")).default as any;
      try {
        await git.clone({ fs, http, dir, url: access.remote, singleBranch: true, depth: 1 });
      } catch {
        await fs.mkdir(dir, { recursive: true });
        await git.init({ fs, dir, defaultBranch: "main" });
      }
      await fs.mkdir(`${dir}/intents`, { recursive: true });
      await fs.writeFile(`${dir}/intents/${intent.id}.json`, JSON.stringify(intent, null, 2));
      await git.add({ fs, dir, filepath: `intents/${intent.id}.json` });
      await git.commit({
        fs, dir,
        author: { name: intent.author.agent_id, email: "agent@weave" },
        message: `intent ${intent.id.slice(0, 12)}: ${intent.goal}`,
      });
      const remoteUrl = access.remote.replace("https://", `https://x-access-token:${access.token}@`);
      await git.push({ fs, http, dir, remote: "origin", remoteRef: "main", url: remoteUrl });
      return true;
    } catch (e) {
      console.warn("artifacts persistIntent degraded:", (e as Error).message);
      return false;
    }
  }
}
