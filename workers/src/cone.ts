import type { CallGraph, Intent } from "./types";

/**
 * Conflict rule (TS port of weave/cone.py):
 * two intents conflict iff one touches a node the other transitively
 * depends on — or the same node. Nodes that merely share a dependency
 * do NOT conflict.
 */

type Graph = Map<string, Set<string>>;

function buildGraph(intents: Intent[], file: string): Graph {
  const g: Graph = new Map();
  for (const it of intents) {
    const fg = it.graph?.[file] ?? {};
    for (const [node, info] of Object.entries(fg)) {
      if (!g.has(node)) g.set(node, new Set());
      for (const c of info.calls ?? []) g.get(node)!.add(c);
    }
  }
  return g;
}

function dependsOn(g: Graph, a: string, b: string): boolean {
  const seen = new Set<string>();
  const stack = [a];
  while (stack.length) {
    const cur = stack.pop()!;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const callee of g.get(cur) ?? []) {
      if (callee === b) return true;
      stack.push(callee);
    }
  }
  return false;
}

function nodesOf(it: Intent, file: string): string[] {
  return it.operations.filter((o) => o.file === file && o.node).map((o) => o.node!);
}

export function findConflict(
  a: Intent,
  b: Intent
): { hit: boolean; why: string } {
  const files = new Set([
    ...a.operations.map((o) => o.file),
    ...b.operations.map((o) => o.file),
  ]);
  for (const f of files) {
    const g = buildGraph([a, b], f);
    for (const na of nodesOf(a, f)) {
      for (const nb of nodesOf(b, f)) {
        if (na === nb) return { hit: true, why: `same node '${na}' in ${f}` };
        if (dependsOn(g, na, nb))
          return { hit: true, why: `'${na}' depends on '${nb}' in ${f}` };
        if (dependsOn(g, nb, na))
          return { hit: true, why: `'${nb}' depends on '${na}' in ${f}` };
      }
    }
  }
  return { hit: false, why: "" };
}
