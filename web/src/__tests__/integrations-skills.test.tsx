import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SkillsSection } from "@/components/slide-overs/integrations/SkillsSection";
import type { SkillRow } from "@/api/skills";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/api/skills", () => ({
  listSkills: vi.fn(),
  scanLocalSkills: vi.fn(),
  installSkillFromZip: vi.fn(),
  deleteSkill: vi.fn(),
  searchSkillRegistry: vi.fn().mockResolvedValue([]),
  installSkillFromRegistry: vi.fn(),
}));

import * as skillsApi from "@/api/skills";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SKILL_LOCAL: SkillRow = {
  id: 1,
  slug: "web-research",
  display_name: "Web Research",
  description: "Research the web",
  source: "local",
  version: "1.0.0",
  install_path: "/skills/web-research",
  origin_url: null,
  installed_at: "2026-01-01T00:00:00",
  is_enabled: true,
};

const SKILL_ZIP: SkillRow = {
  id: 2,
  slug: "my-custom",
  display_name: "My Custom",
  description: null,
  source: "zip",
  version: null,
  install_path: "/skills/my-custom",
  origin_url: null,
  installed_at: "2026-01-02T00:00:00",
  is_enabled: true,
};

const SKILL_REGISTRY: SkillRow = {
  id: 3,
  slug: "from-registry",
  display_name: "From Registry",
  description: "A registry skill",
  source: "registry",
  version: "2.0.0",
  install_path: "/skills/from-registry",
  origin_url: "https://example.com/skill",
  installed_at: "2026-01-03T00:00:00",
  is_enabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SkillsSection — empty state", () => {
  it("renders empty state when no skills", () => {
    render(<SkillsSection skills={[]} onRefresh={() => undefined} />);
    expect(screen.getByText(/No skills installed yet/i)).toBeInTheDocument();
  });

  it("shows Skills (0 installed) header", () => {
    render(<SkillsSection skills={[]} onRefresh={() => undefined} />);
    expect(screen.getByText(/Skills \(0 installed\)/i)).toBeInTheDocument();
  });
});

describe("SkillsSection — skill rows", () => {
  it("renders skill rows with source pills", () => {
    render(
      <SkillsSection
        skills={[SKILL_LOCAL, SKILL_ZIP, SKILL_REGISTRY]}
        onRefresh={() => undefined}
      />,
    );
    expect(screen.getByText("Web Research")).toBeInTheDocument();
    expect(screen.getByText("My Custom")).toBeInTheDocument();
    expect(screen.getByText("From Registry")).toBeInTheDocument();

    expect(screen.getByText("local")).toBeInTheDocument();
    expect(screen.getByText("zip")).toBeInTheDocument();
    expect(screen.getByText("registry")).toBeInTheDocument();
  });

  it("shows install_path as tooltip text", () => {
    render(<SkillsSection skills={[SKILL_LOCAL]} onRefresh={() => undefined} />);
    const pathEl = screen.getByTitle("/skills/web-research");
    expect(pathEl).toBeInTheDocument();
  });
});

describe("SkillsSection — Scan local", () => {
  it("Scan local calls scanLocalSkills and shows delta banner", async () => {
    vi.mocked(skillsApi.scanLocalSkills).mockResolvedValue({ added: 3, removed: 1 });
    const onRefresh = vi.fn();

    render(<SkillsSection skills={[]} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole("button", { name: /scan local folder/i }));

    await waitFor(() =>
      expect(screen.getByText(/3 added/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/1 removed/i)).toBeInTheDocument();
    expect(skillsApi.scanLocalSkills).toHaveBeenCalledOnce();
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});

describe("SkillsSection — Upload", () => {
  it("Upload triggers installSkillFromZip with the File", async () => {
    vi.mocked(skillsApi.installSkillFromZip).mockResolvedValue(SKILL_ZIP);
    const onRefresh = vi.fn();

    render(<SkillsSection skills={[]} onRefresh={onRefresh} />);

    const file = new File(["content"], "my-skill.skill", { type: "application/zip" });
    const input = screen.getByLabelText(/upload skill zip/i);
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(skillsApi.installSkillFromZip).toHaveBeenCalledWith(file));
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});

describe("SkillsSection — Delete", () => {
  it("Delete prompts confirm and calls deleteSkill", async () => {
    vi.mocked(skillsApi.deleteSkill).mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onRefresh = vi.fn();

    render(<SkillsSection skills={[SKILL_LOCAL]} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole("button", { name: /delete skill web-research/i }));

    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(skillsApi.deleteSkill).toHaveBeenCalledWith("web-research"));
    expect(onRefresh).toHaveBeenCalledOnce();

    confirmSpy.mockRestore();
  });

  it("Delete does NOT call deleteSkill when confirm is cancelled", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onRefresh = vi.fn();

    render(<SkillsSection skills={[SKILL_LOCAL]} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole("button", { name: /delete skill web-research/i }));

    expect(skillsApi.deleteSkill).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });
});

describe("SkillsSection — Browse registry", () => {
  it("Browse registry button opens RegistryBrowserModal", async () => {
    render(<SkillsSection skills={[]} onRefresh={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: /browse registry/i }));

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /browse skill registry/i })).toBeInTheDocument(),
    );
  });
});
