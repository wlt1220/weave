import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    alias: {
      // StreamCoordinator only touches ctx.storage + env; run it in plain
      // node with a stub DurableObject base class (no workerd needed).
      "cloudflare:workers": path.resolve(import.meta.dirname, "test/stub-workers.ts"),
    },
  },
});
