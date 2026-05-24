import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RegistryBrowserModal } from "@/components/slide-overs/integrations/RegistryBrowserModal";
import type { SkillRegistryEntry } from "@/api/skills";
import type { McpRegistryEntry } from "@/api/mcp";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/skills", () => ({
  searchSkillRegistry: vi.fn(),
  installSkillFromRegistry: vi.fn(),
}));

vi.mock("@/api/mcp", () => ({
  searchMcpRegistry: vi.fn(),
  installMcpFromRegistry: vi.fn(),
}));

import * as skillsApi from "@/api/skills";
import * as mcpApi from "@/api/mcp";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SKILL_ENTRY: SkillRegistryEntry = {
  id: "skill-abc",
  slug: "web-search",
  name: "Web Search Skill",
  description: "Search the web",
  version: "1.0.0",
  source_url: "https://example.com/skill",
  tags: ["search"],
};

const MCP_CURATED: McpRegistryEntry = {
  id: "mcp-curated",
  slug: "brave-search",
  name: "Brave Search MCP",
  description: "Search with Brave",
  source: "curated",
  tags: ["search"],
  transport_hint: "stdio",
};

const MCP_COMPOSIO: McpRegistryEntry = {
  id: "mcp-composio",
  slug: "gmail-mcp",
  name: "Gmail MCP",
  description: "Gmail via Composio",
  source: "composio",
  tags: ["email"],
  transport_hint: "http",
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RegistryBrowserModal — skills mode", () => {
  it("renders skill results and install button", async () => {
    vi.mocked(skillsApi.searchSkillRegistry).mockResolvedValue([SKILL_ENTRY]);

    render(
      <RegistryBrowserModal
        mode="skills"
        onClose={() => undefined}
        onInstalled={() => undefined}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Web Search Skill")).toBeInTheDocument(),
    );
    expect(screen.getByText("Search the web")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^install$/i })).toBeInTheDocument();
  });

  it("search input calls searchSkillRegistry with the query", async () => {
    vi.mocked(skillsApi.searchSkillRegistry).mockResolvedValue([]);

    render(
      <RegistryBrowserModal
        mode="skills"
        onClose={() => undefined}
        onInstalled={() => undefined}
      />,
    );

    const input = screen.getByLabelText(/search registry/i);
    fireEvent.change(input, { target: { value: "search" } });

    // debounce is 300ms — fast-forward via waitFor
    await waitFor(() =>
      expect(skillsApi.searchSkillRegistry).toHaveBeenCalledWith("search"),
    );
  });

  it("Install button calls installSkillFromRegistry with the correct id", async () => {
    vi.mocked(skillsApi.searchSkillRegistry).mockResolvedValue([SKILL_ENTRY]);
    vi.mocked(skillsApi.installSkillFromRegistry).mockResolvedValue({
      id: 1,
      slug: "web-search",
      display_name: "Web Search Skill",
      description: "Search the web",
      source: "registry",
      version: "1.0.0",
      install_path: "/skills/web-search",
      origin_url: "https://example.com/skill",
      installed_at: "2026-01-01T00:00:00",
      is_enabled: true,
    });
    const onInstalled = vi.fn();

    render(
      <RegistryBrowserModal
        mode="skills"
        onClose={() => undefined}
        onInstalled={onInstalled}
      />,
    );

    await waitFor(() => screen.getByText("Web Search Skill"));
    fireEvent.click(screen.getByRole("button", { name: /^install$/i }));

    await waitFor(() =>
      expect(skillsApi.installSkillFromRegistry).toHaveBeenCalledWith("skill-abc"),
    );
    expect(onInstalled).toHaveBeenCalledOnce();
  });
});

describe("RegistryBrowserModal — MCP mode", () => {
  it("renders MCP results with source pills (curated and composio)", async () => {
    vi.mocked(mcpApi.searchMcpRegistry).mockResolvedValue([MCP_CURATED, MCP_COMPOSIO]);

    render(
      <RegistryBrowserModal
        mode="mcp"
        onClose={() => undefined}
        onInstalled={() => undefined}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Brave Search MCP")).toBeInTheDocument(),
    );
    expect(screen.getByText("Gmail MCP")).toBeInTheDocument();

    // Source pills
    expect(screen.getByText("curated")).toBeInTheDocument();
    expect(screen.getByText("composio")).toBeInTheDocument();
  });

  it("source pill differentiates curated vs composio with different styles", async () => {
    vi.mocked(mcpApi.searchMcpRegistry).mockResolvedValue([MCP_CURATED, MCP_COMPOSIO]);

    render(
      <RegistryBrowserModal
        mode="mcp"
        onClose={() => undefined}
        onInstalled={() => undefined}
      />,
    );

    await waitFor(() => screen.getByText("curated"));

    const curatedPill = screen.getByText("curated");
    const composioPill = screen.getByText("composio");

    // Phase D L5 moved these from hard-coded green/blue to the semantic
    // ok/accent tokens. Assert on the new contract.
    expect(curatedPill.className).toContain("text-ok");
    expect(composioPill.className).toContain("text-accent");
  });

  it("search input calls searchMcpRegistry in MCP mode", async () => {
    vi.mocked(mcpApi.searchMcpRegistry).mockResolvedValue([]);

    render(
      <RegistryBrowserModal
        mode="mcp"
        onClose={() => undefined}
        onInstalled={() => undefined}
      />,
    );

    const input = screen.getByLabelText(/search registry/i);
    fireEvent.change(input, { target: { value: "gmail" } });

    await waitFor(() =>
      expect(mcpApi.searchMcpRegistry).toHaveBeenCalledWith("gmail"),
    );
  });

  it("Install button calls installMcpFromRegistry with the correct id", async () => {
    vi.mocked(mcpApi.searchMcpRegistry).mockResolvedValue([MCP_CURATED]);
    vi.mocked(mcpApi.installMcpFromRegistry).mockResolvedValue({
      id: 10,
      name: "brave-search",
      transport: "stdio",
      config_json: "{}",
      is_enabled: true,
      health_status: null,
      health_message: null,
      last_checked_at: null,
    });
    const onInstalled = vi.fn();

    render(
      <RegistryBrowserModal
        mode="mcp"
        onClose={() => undefined}
        onInstalled={onInstalled}
      />,
    );

    await waitFor(() => screen.getByText("Brave Search MCP"));
    fireEvent.click(screen.getByRole("button", { name: /^install$/i }));

    await waitFor(() =>
      expect(mcpApi.installMcpFromRegistry).toHaveBeenCalledWith("mcp-curated"),
    );
    expect(onInstalled).toHaveBeenCalledOnce();
  });
});

describe("RegistryBrowserModal — close behaviour", () => {
  it("close button calls onClose", async () => {
    vi.mocked(skillsApi.searchSkillRegistry).mockResolvedValue([]);
    const onClose = vi.fn();

    render(
      <RegistryBrowserModal mode="skills" onClose={onClose} onInstalled={() => undefined} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /close modal/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
