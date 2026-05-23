/**
 * API client for /api/tools — Phase 3b.
 *
 * Auth: all endpoints require credentials (operator token via session cookie).
 */

import { parseJson } from "./_http";

export type ToolKind = "native" | "mcp" | "composio" | "skill_action";

export type ToolRow = {
  id: number;
  kind: ToolKind;
  source_ref: string;
  name: string;
  description: string | null;
  is_enabled: boolean;
  is_assigned_to: string[];
};

export type ToolsListResponse = {
  native: ToolRow[];
  mcp: ToolRow[];
  composio: ToolRow[];
  skill_action: ToolRow[];
};

export type ToolRefreshResponse = {
  native_added: number;
  composio_added: number;
  mcp_added: number;
};

export async function listTools(): Promise<ToolsListResponse> {
  const res = await fetch("/api/tools", { credentials: "include" });
  return parseJson<ToolsListResponse>(res);
}

export async function refreshTools(): Promise<ToolRefreshResponse> {
  const res = await fetch("/api/tools/refresh", {
    method: "POST",
    credentials: "include",
  });
  return parseJson<ToolRefreshResponse>(res);
}

export async function toggleTool(id: number, is_enabled: boolean): Promise<ToolRow> {
  const res = await fetch(`/api/tools/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_enabled }),
  });
  return parseJson<ToolRow>(res);
}
