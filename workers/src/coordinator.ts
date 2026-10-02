import { DurableObject } from "cloudflare:workers";
import { findConflict } from "./cone";
import { sealIntent } from "./seal";
import { ArtifactLayer } from "./artifacts";
import type {
  Intent,
  LogEntry,
  NegotiationRecord,
  TrunkState,
} from "./types";

interface Env {
  ARTIFACTS?: any;
  WEAVE_OBJECTS?: any;
  USE_ARTIFACTS?: string;
}

/**
 * StreamCoordinator — one Durable Object per stream.
 * Owns the intent log, the trunk fold state, and negotiations.
 * This is where the continuous integrator lives: every ingested intent is
 * immediately checked against the trunk window — disjoint cones fold
 * lock-free, overlaps open a negotiation. Serialization per stream gives us
 * strong ordering exactly where merge order matters, nowhere else.
 */
export class StreamCoordinator extends DurableObject<Env> {
  private artifacts(): ArtifactLayer {
    const enabled = this.env.USE_ARTIFACTS === "1" && !!this.env.ARTIFACTS;
    return new ArtifactLayer(enabled ? this.env.ARTIFACTS : undefined);
  }

  private async load<T>(key: string, fallback: T): Promise<T> {
    return ((await this.ctx.storage.get(key)) as T) ?? fallback;
  }

  async ensureStream(stream: string) {
    const arts = this.artifacts();
    const { repo, remote } = await arts.ensureStreamRepo(stream);
    await this.ctx.storage.put("meta", { stream, repo, remote, ts: Date.now() });
    return { stream, repo, remote, artifacts: arts.enabled };
  }

  async getState() {
    const log = await this.load<LogEntry[]>("log", []);
    const trunk = await this.load<TrunkState>("trunk", { head: null, folds: 0 });
    const pending = await this.load<string[]>("pending", []);
    const negotiations = await this.load<NegotiationRecord[]>("negotiations", []);
    const meta = await this.load("meta", null);
    return { meta, log, trunk, pending, negotiations };
  }

  async ingest(raw: Omit<Intent, "id" | "stream"> & { id?: string }, stream: string) {
    const id = await sealIntent({ ...raw, stream, parents: raw.parents ?? [] } as any);
    const intent: Intent = { ...raw, stream, parents: raw.parents ?? [], id } as Intent;
    if (raw.id && raw.id !== id) {
      return { ok: false as const, error: "intent id does not match content hash" };
    }

    await this.ctx.storage.put(`intent:${id}`, intent);
    const log = await this.load<LogEntry[]>("log", []);
    log.push({ id, stream, goal: intent.goal, ts: Date.now() });
    await this.ctx.storage.put("log", log);

    // The git-visible record lives in the stream's Artifacts repo, mirrored
    // by any git client via GET /v1/streams/:stream/git (`weave mirror`).
    // The Worker never touches git itself: binding RPCs only.

    // continuous integrator
    const result = await this.integrate(intent);
    return { ok: true as const, id, ...result };
  }

  /** Fold pending intents into the trunk; open negotiations on overlap.
   *
   *  Causality matters: an intent only contends with intents it has NOT
   *  seen. Anything at or before its parents in the log is a causal
   *  predecessor (a sequential edit, like a rebase) — not a conflict.
   *  Only the concurrent suffix after the newest parent is checked.
   */
  private async integrate(intent: Intent) {
    const trunk = await this.load<TrunkState>("trunk", { head: null, folds: 0 });
    const pending = await this.load<string[]>("pending", []);
    const log = await this.load<LogEntry[]>("log", []);

    // No receipt, no merge: unverified intents are recorded but never fold.
    // They wait in pending until a verification receipt arrives.
    if (!intent.verification?.passed) {
      if (!pending.includes(intent.id)) pending.push(intent.id);
      await this.ctx.storage.put("pending", pending);
      return { integrated: false, awaiting_verification: true as const };
    }

    const parentIds = new Set(intent.parents ?? []);
    let cutoff = -1;
    log.forEach((e, i) => {
      if (parentIds.has(e.id)) cutoff = Math.max(cutoff, i);
    });
    // concurrent suffix: arrived after the newest parent, excluding self
    const window = log.filter((e, i) => i > cutoff && e.id !== intent.id).slice(-50);
    const rivals: Intent[] = [];
    for (const e of window) {
      const it = await this.ctx.storage.get<Intent>(`intent:${e.id}`);
      if (it) rivals.push(it);
    }

    for (const other of rivals) {
      const { hit, why } = findConflict(intent, other);
      if (hit) {
        const rec = await this.openNegotiation(intent, other, why);
        // won the negotiation → fold now; the loser stays pending as a ghost
        if (rec.outcome === "merged" && rec.winner === intent.id) {
          trunk.head = intent.id;
          trunk.folds += 1;
          await this.ctx.storage.put("trunk", trunk);
          const idx = pending.indexOf(intent.id);
          if (idx >= 0) pending.splice(idx, 1);
          await this.ctx.storage.put("pending", pending);
          return { integrated: true, trunk_head: trunk.head, folds: trunk.folds,
                   won_negotiation: rec.id };
        }
        if (!pending.includes(intent.id)) pending.push(intent.id);
        await this.ctx.storage.put("pending", pending);
        return { integrated: false, negotiation: rec.id, reason: why };
      }
    }

    // disjoint from everything in the window → fold lock-free
    trunk.head = intent.id;
    trunk.folds += 1;
    await this.ctx.storage.put("trunk", trunk);
    const idx = pending.indexOf(intent.id);
    if (idx >= 0) pending.splice(idx, 1);
    await this.ctx.storage.put("pending", pending);
    return { integrated: true, trunk_head: trunk.head, folds: trunk.folds };
  }

  /**
   * Rebase-and-retry: re-run integration for every pending intent with
   * parents fast-forwarded to the current trunk head. Intents that are now
   * disjoint fold; the rest keep their (new) negotiation records.
   * This is the prototype's answer to "rebase hell": the machine does it.
   */
  async retryPending() {
    const trunk = await this.load<TrunkState>("trunk", { head: null, folds: 0 });
    const pending = await this.load<string[]>("pending", []);
    const retried: string[] = [];
    const stillPending: string[] = [];
    for (const id of [...pending]) {
      const intent = await this.ctx.storage.get<Intent>(`intent:${id}`);
      if (!intent) continue;
      if (trunk.head) intent.parents = [trunk.head];
      await this.ctx.storage.put(`intent:${id}`, intent);
      const r = await this.integrate(intent);
      if (r.integrated) retried.push(id);
      else stillPending.push(id);
    }
    return { retried: retried.length, still_pending: stillPending.length };
  }

  /** Attach a verification receipt to an intent; re-integrate if it was waiting. */
  async verifyIntent(id: string, receipt: { tests: string[]; passed: boolean; sandbox?: string }) {
    const intent = await this.ctx.storage.get<Intent>(`intent:${id}`);
    if (!intent) return { ok: false as const, error: "intent not found" };
    intent.verification = receipt;
    await this.ctx.storage.put(`intent:${id}`, intent);
    const r = await this.integrate(intent);
    return { ok: true as const, id, ...r };
  }

  private async openNegotiation(a: Intent, b: Intent, reason: string) {
    const va = !!a.verification?.passed;
    const vb = !!b.verification?.passed;
    const transcript = [
      { speaker: "system", message: `negotiation opened: ${reason}` },
      { speaker: a.author.agent_id, message: a.rationale || `intends: ${a.goal}` },
      { speaker: b.author.agent_id, message: b.rationale || `intends: ${b.goal}` },
    ];
    let outcome: "merged" | "escalated";
    let winner: string | null = null;
    let ghost_genes: NegotiationRecord["ghost_genes"] = [];
    let human_context = "";
    if (va !== vb) {
      const w = va ? a : b;
      const l = va ? b : a;
      outcome = "merged";
      winner = w.id;
      ghost_genes = [{ intent: l.id, goal: l.goal, superseded_by: w.id }];
      transcript.push({
        speaker: "arbiter",
        message: `exactly one verified intent: ${w.author.agent_id} wins; ` +
          `${l.author.agent_id}'s change parked as ghost gene`,
      });
    } else {
      outcome = "escalated";
      human_context = `contested: '${a.goal}' vs '${b.goal}'; overlap: ${reason}`;
      transcript.push({
        speaker: "arbiter",
        message: `both intents verified=${va}: no safe automatic resolution — escalating`,
      });
    }
    const rec: NegotiationRecord = {
      id: `ng-${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`,
      intents: [a.id, b.id],
      reason,
      transcript,
      outcome,
      winner,
      ghost_genes,
      human_context,
      ts: Date.now(),
    };
    const negotiations = await this.load<NegotiationRecord[]>("negotiations", []);
    negotiations.push(rec);
    await this.ctx.storage.put("negotiations", negotiations);
    return rec;
  }

  async getIntent(id: string) {
    return this.ctx.storage.get<Intent>(`intent:${id}`);
  }
}
