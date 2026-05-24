/**
 * Cross-cutting search index — Epic C5 (N11).
 *
 * Builds a flat in-memory list of searchable destinations the command palette
 * surfaces: slash commands, knowledge docs, agents, tools, and a curated set
 * of well-known settings keys.
 *
 * Each non-command fetch is wrapped in try/catch so a single failed API does
 * not poison the whole index — the kind is simply absent.
 */

import { SLASH_COMMANDS } from "@/hooks/useSlashCommands";
import { fetchKnowledgeIndex } from "@/api/knowledge";
import { listAgents } from "@/api/agents";
import { listTools } from "@/api/tools";
import type { ToolRow } from "@/api/tools";

export type SearchResultKind =
  | "command"
  | "knowledge"
  | "agent"
  | "tool"
  | "settings";

export interface SearchResult {
  kind: SearchResultKind;
  /** Stable id within its kind — used as React key. */
  id: string;
  /** Visible primary label. */
  label: string;
  /** Optional secondary line (e.g. agent slug, tool name, doc snippet). */
  description?: string;
  /** Sentinel string the palette will dispatch when this result is picked. */
  sentinel: string;
}

// ---------------------------------------------------------------------------
// Static metadata
// ---------------------------------------------------------------------------

/** Stable ordering used for tie-breaking inside `rankResults`. */
const KIND_ORDER: Record<SearchResultKind, number> = {
  command: 0,
  knowledge: 1,
  agent: 2,
  tool: 3,
  settings: 4,
};

/**
 * Well-known settings entries. These mirror the tabs from `SettingsPage` so
 * users typing things like "policy" or "provider" land on the right page.
 * Each entry routes to the settings slide-over via the existing dispatch
 * sentinel — the UI flag will translate that into `/settings` under v2.
 */
interface SettingsEntry {
  id: string;
  label: string;
  description: string;
  /** Extra keywords folded into `description` for search ranking. */
  keywords: string;
}

const SETTINGS_ENTRIES: readonly SettingsEntry[] = [
  {
    id: "provider",
    label: "Provider",
    description: "Model provider (OpenAI, Codex, OpenRouter, Ollama)",
    keywords: "model provider openai codex openrouter ollama llm",
  },
  {
    id: "routing",
    label: "Routing",
    description: "Per-purpose model routing",
    keywords: "routing model purpose subagent",
  },
  {
    id: "wabot",
    label: "Wabot",
    description: "Wabot daemon endpoint & token",
    keywords: "wabot daemon endpoint token whatsapp",
  },
  {
    id: "policy",
    label: "Policy",
    description: "Send policy (dry_run, allowlist, owner, allow_all)",
    keywords: "policy send dry run allowlist owner allow all recipients",
  },
  {
    id: "experimental",
    label: "Experimental",
    description: "Experimental settings & subagents",
    keywords: "experimental subagents flags",
  },
] as const;

// ---------------------------------------------------------------------------
// Builders — each kind is independently fault-tolerant.
// ---------------------------------------------------------------------------

function buildCommandResults(): SearchResult[] {
  return SLASH_COMMANDS.map((c) => ({
    kind: "command" as const,
    id: c.name,
    label: c.name,
    description: c.description,
    sentinel: c.expand(),
  }));
}

async function buildKnowledgeResults(): Promise<SearchResult[]> {
  try {
    const { docs } = await fetchKnowledgeIndex();
    return docs.map((d) => ({
      kind: "knowledge" as const,
      id: `knowledge:${d.id}`,
      label: d.path || d.id,
      description: d.truncated_preview?.slice(0, 80) || undefined,
      sentinel: "__open_knowledge__",
    }));
  } catch {
    return [];
  }
}

async function buildAgentResults(): Promise<SearchResult[]> {
  try {
    const agents = await listAgents();
    return agents.map((a) => ({
      kind: "agent" as const,
      id: `agent:${a.slug}`,
      label: a.display_name || a.slug,
      description: a.description || a.slug,
      sentinel: "__open_slide_over__:agents",
    }));
  } catch {
    return [];
  }
}

async function buildToolResults(): Promise<SearchResult[]> {
  try {
    const tools = await listTools();
    const all: ToolRow[] = [
      ...tools.native,
      ...tools.mcp,
      ...tools.composio,
      ...tools.skill_action,
    ];
    return all.map((t) => ({
      kind: "tool" as const,
      id: `tool:${t.id}`,
      label: t.name,
      description: t.description || t.source_ref,
      sentinel: "__open_slide_over__:tools",
    }));
  } catch {
    return [];
  }
}

function buildSettingsResults(): SearchResult[] {
  return SETTINGS_ENTRIES.map((s) => ({
    kind: "settings" as const,
    id: `settings:${s.id}`,
    label: s.label,
    description: `${s.description} · ${s.keywords}`,
    sentinel: "__open_slide_over__:settings",
  }));
}

/**
 * Build a complete cross-cutting search index. Each kind's fetcher is wrapped
 * so a single API failure degrades gracefully — the kind is just absent from
 * the result list.
 */
export async function buildSearchIndex(): Promise<SearchResult[]> {
  const [knowledge, agents, tools] = await Promise.all([
    buildKnowledgeResults(),
    buildAgentResults(),
    buildToolResults(),
  ]);
  return [
    ...buildCommandResults(),
    ...knowledge,
    ...agents,
    ...tools,
    ...buildSettingsResults(),
  ];
}

// ---------------------------------------------------------------------------
// Cache — lazy build, single shared promise per open.
// ---------------------------------------------------------------------------

let cached: SearchResult[] | null = null;
let cachePromise: Promise<SearchResult[]> | null = null;

export async function getSearchIndex(): Promise<SearchResult[]> {
  if (cached) return cached;
  if (cachePromise) return cachePromise;
  cachePromise = buildSearchIndex().then((r) => {
    cached = r;
    cachePromise = null;
    return r;
  });
  return cachePromise;
}

export function clearSearchIndexCache(): void {
  cached = null;
  cachePromise = null;
}

// ---------------------------------------------------------------------------
// Ranking — pure function over SearchResult[].
// ---------------------------------------------------------------------------

/**
 * Score a single item against a lowercased query. Higher is better. A score
 * of 0 means "no match" and the item should be excluded.
 *
 * Slash-command labels keep their leading "/" as a presentation prefix
 * (so the dropdown shows "/qr"), but that slash is not part of the lexical
 * key users type. Strip it before exact / prefix comparisons so typing
 * "qr" still hits the "/qr" command as an exact match.
 */
function scoreItem(query: string, item: SearchResult): number {
  const rawLabel = item.label.toLowerCase();
  const label =
    item.kind === "command" && rawLabel.startsWith("/")
      ? rawLabel.slice(1)
      : rawLabel;
  if (label === query) return 1000;
  if (label.startsWith(query)) return 500;
  if (label.includes(query)) return 100;
  if (item.description && item.description.toLowerCase().includes(query)) {
    return 50;
  }
  return 0;
}

/**
 * Rank items against the query.
 * - Empty query → return all items in the input's natural order.
 * - Non-empty query → drop zero-score items, sort by:
 *     1. score (desc)
 *     2. kind order (command < knowledge < agent < tool < settings)
 *     3. label A-Z
 */
export function rankResults(
  query: string,
  items: SearchResult[],
): SearchResult[] {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return [...items];

  const scored = items
    .map((item) => ({ item, score: scoreItem(q, item) }))
    .filter((s) => s.score > 0);

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const ko = KIND_ORDER[a.item.kind] - KIND_ORDER[b.item.kind];
    if (ko !== 0) return ko;
    return a.item.label.localeCompare(b.item.label);
  });

  return scored.map((s) => s.item);
}
