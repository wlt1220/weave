export interface Author {
  agent_id: string;
  model?: string;
  session?: string;
}

export interface Verification {
  tests: string[];
  passed: boolean;
  sandbox?: string;
}

export interface Operation {
  op: string;
  file: string;
  node?: string;
  new_source?: string;
}

/** Per-file function call graph submitted by the client (computed via AST). */
export interface CallGraph {
  [file: string]: { [node: string]: { calls: string[] } };
}

export interface Intent {
  id: string;
  goal: string;
  author: Author;
  plan?: string[];
  operations: Operation[];
  verification?: Verification;
  rationale?: string;
  parents: string[];
  stream: string;
  created_at: string;
  graph?: CallGraph;
}

export interface LogEntry {
  id: string;
  stream: string;
  goal: string;
  ts: number;
}

export interface TrunkState {
  head: string | null;
  folds: number;
}

export interface NegotiationRecord {
  id: string;
  intents: string[];
  reason: string;
  transcript: { speaker: string; message: string }[];
  outcome: "merged" | "escalated";
  winner: string | null;
  ghost_genes: { intent: string; goal: string; superseded_by: string }[];
  human_context: string;
  ts: number;
}
