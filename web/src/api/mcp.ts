/**
 * API client for /api/mcp — Phase 4.
 *
 * Auth: all endpoints require credentials (operator token via session cookie).
 */

import { parseJson } from "./_http";

export type McpServerRow = {
  id: number;
  name: string;
  transport: string;
  config_json: string;
  is_enabled: boolean;
  health_status: string | null;
  health_message: string | null;
  last_checked_at: string | null;
};

export type McpServerCreate = {
  name: string;
  transport: string;
  config_json: Record<string, unknown>;
};

export type McpServerPatch = Partial<{
  name: string;
  transport: string;
  config_json: Record<string, unknown>;
  is_enabled: boolean;
}>;

export type McpRegistryEntry = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  source: "curated" | "composio";
  tags: string[];
  transport_hint: string | null;
};

export type McpCheckResult = {
  health_status: string;
  health_message: string | null;
  tool_count: number;
};

export async function listMcpServers(): Promise<McpServerRow[]> {
  const res = await fetch("/api/mcp/servers", { credentials: "include" });
  return parseJson<McpServerRow[]>(res);
}

export async function createMcpServer(payload: McpServerCreate): Promise<McpServerRow> {
  const res = await fetch("/api/mcp/servers", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson<McpServerRow>(res);
}

export async function updateMcpServer(id: number, patch: McpServerPatch): Promise<McpServerRow> {
  const res = await fetch(`/api/mcp/servers/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJson<McpServerRow>(res);
}

export async function deleteMcpServer(id: number): Promise<void> {
  const res = await fetch(`/api/mcp/servers/${id}`, {
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

export async function checkMcpServer(id: number): Promise<McpCheckResult> {
  const res = await fetch(`/api/mcp/servers/${id}/check`, {
    method: "POST",
    credentials: "include",
  });
  return parseJson<McpCheckResult>(res);
}

export async function searchMcpRegistry(q: string): Promise<McpRegistryEntry[]> {
  const res = await fetch(
    `/api/mcp/registry/search?q=${encodeURIComponent(q)}`,
    { credentials: "include" },
  );
  return parseJson<McpRegistryEntry[]>(res);
}

export async function installMcpFromRegistry(registry_id: string): Promise<McpServerRow> {
  const res = await fetch("/api/mcp/registry/install", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ registry_id }),
  });
  return parseJson<McpServerRow>(res);
}
