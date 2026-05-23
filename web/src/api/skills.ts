/**
 * API client for /api/skills — Phase 4.
 *
 * Auth: all endpoints require credentials (operator token via session cookie).
 */

import { parseJson } from "./_http";

export type SkillRow = {
  id: number;
  slug: string;
  display_name: string;
  description: string | null;
  source: string;
  version: string | null;
  install_path: string;
  origin_url: string | null;
  installed_at: string;
  is_enabled: boolean;
};

export type SkillRegistryEntry = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  version: string | null;
  source_url: string | null;
  tags: string[];
};

export async function listSkills(): Promise<SkillRow[]> {
  const res = await fetch("/api/skills", { credentials: "include" });
  return parseJson<SkillRow[]>(res);
}

export async function scanLocalSkills(): Promise<{ added: number; removed: number }> {
  const res = await fetch("/api/skills/scan", {
    method: "POST",
    credentials: "include",
  });
  return parseJson<{ added: number; removed: number }>(res);
}

export async function installSkillFromZip(file: File): Promise<SkillRow> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/skills/install/zip", {
    method: "POST",
    credentials: "include",
    body: form,
  });
  return parseJson<SkillRow>(res);
}

export async function installSkillFromRegistry(registry_id: string): Promise<SkillRow> {
  const res = await fetch("/api/skills/install/registry", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ registry_id }),
  });
  return parseJson<SkillRow>(res);
}

export async function deleteSkill(slug: string): Promise<void> {
  const res = await fetch(`/api/skills/${encodeURIComponent(slug)}`, {
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

export async function searchSkillRegistry(q: string): Promise<SkillRegistryEntry[]> {
  const res = await fetch(
    `/api/skills/registry/search?q=${encodeURIComponent(q)}`,
    { credentials: "include" },
  );
  return parseJson<SkillRegistryEntry[]>(res);
}
