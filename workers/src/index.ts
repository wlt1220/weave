import { Hono } from "hono";
import { StreamCoordinator } from "./coordinator";
import { ArtifactLayer } from "./artifacts";

interface Env {
  ARTIFACTS?: any;
  WEAVE_OBJECTS?: R2Bucket;
  USE_ARTIFACTS?: string;
  STREAM_COORDINATOR: DurableObjectNamespace<StreamCoordinator>;
}

const app = new Hono<{ Bindings: Env }>();

function coord(env: Env, stream: string) {
  const id = env.STREAM_COORDINATOR.idFromName(`stream-${stream}`);
  return env.STREAM_COORDINATOR.get(id);
}

app.get("/", (c) =>
  c.json({
    service: "weave-coordinator",
    version: "0.1.0",
    description: "coordination plane for agent-native version control",
  })
);

// create (or ensure) a stream → provisions the Artifacts repo
app.post("/v1/streams", async (c) => {
  const { stream } = await c.req.json();
  if (!stream || typeof stream !== "string")
    return c.json({ error: "stream is required" }, 400);
  const stub = coord(c.env, stream);
  const meta = await stub.ensureStream(stream);
  return c.json(meta, 201);
});

// ingest an intent → validated, sealed, logged, continuously integrated
app.post("/v1/streams/:stream/intents", async (c) => {
  const stream = c.req.param("stream");
  const body = await c.req.json();
  if (!body.goal || !body.author?.agent_id || !Array.isArray(body.operations))
    return c.json({ error: "goal, author.agent_id and operations are required" }, 400);
  const stub = coord(c.env, stream);
  const res = await stub.ingest({ ...body, created_at: new Date().toISOString() }, stream);
  if (!res.ok) return c.json({ error: res.error }, 400);
  return c.json(res, 201);
});

app.get("/v1/streams/:stream", async (c) => {
  const stub = coord(c.env, c.req.param("stream"));
  return c.json(await stub.getState());
});

app.get("/v1/streams/:stream/intents/:id", async (c) => {
  const stub = coord(c.env, c.req.param("stream"));
  const intent = await stub.getIntent(c.req.param("id"));
  if (!intent) return c.json({ error: "not found" }, 404);
  return c.json(intent);
});

// rebase-and-retry all pending intents against the current trunk head
app.post("/v1/streams/:stream/retry", async (c) => {
  const stub = coord(c.env, c.req.param("stream"));
  return c.json(await stub.retryPending());
});

// attach a verification receipt; re-integrates if the intent was waiting
app.post("/v1/streams/:stream/intents/:id/verify", async (c) => {
  const stub = coord(c.env, c.req.param("stream"));
  const receipt = await c.req.json();
  if (typeof receipt.passed !== "boolean")
    return c.json({ error: "receipt.passed (boolean) is required" }, 400);
  const res = await stub.verifyIntent(c.req.param("id"), {
    tests: receipt.tests ?? [],
    passed: receipt.passed,
    sandbox: receipt.sandbox,
  });
  if (!res.ok) return c.json({ error: res.error }, 404);
  return c.json(res);
});

// the git bridge: git-over-HTTPS remote + short-lived token for this stream
app.get("/v1/streams/:stream/git", async (c) => {
  const stream = c.req.param("stream");
  const arts = new ArtifactLayer(
    c.env.USE_ARTIFACTS === "1" && c.env.ARTIFACTS ? c.env.ARTIFACTS : undefined
  );
  if (!arts.enabled)
    return c.json({ error: "artifacts not enabled (set USE_ARTIFACTS=1 with a Cloudflare account)" }, 503);
  const access = await arts.gitAccess(stream);
  if (!access) return c.json({ error: "stream repo not found" }, 404);
  return c.json({ stream, ...access, expires_in_seconds: 3600 });
});

app.notFound((c) => c.json({ error: "not found" }, 404));

export default app;
export { StreamCoordinator };
