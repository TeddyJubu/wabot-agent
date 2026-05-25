export interface KnowledgeDocMeta {
  id: string;
  path: string;
  updated_at: string | null;
  char_count: number;
  truncated_preview: string;
  /**
   * Optimistic-concurrency token: first 16 hex chars of SHA-256 over the
   * file bytes. Send back as `If-Match` on the next PUT so the server can
   * reject stale writes with a 409 instead of silently clobbering a
   * concurrent edit.
   */
  version: string;
}

export interface KnowledgeIndex {
  docs: KnowledgeDocMeta[];
  budgets: {
    instructions: number;
    contact: number;
  };
}

/**
 * Error thrown when the server rejects a save because the content exceeds the
 * configured budget. The backend returns HTTP 413 with a JSON body containing
 * the budget and the actual content length so callers can surface a precise
 * inline message instead of falling back to the generic save-failed text.
 */
export class KnowledgeBudgetExceededError extends Error {
  readonly status = 413 as const;
  readonly budget: number;
  readonly actual: number;
  constructor(budget: number, actual: number) {
    super(`Content exceeds budget (${actual} > ${budget})`);
    this.name = "KnowledgeBudgetExceededError";
    this.budget = budget;
    this.actual = actual;
  }
}

/**
 * Error thrown when the server rejects a save because the supplied
 * `If-Match` token does not match the current on-disk version (HTTP 409).
 * Carries the server's authoritative current content + version so the
 * client can offer the operator a "Reload" or "Overwrite anyway" choice
 * without re-fetching.
 */
export class KnowledgeStaleVersionError extends Error {
  readonly status = 409 as const;
  readonly currentVersion: string;
  readonly currentContent: string;
  readonly submittedVersion: string | null;
  constructor(
    currentVersion: string,
    currentContent: string,
    submittedVersion: string | null,
  ) {
    super(
      `Stale version (submitted=${submittedVersion ?? "<none>"}, current=${currentVersion})`,
    );
    this.name = "KnowledgeStaleVersionError";
    this.currentVersion = currentVersion;
    this.currentContent = currentContent;
    this.submittedVersion = submittedVersion;
  }
}

export interface KnowledgeDoc {
  content: string;
  id: string;
  char_count: number;
  updated_at: string | null;
  version: string;
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
    // Phase 2a: the knowledge PUT endpoint enforces the character budget and
    // returns 413 with `{ detail, budget, actual }`. Surface that as a typed
    // error so the editor can render a precise inline message and stop the
    // autosave retry loop. Be defensive: the body shape may be nested under
    // FastAPI's `detail` envelope, or it may arrive flat — accept both.
    if (res.status === 413) {
      const body = (await res
        .json()
        .catch(() => null)) as
        | { budget?: number; actual?: number; detail?: { budget?: number; actual?: number } }
        | null;
      const payload = body?.detail && typeof body.detail === "object" ? body.detail : body;
      const budget = typeof payload?.budget === "number" ? payload.budget : 0;
      const actual = typeof payload?.actual === "number" ? payload.actual : 0;
      throw new KnowledgeBudgetExceededError(budget, actual);
    }
    // Optimistic-concurrency 409: the server rejected an If-Match. The
    // body carries the authoritative current_version + current_content
    // so the client can render a conflict banner without re-fetching.
    // Same FastAPI nesting tolerance as the 413 branch above.
    if (res.status === 409) {
      const body = (await res.json().catch(() => null)) as
        | {
            current_version?: string;
            current_content?: string;
            submitted_version?: string | null;
            detail?: {
              current_version?: string;
              current_content?: string;
              submitted_version?: string | null;
            };
          }
        | null;
      const payload =
        body?.detail && typeof body.detail === "object" ? body.detail : body;
      const currentVersion = typeof payload?.current_version === "string"
        ? payload.current_version
        : "";
      const currentContent = typeof payload?.current_content === "string"
        ? payload.current_content
        : "";
      const submittedVersion = typeof payload?.submitted_version === "string"
        ? payload.submitted_version
        : null;
      throw new KnowledgeStaleVersionError(
        currentVersion,
        currentContent,
        submittedVersion,
      );
    }
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

export async function saveInstructions(
  content: string,
  ifMatch?: string,
): Promise<KnowledgeDocMeta> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // Only send If-Match when the caller has a version to assert against.
  // Absent header → server bypasses the version check (CLI / curl path).
  if (ifMatch) headers["If-Match"] = ifMatch;
  return apiJson("/api/knowledge/instructions", {
    method: "PUT",
    headers,
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
