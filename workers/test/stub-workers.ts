/** Minimal DurableObject stub: StreamCoordinator only uses ctx.storage + env. */
export class DurableObject<Env = unknown> {
  protected ctx: {
    storage: {
      get<T>(key: string): Promise<T | undefined>;
      put(key: string, value: unknown): Promise<void>;
    };
  };
  protected env: Env;
  constructor(ctx: DurableObject["ctx"], env: Env) {
    this.ctx = ctx;
    this.env = env;
  }
}
