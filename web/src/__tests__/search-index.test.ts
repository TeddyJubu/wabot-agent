import { describe, expect, it, vi, beforeEach } from "vitest";

import type { KnowledgeIndex } from "@/api/knowledge";
import type { AgentSummary } from "@/api/agents";
import type { ToolsListResponse } from "@/api/tools";

// ---------------------------------------------------------------------------
// All four API surfaces are mocked at module scope. Each test can override the
// individual mock to simulate a failure path or a custom fixture.
// ---------------------------------------------------------------------------

vi.mock("@/api/knowledge", () => ({
  fetchKnowledgeIndex: vi.fn(),
}));

vi.mock("@/api/agents", () => ({
  listAgents: vi.fn(),
}));

vi.mock("@/api/tools", () => ({
  listTools: vi.fn(),
}));

import { fetchKnowledgeIndex } from "@/api/knowledge";
import { listAgents } from "@/api/agents";
import { listTools } from "@/api/tools";
import {
  buildSearchIndex,
  clearSearchIndexCache,
  rankResults,
  type SearchResult,
} from "@/searchIndex";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const KNOWLEDGE_FIXTURE: KnowledgeIndex = {
  docs: [
    {
      id: "instructions",
      path: "knowledge/instructions.md",
      updated_at: null,
      char_count: 12,
      truncated_preview: "qr pairing notes",
      version: "0000000000000000",
    },
  ],
  budgets: { instructions: 1000, contact: 1000 },
};

const AGENTS_FIXTURE: AgentSummary[] = [
  {
    id: 1,
    slug: "router",
    display_name: "Router",
    description: "Default routing agent",
    is_builtin: true,
    is_enabled: true,
    parent_slug: null,
    handoff_filter: null,
    tool_count: 4,
    skill_count: 2,
    updated_at: "2026-01-01T00:00:00Z",
  },
];

const TOOLS_FIXTURE: ToolsListResponse = {
  native: [
    {
      id: 11,
      kind: "native",
      source_ref: "native:send_message",
      name: "send_message",
      description: "Send a WhatsApp message",
      is_enabled: true,
      is_assigned_to: [],
    },
  ],
  mcp: [],
  composio: [
    {
      id: 22,
      kind: "composio",
      source_ref: "composio:gmail_send",
      name: "gmail_send",
      description: "Send a Gmail message via Composio",
      is_enabled: true,
      is_assigned_to: [],
    },
  ],
  skill_action: [],
};

// ---------------------------------------------------------------------------
// Setup — reset mocks + cache between cases.
// ---------------------------------------------------------------------------

beforeEach(() => {
  clearSearchIndexCache();
  vi.mocked(fetchKnowledgeIndex).mockReset();
  vi.mocked(listAgents).mockReset();
  vi.mocked(listTools).mockReset();

  vi.mocked(fetchKnowledgeIndex).mockResolvedValue(KNOWLEDGE_FIXTURE);
  vi.mocked(listAgents).mockResolvedValue(AGENTS_FIXTURE);
  vi.mocked(listTools).mockResolvedValue(TOOLS_FIXTURE);
});

// ---------------------------------------------------------------------------
// buildSearchIndex — happy path + graceful degradation
// ---------------------------------------------------------------------------

describe("buildSearchIndex", () => {
  it("returns commands + knowledge + agents + tools + settings entries", async () => {
    const items = await buildSearchIndex();
    const kinds = new Set(items.map((i) => i.kind));
    expect(kinds.has("command")).toBe(true);
    expect(kinds.has("knowledge")).toBe(true);
    expect(kinds.has("agent")).toBe(true);
    expect(kinds.has("tool")).toBe(true);
    expect(kinds.has("settings")).toBe(true);

    // Spot-check a knowledge entry was mapped through.
    const knowledgePaths = items
      .filter((i) => i.kind === "knowledge")
      .map((i) => i.label);
    expect(knowledgePaths).toContain("knowledge/instructions.md");

    // Spot-check an agent and a tool were mapped through.
    expect(items.some((i) => i.kind === "agent" && i.label === "Router")).toBe(
      true,
    );
    expect(
      items.some((i) => i.kind === "tool" && i.label === "send_message"),
    ).toBe(true);
  });

  it("degrades gracefully when one API fails (knowledge rejects)", async () => {
    vi.mocked(fetchKnowledgeIndex).mockRejectedValueOnce(
      new Error("kn boom"),
    );

    const items = await buildSearchIndex();
    const kinds = new Set(items.map((i) => i.kind));

    // Knowledge is absent...
    expect(kinds.has("knowledge")).toBe(false);
    // ...but the other kinds still come through.
    expect(kinds.has("command")).toBe(true);
    expect(kinds.has("agent")).toBe(true);
    expect(kinds.has("tool")).toBe(true);
    expect(kinds.has("settings")).toBe(true);
  });

  it("returns sentinel mappings that match the documented contract", async () => {
    const items = await buildSearchIndex();
    const knowledge = items.find((i) => i.kind === "knowledge");
    const agent = items.find((i) => i.kind === "agent");
    const tool = items.find((i) => i.kind === "tool");
    const settings = items.find((i) => i.kind === "settings");
    expect(knowledge?.sentinel).toBe("__open_knowledge__");
    expect(agent?.sentinel).toBe("__open_slide_over__:agents");
    expect(tool?.sentinel).toBe("__open_slide_over__:tools");
    expect(settings?.sentinel).toBe("__open_slide_over__:settings");
  });
});

// ---------------------------------------------------------------------------
// rankResults — pure scoring
// ---------------------------------------------------------------------------

describe("rankResults", () => {
  const fixture: SearchResult[] = [
    {
      kind: "command",
      id: "/qr",
      label: "/qr",
      description: "Open WhatsApp pairing QR",
      sentinel: "__open_pair__",
    },
    {
      kind: "knowledge",
      id: "k1",
      label: "qr-tagged-knowledge-doc",
      description: "qr pairing notes",
      sentinel: "__open_knowledge__",
    },
    {
      kind: "agent",
      id: "a1",
      label: "Pair WhatsApp",
      description: "Pairing helper",
      sentinel: "__open_slide_over__:agents",
    },
    {
      kind: "tool",
      id: "t1",
      label: "open pair",
      description: "Open pairing flow",
      sentinel: "__open_slide_over__:tools",
    },
    {
      kind: "settings",
      id: "s1",
      label: "Provider",
      description: "Model provider",
      sentinel: "__open_slide_over__:settings",
    },
  ];

  it("returns the full input list when query is empty", () => {
    const out = rankResults("", fixture);
    expect(out).toHaveLength(fixture.length);
  });

  it("ranks an exact /qr command above a knowledge doc whose description contains qr", () => {
    const out = rankResults("qr", fixture);
    expect(out[0]?.id).toBe("/qr");
    // The knowledge doc still shows up (label includes "qr").
    expect(out.some((r) => r.id === "k1")).toBe(true);
    // Exact match (1000) beats label-includes (100) for the knowledge entry.
    const qrIdx = out.findIndex((r) => r.id === "/qr");
    const knIdx = out.findIndex((r) => r.id === "k1");
    expect(qrIdx).toBeLessThan(knIdx);
  });

  it("prefers prefix over includes for the same query", () => {
    const out = rankResults("pair", fixture);
    const prefixIdx = out.findIndex((r) => r.label === "Pair WhatsApp");
    const includesIdx = out.findIndex((r) => r.label === "open pair");
    expect(prefixIdx).toBeGreaterThanOrEqual(0);
    expect(includesIdx).toBeGreaterThanOrEqual(0);
    expect(prefixIdx).toBeLessThan(includesIdx);
  });

  it("breaks ties by kind order (Command before Knowledge)", () => {
    // Both labels equally "include" the query; same description coverage.
    const tie: SearchResult[] = [
      {
        kind: "knowledge",
        id: "K",
        label: "alpha",
        description: "",
        sentinel: "k",
      },
      {
        kind: "command",
        id: "C",
        label: "alpha",
        description: "",
        sentinel: "c",
      },
    ];
    const out = rankResults("alpha", tie);
    expect(out[0]?.kind).toBe("command");
    expect(out[1]?.kind).toBe("knowledge");
  });

  it("excludes zero-score items", () => {
    const out = rankResults("zzz-no-match", fixture);
    expect(out).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Perf — synthetic 200-item index must rank in < 50 ms.
// ---------------------------------------------------------------------------

describe("rankResults performance", () => {
  it("ranks 200 items in under 50 ms", () => {
    const items: SearchResult[] = [];
    const kinds: SearchResult["kind"][] = [
      "knowledge",
      "agent",
      "tool",
      "settings",
    ];
    for (const k of kinds) {
      for (let i = 0; i < 50; i++) {
        items.push({
          kind: k,
          id: `${k}-${i}`,
          label: `${k} item ${i} alpha`,
          description: `description for ${k} ${i}`,
          sentinel: `__sentinel__:${k}:${i}`,
        });
      }
    }
    expect(items).toHaveLength(200);

    const start = performance.now();
    const out = rankResults("a", items);
    const elapsed = performance.now() - start;

    expect(out.length).toBeGreaterThan(0);
    // Shared CI runners are slower than dev laptops; widen the budget there
    // so a noisy worker doesn't flake the test (real regressions still trip
    // the 250ms ceiling, which is ~5x our normal local timing).
    const PERF_BUDGET_MS = process.env.CI ? 250 : 50;
    expect(elapsed).toBeLessThan(PERF_BUDGET_MS);
  });
});
