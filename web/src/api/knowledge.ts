export interface KnowledgeDocMeta {
  id: string;
  path: string;
  updated_at: string | null;
  char_count: number;
  truncated_preview: string;
}

export interface KnowledgeIndex {
  docs: KnowledgeDocMeta[];
  budgets: {
    instructions: number;
    memory: number;
    contact: number;
  };
}

export interface KnowledgeDoc {
  content: string;
  id: string;
  char_count: number;
  updated_at: string | null;
}

export interface ContactSummary {
  contact: string;
  fact_count: number;
  updated_at: string | null;
}

export interface ContactFact {
  key: string;
  value: string;
  source?: string;
  updated_at?: string;
}

export interface AgentNote {
  key: string;
  value: string;
  updated_at?: string;
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: "include", ...init });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${url}: ${res.status}${detail ? ` — ${detail}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchKnowledgeIndex(): Promise<KnowledgeIndex> {
  return apiJson("/api/knowledge");
}

export async function fetchInstructions(): Promise<KnowledgeDoc> {
  return apiJson("/api/knowledge/instructions");
}

export async function saveInstructions(content: string): Promise<KnowledgeDocMeta> {
  return apiJson("/api/knowledge/instructions", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function fetchMemory(): Promise<KnowledgeDoc> {
  return apiJson("/api/knowledge/memory");
}

export async function saveMemory(content: string): Promise<KnowledgeDocMeta> {
  return apiJson("/api/knowledge/memory", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function fetchKnowledgeContacts(): Promise<{ contacts: ContactSummary[] }> {
  return apiJson("/api/knowledge/contacts");
}

export async function fetchContactFacts(contact: string): Promise<{
  contact: string;
  facts: ContactFact[];
}> {
  return apiJson(`/api/memory/${encodeURIComponent(contact)}`);
}

export async function upsertContactFact(
  contact: string,
  key: string,
  value: string,
): Promise<{ stored: boolean }> {
  return apiJson(`/api/memory/${encodeURIComponent(contact)}/facts`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, value }),
  });
}

export async function deleteContactFact(
  contact: string,
  key: string,
): Promise<{ deleted: boolean }> {
  return apiJson(
    `/api/memory/${encodeURIComponent(contact)}/facts/${encodeURIComponent(key)}`,
    { method: "DELETE" },
  );
}

export async function fetchAgentNotes(): Promise<{ items: AgentNote[] }> {
  return apiJson("/api/memory/agent-notes");
}

export async function upsertAgentNote(key: string, value: string): Promise<{ stored: boolean }> {
  return apiJson("/api/memory/agent-notes", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, value }),
  });
}

export async function deleteAgentNote(key: string): Promise<{ deleted: boolean }> {
  return apiJson(`/api/memory/agent-notes/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
}
