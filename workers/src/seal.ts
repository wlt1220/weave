import type { CallGraph, Intent } from "./types";

/** Canonical JSON for content addressing (mirrors the Python prototype). */
export function canonical(obj: unknown): string {
  return JSON.stringify(sortKeys(obj));
}

function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v).sort()) out[k] = sortKeys((v as any)[k]);
    return out;
  }
  return v;
}

export async function sealIntent(intent: Omit<Intent, "id">): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(intent));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
