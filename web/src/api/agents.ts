/**
 * API client for /api/agents — Phase 3b.
 *
 * Auth: all endpoints require credentials (operator token via session cookie).
 */

import { parseJson } from "./_http";

export type AgentSummary = {
  id: number;
  slug: string;
  display_name: string;
  description: string | null;
  is_builtin: boolean;
  is_enabled: boolean;
  parent_slug: string | null;
  handoff_filter: string | null;
  tool_count: number;
  skill_count: number;
  updated_at: string;
};

export type AgentDetail = AgentSummary & {
  instructions: string;
  tool_ids: number[];
  skill_ids: number[];
};

export type AgentCreate = {
  slug: string;
  display_name: string;
  description?: string | null;
  instructions: string;
  parent_slug?: string | null;
  handoff_filter?: string | null;
};

export type AgentUpdate = Partial<{
  display_name: string;
  description: string | null;
  instructions: string;
  is_enabled: boolean;
  parent_slug: string | null;
  handoff_filter: string | null;
}>;

export type AgentTestResponse = {
  transcript: string;
  tool_calls: Array<Record<string, unknown>>;
  error: string | null;
};

export async function listAgents(): Promise<AgentSummary[]> {
  const res = await fetch("/api/agents", { credentials: "include" });
  return parseJson<AgentSummary[]>(res);
}

export async function getAgent(slug: string): Promise<AgentDetail> {
  const res = await fetch(`/api/agents/${encodeURIComponent(slug)}`, {
    credentials: "include",
  });
  return parseJson<AgentDetail>(res);
}

export async function createAgent(payload: AgentCreate): Promise<AgentDetail> {
  const res = await fetch("/api/agents", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson<AgentDetail>(res);
}

export async function updateAgent(slug: string, patch: AgentUpdate): Promise<AgentDetail> {
  const res = await fetch(`/api/agents/${encodeURIComponent(slug)}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJson<AgentDetail>(res);
}

export async function deleteAgent(slug: string): Promise<void> {
  const res = await fetch(`/api/agents/${encodeURIComponent(slug)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      typeof body.detail === "string" ? body.detail : `Delete failed (${res.status})`,
    );
  }
}

export async function setAgentTools(slug: string, tool_ids: number[]): Promise<AgentDetail> {
  const res = await fetch(`/api/agents/${encodeURIComponent(slug)}/tools`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_ids }),
  });
  return parseJson<AgentDetail>(res);
}

export async function setAgentSkills(slug: string, skill_ids: number[]): Promise<AgentDetail> {
  const res = await fetch(`/api/agents/${encodeURIComponent(slug)}/skills`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill_ids }),
  });
  return parseJson<AgentDetail>(res);
}

export async function testAgent(slug: string, prompt: string): Promise<AgentTestResponse> {
  const res = await fetch(`/api/agents/${encodeURIComponent(slug)}/test`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
  return parseJson<AgentTestResponse>(res);
}
